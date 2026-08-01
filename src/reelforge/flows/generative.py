"""Generative-mode pipeline: brief -> script -> scenes+voice+music -> draft -> review.

No input footage. Reuses the same review gate and publish path as the footage
flow. Media generation is dry-run by default (real fal/MiniMax when creds are
given). Suits the nursery-rhymes profile (and any generative niche).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..core.context import OpContext
from ..core.profile import ContentProfile, SourceMode
from ..core.state import Ledger
from ..core.storage import Storage
from ..core.budget import BudgetGuard, estimate_cost
from ..ops import generate as G
from ..ops import build, review
from ..ops import publish as pub


def run_generative(
    profile: ContentProfile,
    *,
    topic: Optional[str] = None,
    work_root: str | Path = ".rf_work",
    db_path: Optional[str | Path] = None,
    auto_approve: bool = False,
    publish: bool = False,
    dry_run: bool = True,
    creds: Optional[dict] = None,
    enforce_budget: bool = False,
) -> dict:
    if profile.source.mode is SourceMode.footage:
        raise ValueError(f"profile '{profile.id}' is footage-mode; use run_footage")

    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(db_path or work_root / "reelforge.db")
    run_id = ledger.create_run(profile.id, {"mode": "generative", "topic": topic})
    storage = Storage(work_root / run_id)
    ctx = OpContext(run_id=run_id, profile=profile, storage=storage, ledger=ledger)
    target = profile.edit.target_w_h
    gen_provider = profile.generate.animation.get("provider") if not dry_run else None
    tts_provider = profile.generate.voiceover.provider if not dry_run else None
    music_provider = profile.generate.music.source if not dry_run else None

    try:
        # ---- script ----
        ledger.update_run(run_id, "scripting")
        sc = G.op_write_script(ctx, topic=topic).outputs
        script, total_s = sc["script"], sc["total_s"]
        scenes = script["scenes"]

        # ---- generate scene clips (already at target 9:16) ----
        ledger.update_run(run_id, "generating")
        clips = []
        guard = BudgetGuard(ctx.ledger, profile)
        for i, scene in enumerate(scenes):
            per = float(scene["seconds"])
            if enforce_budget and clips and not guard.allow(
                    run_id, estimate_cost("video", gen_provider, seconds=per)):
                ledger.log_event(run_id, "budget", "trim",
                                 f"stopped at scene {i}; per-video budget "
                                 f"${profile.budget.max_usd_per_video} reached")
                break
            clip = G.op_gen_scene_clip(
                ctx, i, scene["text"], target, per,
                provider=gen_provider, dry_run=dry_run, creds=creds,
            ).outputs["clip"]
            clips.append(clip)
        scenes = scenes[:len(clips)]  # keep captions/timeline aligned with what we built
        video = build.op_render(ctx, clips, name="scenes").outputs["draft"]

        # ---- voice + music ----
        tracks = []
        if profile.generate.voiceover.enabled:
            v = G.op_gen_voiceover(ctx, script["narration"], total_s,
                                   provider=tts_provider, dry_run=dry_run,
                                   creds=creds).outputs["audio"]
            tracks.append({"path": v, "gain": 1.0})
        mood = profile.generate.music.mood or "soft_singalong"
        m = G.op_gen_music(ctx, mood, total_s, provider=music_provider,
                           dry_run=dry_run, creds=creds).outputs["audio"]
        tracks.append({"path": m, "gain": 0.35})
        video = build.op_mux_audio(ctx, video, tracks, name="scored").outputs["path"]

        # ---- captions (from known script timings) + grade ----
        ledger.update_run(run_id, "building")
        if profile.edit.captions.enabled:
            video = build.op_captions_from_script(
                ctx, video, scenes, style=profile.edit.captions.style).outputs["path"]
        draft = build.op_color_grade(ctx, video, profile.edit.color_grade.look).outputs["path"]

        # ---- review gate ----
        ledger.update_run(run_id, "review")
        thumb = review.op_render_preview(ctx, draft).outputs["thumb"]
        notify = review.op_notify(ctx, draft, thumb, None)
        approval_required = notify.outputs["approval_required"] and not auto_approve
        status = "awaiting_approval" if approval_required else "approved"
        ledger.update_run(run_id, status, {"draft": str(draft)})

        # ---- publish ----
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
            "title": script["title"], "n_scenes": len(scenes),
            "published": published, "workdir": str(storage.root),
        }
    except Exception as e:  # noqa: BLE001
        ledger.update_run(run_id, "error", {"error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        ledger.close()
