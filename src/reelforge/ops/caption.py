"""AI overlay captions — Claude 'sees' the ride and writes rider-voice lines.

Flow: extract a few keyframes -> send them to Claude (vision) with the profile's
themes (+ optional trend) -> Claude returns short reflective overlay lines.
Gated: uses Claude only when ANTHROPIC_API_KEY is present and has balance; else a
deterministic themed fallback. Burning the lines onto the video is done by
build.op_captions_from_script (reused).
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import OpResult

_MODEL = "claude-sonnet-4-5"

# Deterministic, on-theme lines used when Claude is unavailable.
_FALLBACK = [
    "The road doesn't ask who you were.",
    "Two wheels, one quiet mind.",
    "Grateful for the miles and the breath.",
    "Peace is found between the turns.",
    "Ride like you've forgiven yourself.",
    "Every mile is a small resurrection.",
    "Chase stillness, not just speed.",
    "The journey keeps the promises people don't.",
]


@op("extract_keyframes")
def op_extract_keyframes(ctx: OpContext, video: str, n: int = 3,
                         max_dim: int = 512) -> OpResult:
    """Pull n downscaled JPEG keyframes spread across the clip. One job: sample frames."""
    info = media.probe(video)
    dur = info.duration_s or 1.0
    n = max(1, n)
    times = [dur * (i + 1) / (n + 1) for i in range(n)]  # evenly spread, skip ends
    frames = []
    for i, t in enumerate(times):
        out = ctx.storage.path("caption", f"kf{i}.jpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        media.run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                   "-frames:v", "1", "-vf", f"scale={max_dim}:-1", "-q:v", "4", str(out)])
        frames.append(str(out))
    return OpResult(outputs={"frames": frames}, metrics={"n_frames": float(len(frames))},
                    message=f"{len(frames)} keyframe(s)")


def _fallback_lines(themes: list[str], count: int) -> list[str]:
    return _FALLBACK[:count] if count <= len(_FALLBACK) else \
        (_FALLBACK * (count // len(_FALLBACK) + 1))[:count]


def _build_prompt(themes: list[str], count: int, trend: str | None) -> str:
    theme_str = ", ".join(themes) if themes else "biker life, peace, gratitude"
    p = (
        "These frames are from a first-person POV cycling/biker short video. "
        "Look at the scene (setting, light, mood, motion). Then write exactly "
        f"{count} short overlay captions for the video, in a calm, reflective rider "
        f"voice. Draw on these themes: {theme_str}. "
        "Each line <= 8 words, evocative, no hashtags, no numbering, no quotes. "
        "One caption per line."
    )
    if trend:
        p += f" You may subtly nod to this trend if it fits: {trend}."
    return p


def _claude_lines(frames: list[str], themes: list[str], count: int,
                  trend: str | None) -> tuple[list[str], dict]:
    import anthropic

    content = []
    for f in frames:
        data = base64.standard_b64encode(Path(f).read_bytes()).decode()
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": _build_prompt(themes, count, trend)})
    client = anthropic.Anthropic()
    msg = client.messages.create(model=_MODEL, max_tokens=300,
                                 messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    lines = [ln.strip("-•*0123456789. \t\"'") for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln][:count]
    usage = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}
    return lines, usage


@op("ai_captions")
def op_ai_captions(ctx: OpContext, frames: list[str], themes: list[str],
                   count: int = 4, trend: str | None = None) -> OpResult:
    """Write overlay captions from the scene + themes. Claude if keyed, else fallback."""
    if os.environ.get("ANTHROPIC_API_KEY") and frames:
        try:
            lines, usage = _claude_lines(frames, themes, count, trend)
            if lines:
                # approx sonnet pricing: $3/M in, $15/M out
                cost = round(usage["in"] / 1e6 * 3 + usage["out"] / 1e6 * 15, 5)
                ctx.ledger.add_spend(ctx.run_id,
                                     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                     "llm_captions", "claude", cost, dry_run=False)
                while len(lines) < count:  # pad if Claude returned fewer
                    lines.append(_FALLBACK[len(lines) % len(_FALLBACK)])
                return OpResult(outputs={"lines": lines, "source": "claude"},
                                metrics={"est_usd": cost, "n_lines": float(len(lines))},
                                message=f"{len(lines)} caption(s) via Claude (${cost:.4f})")
        except Exception as e:  # noqa: BLE001 - fall back rather than fail the run
            ctx.log("ai_captions", "warn", f"claude failed, fallback: {e}")
    lines = _fallback_lines(themes, count)
    return OpResult(outputs={"lines": lines, "source": "fallback"},
                    metrics={"n_lines": float(len(lines))},
                    message=f"{len(lines)} caption(s) via fallback")
