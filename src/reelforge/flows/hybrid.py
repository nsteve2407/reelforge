"""Hybrid-mode pipeline: narration (your voice or TTS) + AI-generated b-roll.

Suits the TV-series-talk profile: a spoken take over generated cutaway visuals.
Reuses the generative media ops for b-roll + music, the build ops for assembly,
and the shared review/publish path. If `voice_input` is given it becomes the
narration (and sets the timeline length); otherwise narration is generated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..core import media
from ..core.context import OpContext
from ..core.profile import ContentProfile, SourceMode
from ..core.state import Ledger
from ..core.storage import Storage
from ..ops import generate as G
from ..ops import build, review
from ..ops import publish as pub


def run_hybrid(
    profile: ContentProfile,
    *,
    topic: Optional[str] = None,
    voice_input: Optional[str] = None,
    work_root: str | Path = ".rf_work",
    db_path: Optional[str | Path] = None,
    auto_approve: bool = False,
    publish: bool = False,
    dry_run: bool = True,
    creds: Optional[dict] = None,
) -> dict:
    if profile.source.mode is not SourceMode.hybrid:
        raise ValueError(f"profile '{profile.id}' is not hybrid-mode")

    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(db_path or work_root / "reelforge.db")
    run_id = ledger.create_run(profile.id, {"mode": "hybrid", "topic": topic,
                                            "voice_input": voice_input})
    storage = Storage(work_root / run_id)
    ctx = OpContext(run_id=run_id, profile=profile, storage=storage, ledger=ledger)
    target = profile.edit.target_w_h
    broll_provider = profile.generate.broll.get("provider") if not dry_run else None
    tts_provider = profile.generate.voiceover.provider if not dry_run else None
    music_provider = profile.generate.music.source if not dry_run else None

    try:
        # ---- script (take + b-roll scene prompts) ----
        ledger.update_run(run_id, "scripting")
        sc = G.op_write_script(ctx, topic=topic).outputs
        script = sc["script"]
        scenes = script["scenes"]
        n = len(scenes)

        # ---- narration: real voice input, else generated ----
        ledger.update_run(run_id, "generating")
        if voice_input and Path(voice_input).exists():
            total_s = media.probe(voice_input).duration_s or sc["total_s"]
            narration_path = voice_input
            narration_src = "input"
        else:
            total_s = sc["total_s"]
            narration_path = G.op_gen_voiceover(
                ctx, script["narration"], total_s, provider=tts_provider,
                dry_run=dry_run, creds=creds).outputs["audio"]
            narration_src = "generated"
        per = total_s / max(1, n)

        # ---- b-roll cutaways sized to the narration ----
        clips = []
        for i, scene in enumerate(scenes):
            clip = G.op_gen_scene_clip(ctx, i, scene["text"], target, per,
                                       provider=broll_provider, dry_run=dry_run,
                                       creds=creds).outputs["clip"]
            clips.append(clip)
        video = build.op_render(ctx, clips, name="broll").outputs["draft"]

        # ---- mix narration + music ----
        mood = profile.generate.music.mood or "tension_underscore"
        music = G.op_gen_music(ctx, mood, total_s, provider=music_provider,
                               dry_run=dry_run, creds=creds).outputs["audio"]
        video = build.op_mux_audio(ctx, video, [
            {"path": narration_path, "gain": 1.0}, {"path": music, "gain": 0.3},
        ], name="scored").outputs["path"]

        # ---- captions + grade ----
        ledger.update_run(run_id, "building")
        if profile.edit.captions.enabled:
            scenes_adj = [{"text": s["text"], "seconds": per} for s in scenes]
            video = build.op_captions_from_script(
                ctx, video, scenes_adj, style=profile.edit.captions.style).outputs["path"]
        draft = build.op_color_grade(ctx, video, profile.edit.color_grade.look).outputs["path"]

        # ---- review + publish ----
        ledger.update_run(run_id, "review")
        thumb = review.op_render_preview(ctx, draft).outputs["thumb"]
        notify = review.op_notify(ctx, draft, thumb, None)
        approval_required = notify.outputs["approval_required"] and not auto_approve
        status = "awaiting_approval" if approval_required else "approved"
        ledger.update_run(run_id, status, {"draft": str(draft)})

        published: list[dict] = []
        if status == "approved" and publish:
            ledger.update_run(run_id, "publishing")
            for platform in profile.publish.platforms:
                res = pub.op_publish(ctx, draft, platform, dry_run=dry_run, creds=creds)
                published.append({"platform": platform, "ok": res.ok,
                                  "url": res.outputs.get("url"),
                                  "dry_run": res.outputs.get("dry_run")})
            status = "published" if any(p["ok"] for p in published) else "publish_failed"
            ledger.update_run(run_id, status)

        return {
            "run_id": run_id, "status": status, "draft": str(draft),
            "thumb": str(thumb), "review_card": notify.outputs["card"],
            "title": script["title"], "n_scenes": n, "narration": narration_src,
            "published": published, "workdir": str(storage.root),
        }
    except Exception as e:  # noqa: BLE001
        ledger.update_run(run_id, "error", {"error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        ledger.close()
