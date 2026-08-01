"""Multi-channel batch runner — run many profiles in one pass.

Each item routes to the right flow by source.mode, sharing one ledger/work-root
so quota (per platform/day), daily caps, and budget accounting are enforced
across the whole batch. Failures are isolated: one channel erroring doesn't sink
the others.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..core import media
from ..core.profile import ContentProfile, SourceMode, load_profile
from ..core.state import Ledger


def run_batch(
    items: list[dict],
    *,
    profiles_dir: str | Path = "profiles",
    work_root: str | Path = ".rf_work",
    auto_approve: bool = False,
    publish: bool = False,
    dry_run: bool = True,
    creds: Optional[dict] = None,
    enforce_budget: bool = False,
) -> list[dict]:
    """Run a batch. Each item: {profile, input?, topic?, voice?}.

    `profile` may be an id/path or a ContentProfile. Returns one result dict per
    item (with an `error` key if that channel failed).
    """
    from . import run_footage, run_generative, run_hybrid  # lazy

    results: list[dict] = []
    for item in items:
        prof = item["profile"]
        if not isinstance(prof, ContentProfile):
            prof = load_profile(prof, profiles_dir=profiles_dir)
        try:
            mode = prof.source.mode
            if mode is SourceMode.generative:
                r = run_generative(prof, topic=item.get("topic"), work_root=work_root,
                                   auto_approve=auto_approve, publish=publish,
                                   dry_run=dry_run, creds=creds,
                                   enforce_budget=enforce_budget)
            elif mode is SourceMode.hybrid:
                r = run_hybrid(prof, topic=item.get("topic"), voice_input=item.get("voice"),
                               work_root=work_root, auto_approve=auto_approve,
                               publish=publish, dry_run=dry_run, creds=creds)
            else:  # footage
                src = item.get("input")
                if not src:  # allow demo footage in a batch
                    src = str(media.synth_test_clip(
                        Path(work_root) / f"_demo_{prof.id}.mp4",
                        duration=14.0, fps=30, size="640x360"))
                r = run_footage(src, prof, work_root=work_root, auto_approve=auto_approve,
                                publish=publish, dry_run=dry_run, creds=creds)
            r["profile"] = prof.id
            results.append(r)
        except Exception as e:  # noqa: BLE001 - isolate per-channel failure
            results.append({"profile": prof.id, "status": "error",
                            "error": f"{type(e).__name__}: {e}"})
    return results
