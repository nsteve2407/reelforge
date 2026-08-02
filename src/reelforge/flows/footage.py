"""Footage-mode pipeline: real clips -> ranked highlights -> vertical draft -> review.

This is the runner: it creates a run, builds one OpContext, and calls the
atomic ops in order, updating ledger state. Each op stays a pure function, so
this same sequence maps 1:1 onto Prefect tasks/flow later (that's the only
thing that changes to move to a durable orchestrator).

Stages: ingest -> understand (multi-signal) -> build -> review gate.
Publishing is intentionally NOT here for the MVP: the flow stops at the
human-review card (Phase 1 = "draft -> notify -> manual upload").
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..core.context import OpContext
from ..core.profile import ContentProfile, SourceMode
from ..core.state import Ledger
from ..core.storage import Storage
from ..core.types import SignalTrack
from ..ops import ingest, understand, build, review, learn, caption
from ..ops import generate as G
from ..ops import publish as pub

# Default fusion weights per signal; profile.understand.score_for can re-bias.
_DEFAULT_WEIGHTS = {
    "scene_change": 1.0,
    "audio_energy": 1.0,
    "motion": 1.2,
    "gforce": 1.5,
}


def _weight_for(name: str, profile: ContentProfile) -> float:
    w = _DEFAULT_WEIGHTS.get(name, 1.0)
    # If the profile lists what to score for, gently upweight matching signals.
    score_for = set(profile.understand.score_for or [])
    if name == "motion" and ({"speed", "air_time", "near_miss"} & score_for):
        w += 0.5
    return w


def run_footage(
    input_path: str,
    profile: ContentProfile,
    *,
    work_root: str | Path = ".rf_work",
    db_path: Optional[str | Path] = None,
    auto_approve: bool = False,
    publish: bool = False,
    dry_run: bool = True,
    creds: dict | None = None,
) -> dict:
    if profile.source.mode is SourceMode.generative:
        raise ValueError(
            f"profile '{profile.id}' is generative; footage flow needs real input"
        )
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(db_path or work_root / "reelforge.db")
    run_id = ledger.create_run(profile.id, {"input": str(input_path)})
    storage = Storage(work_root / run_id)
    ctx = OpContext(run_id=run_id, profile=profile, storage=storage, ledger=ledger)

    try:
        ledger.update_run(run_id, "ingesting")
        hook = learn.op_select_hook(ctx).outputs["hook"]
        ledger.update_run(run_id, "ingesting", {"hook": hook})
        info = ingest.op_probe(ctx, input_path).outputs["media"]
        source = input_path
        if profile.source.proxy_transcode:
            proxy = ingest.op_transcode_proxy(ctx, input_path).outputs["proxy"]
            source = proxy  # analyze the proxy; edit from the original

        # ---- understand: independent signals -> fuse ----
        ledger.update_run(run_id, "understanding")
        tracks: list[SignalTrack] = []
        scenes_res = understand.op_detect_scenes(ctx, source)
        for key in ("track",):
            t = scenes_res.outputs.get(key)
            if isinstance(t, SignalTrack):
                tracks.append(t)
        for res in (understand.op_audio_energy(ctx, source),
                    understand.op_motion(ctx, source)):
            t = res.outputs.get("track")
            if isinstance(t, SignalTrack):
                tracks.append(t)
        tele = understand.op_extract_telemetry(ctx, input_path)
        if tele.outputs.get("track") is not None:
            tracks.append(tele.outputs["track"])

        for t in tracks:
            t.weight = _weight_for(t.name, profile)

        min_len, max_len = profile.edit.length_s
        fused = understand.op_fuse_highlights(
            ctx, info, tracks, min_len=min_len, max_len=max_len,
            top_k=max(1, profile.edit.clips_per_video[1]),
        )
        highlights = fused.outputs["highlights"]
        if not highlights:
            ledger.update_run(run_id, "failed", {"reason": "no highlights"})
            return {"run_id": run_id, "status": "failed", "reason": "no highlights found"}

        # ---- build: cut -> reframe -> grade -> captions ----
        ledger.update_run(run_id, "building")
        segments = build.op_select_clips(ctx, highlights, profile).outputs["segments"]
        target = profile.edit.target_w_h
        clips: list[str] = []
        for i, seg in enumerate(segments):
            clip = build.op_cut(ctx, input_path, seg, name=f"clip{i}").outputs["clip"]
            clip = build.op_reframe(ctx, clip, target, mode=profile.edit.reframe).outputs["path"]
            clip = build.op_color_grade(ctx, clip, profile.edit.color_grade.look).outputs["path"]
            if profile.edit.captions.enabled and profile.edit.captions.source == "transcribe":
                clip = build.op_captions(
                    ctx, clip, style=profile.edit.captions.style,
                    lang=profile.edit.captions.lang,
                ).outputs["path"]
            clips.append(clip)
        draft = build.op_render(ctx, clips, name="draft").outputs["draft"]

        # ---- AI overlay captions (Claude sees the scene + writes rider-voice lines) ----
        caps = profile.edit.captions
        if caps.enabled and caps.source == "ai":
            ledger.update_run(run_id, "captioning")
            frames = caption.op_extract_keyframes(
                ctx, draft, n=caps.keyframes).outputs["frames"]
            lines = caption.op_ai_captions(
                ctx, frames, caps.themes, count=caps.count).outputs["lines"]
            dur = ingest.op_probe(ctx, draft).outputs["media"].duration_s or 1.0
            per = dur / max(1, len(lines))
            scenes = [{"text": ln, "seconds": per} for ln in lines]
            draft = build.op_captions_from_script(
                ctx, draft, scenes, style=caps.style).outputs["path"]

        # ---- music bed (fal Stable Audio) mixed UNDER the ride audio ----
        mus = profile.edit.music
        if mus.enabled:
            ledger.update_run(run_id, "scoring")
            dur = ingest.op_probe(ctx, draft).outputs["media"].duration_s or 1.0
            fal_key = os.environ.get("FAL_KEY")
            use_fal = mus.source == "fal" and bool(fal_key)
            m = G.op_gen_music(
                ctx, mus.mood or "reflective", dur,
                provider="fal" if use_fal else None,
                dry_run=not use_fal,
                creds={"api_key": fal_key} if use_fal else None,
            ).outputs["audio"]
            draft = build.op_add_music_bed(
                ctx, draft, m, source_lufs=mus.source_lufs,
                music_lufs=mus.music_lufs).outputs["path"]

        # ---- review gate ----
        ledger.update_run(run_id, "review")
        thumb = review.op_render_preview(ctx, draft).outputs["thumb"]
        notify = review.op_notify(ctx, draft, thumb, highlights)
        approval_required = notify.outputs["approval_required"] and not auto_approve

        status = "awaiting_approval" if approval_required else "approved"
        ledger.update_run(run_id, status, {"draft": str(draft)})

        # ---- publish (only when approved) ----
        published: list[dict] = []
        if status == "approved" and publish:
            ledger.update_run(run_id, "publishing")
            for platform in profile.publish.platforms:
                res = pub.op_publish(ctx, draft, platform, dry_run=dry_run, creds=creds)
                published.append({"platform": platform, "ok": res.ok,
                                  "url": res.outputs.get("url"),
                                  "dry_run": res.outputs.get("dry_run"),
                                  "message": res.message})
            any_ok = any(p["ok"] for p in published)
            status = "published" if any_ok else "publish_failed"
            ledger.update_run(run_id, status)

        return {
            "run_id": run_id,
            "hook": hook,
            "status": status,
            "draft": str(draft),
            "thumb": str(thumb),
            "review_card": notify.outputs["card"],
            "n_highlights": len(highlights),
            "n_clips": len(clips),
            "published": published,
            "workdir": str(storage.root),
        }
    except Exception as e:  # noqa: BLE001
        ledger.update_run(run_id, "error", {"error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        ledger.close()


def publish_run(
    run_id: str,
    profile: ContentProfile,
    *,
    work_root: str | Path = ".rf_work",
    db_path: Optional[str | Path] = None,
    dry_run: bool = True,
    creds: dict | None = None,
) -> dict:
    """Publish the draft of a previously-approved run to its target platforms."""
    work_root = Path(work_root)
    ledger = Ledger(db_path or work_root / "reelforge.db")
    try:
        run = ledger.get_run(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        draft = run.get("meta", {}).get("draft")
        if not draft:
            drafts = ledger.list_assets(run_id, "draft")
            draft = drafts[-1]["path"] if drafts else None
        if not draft or not Path(draft).exists():
            raise FileNotFoundError(f"no draft found for run {run_id}")
        storage = Storage(work_root / run_id)
        ctx = OpContext(run_id=run_id, profile=profile, storage=storage, ledger=ledger)
        ledger.update_run(run_id, "publishing")
        published = []
        for platform in profile.publish.platforms:
            res = pub.op_publish(ctx, draft, platform, dry_run=dry_run, creds=creds)
            published.append({"platform": platform, "ok": res.ok,
                              "url": res.outputs.get("url"),
                              "dry_run": res.outputs.get("dry_run"),
                              "message": res.message})
        status = "published" if any(p["ok"] for p in published) else "publish_failed"
        ledger.update_run(run_id, status)
        return {"run_id": run_id, "status": status, "draft": draft,
                "published": published}
    finally:
        ledger.close()
