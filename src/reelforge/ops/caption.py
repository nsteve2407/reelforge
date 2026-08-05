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
    theme_str = ", ".join(themes) if themes else "biker life, gratitude, freedom"
    p = (
        "You're a rider writing short text overlays for a first-person POV riding "
        "Short (motorcycle or bicycle — match what you actually see in the frames). "
        "Look at these frames — the setting, light, mood, and motion — and "
        f"write exactly {count} captions that read like real thoughts you'd have on "
        "this ride.\n\n"
        "Voice: casual, warm, a little playful — like texting a friend, NOT a "
        "motivational poster. Avoid clichés, corny lines, and anything preachy.\n"
        "Make the set COHERENT: the lines should flow together like one small moment "
        f"across the ride (a beginning, a middle, a payoff). Loosely inspired by these "
        f"vibes (don't force every one, don't name them literally): {theme_str}.\n"
        "Vary the feel across the lines — mix one relatable/funny, one light and "
        "grateful, one that lands with a little meaning.\n\n"
        "Rules: 3-7 words each; simple everyday words; no hashtags, no emojis, no "
        "quotes, no numbering, no ending punctuation. Output ONLY the caption lines "
        f"— exactly {count} of them, one per line, with NO preamble, intro, header, "
        "or explanation (never write things like 'Here are' or 'Looking at')."
    )
    if trend:
        p += f"\nIf it fits naturally, you may nod to what's trending: {trend}."
    return p


_META = ("here are", "here's", "caption", "looking at", "these frames",
         "cohesive", "coherent", "i'll", "sure,", "note:", "overlay", "first-person")


def _is_caption(ln: str) -> bool:
    """Reject model preamble/meta lines; keep only plausible short overlays."""
    low = ln.lower()
    if not ln or ln.rstrip().endswith(":"):
        return False
    if len(ln.split()) > 12:
        return False
    return not any(m in low for m in _META)


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
    raw = [ln.strip("-•*0123456789. \t\"'") for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in raw if _is_caption(ln)][:count]
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
