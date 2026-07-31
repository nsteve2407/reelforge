"""Ingest ops — bring media in and describe it. Single-responsibility each.

Reference op (`op_probe`) establishes the contract every other op follows.
`op_dedupe` and `op_transcode_proxy` complete the stage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import OpResult


@op("probe")
def op_probe(ctx: OpContext, src: str) -> OpResult:
    """Probe a source video -> MediaInfo. One job: describe the media."""
    info = media.probe(src)
    art = ctx.storage.write_text(json.dumps(asdict(info), indent=2), "ingest", "probe.json")
    return OpResult(
        outputs={"media": info, "src": str(src)},
        artifacts={"probe": str(art)},
        metrics={"duration_s": info.duration_s, "fps": info.fps},
        message=f"{info.width}x{info.height} {info.duration_s:.1f}s audio={info.has_audio}",
    )


@op("dedupe")
def op_dedupe(ctx: OpContext, src: str, seen: set[str] | None = None) -> OpResult:
    """Hash a file (BLAKE2b, streamed) to detect duplicates. One job: identity.

    Returns outputs.duplicate=True if the digest is already in `seen`.
    """
    h = hashlib.blake2b(digest_size=16)
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    dup = bool(seen and digest in seen)
    return OpResult(
        outputs={"digest": digest, "duplicate": dup},
        metrics={"duplicate": 1.0 if dup else 0.0},
        message=f"digest={digest} duplicate={dup}",
    )


@op("transcode_proxy")
def op_transcode_proxy(ctx: OpContext, src: str, height: int = 360) -> OpResult:
    """Make a low-res proxy for fast analysis. One job: cheap analysis copy.

    Skips (returns the source) if the source is already <= target height.
    """
    info = media.probe(src)
    if info.height and info.height <= height:
        return OpResult(outputs={"proxy": str(src), "skipped": True},
                        message="source already low-res; proxy skipped")
    out = ctx.storage.path("ingest", "proxy.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    media.run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "28", "-an", str(out),
    ])
    return OpResult(
        outputs={"proxy": str(out), "skipped": False},
        artifacts={"proxy": str(out)},
        message=f"proxy @ {height}p",
    )
