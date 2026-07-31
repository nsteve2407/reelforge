"""Review ops — the human-in-the-loop gate. Single-responsibility each.

MVP delivers the review card to LOCAL storage (a markdown + JSON card plus a
thumbnail) and logs it. Telegram/Slack/email are future notifier adapters
that implement the same `deliver(card)` shape. Nothing publishes without
passing this gate (the flow stops here when approval is required).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import Highlight, OpResult


@op("render_preview")
def op_render_preview(ctx: OpContext, src: str, at_s: float | None = None) -> OpResult:
    """Grab a single thumbnail frame from the draft. One job: a preview still."""
    info = media.probe(src)
    ts = at_s if at_s is not None else min(1.0, max(0.0, info.duration_s / 3.0))
    out = ctx.storage.path("review", "thumb.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    media.run(["ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(src),
               "-frames:v", "1", "-q:v", "3", str(out)])
    return OpResult(outputs={"thumb": str(out)}, artifacts={"thumb": str(out)},
                    message=f"thumbnail @ {ts:.2f}s")


def _caption_and_tags(ctx: OpContext) -> tuple[str, list[str]]:
    p = ctx.profile
    tags = list(p.publish.hashtags)
    caption = f"{p.niche}".strip() or p.id
    return caption, tags


@op("notify")
def op_notify(ctx: OpContext, draft: str, thumb: str | None = None,
              highlights: list[Highlight] | None = None) -> OpResult:
    """Emit a review card to local storage + ledger. One job: request approval.

    Returns outputs.approval_required so the flow knows whether to stop.
    """
    p = ctx.profile
    caption, tags = _caption_and_tags(ctx)
    info = media.probe(draft)
    card = {
        "run_id": ctx.run_id,
        "profile": p.id,
        "draft": str(draft),
        "thumb": str(thumb) if thumb else None,
        "duration_s": round(info.duration_s, 2),
        "resolution": f"{info.width}x{info.height}",
        "caption": caption,
        "hashtags": tags,
        "platforms": p.publish.platforms,
        "ai_disclosure": p.publish.ai_disclosure,
        "made_for_kids": p.publish.made_for_kids,
        "approval": p.publish.approval.value,
        "highlights": [asdict(h) for h in (highlights or [])],
    }
    card_json = ctx.storage.write_text(json.dumps(card, indent=2), "review", "card.json")
    md = _card_markdown(card)
    card_md = ctx.storage.write_text(md, "review", "card.md")
    approval_required = p.publish.approval.value == "required"
    ctx.log("notify", "info",
            f"review card ready ({info.width}x{info.height}, {info.duration_s:.1f}s); "
            f"approval={'required' if approval_required else 'auto'}")
    return OpResult(
        outputs={"card": str(card_json), "approval_required": approval_required},
        artifacts={"review_card": str(card_json), "review_md": str(card_md)},
        message=f"delivered review card (local) -> {card_md}",
    )


def _card_markdown(card: dict) -> str:
    lines = [
        f"# Review: {card['profile']}  (run {card['run_id']})",
        "",
        f"- **Draft:** `{card['draft']}`",
        f"- **Resolution:** {card['resolution']}  ·  **Duration:** {card['duration_s']}s",
        f"- **Caption:** {card['caption']}",
        f"- **Hashtags:** {' '.join(card['hashtags'])}",
        f"- **Platforms:** {', '.join(card['platforms']) or '(none)'}",
        f"- **AI disclosure:** {card['ai_disclosure']}  ·  **Made for kids:** {card['made_for_kids']}",
        f"- **Approval:** {card['approval']}",
        "",
        "## Highlights used",
    ]
    if card["highlights"]:
        for i, h in enumerate(card["highlights"], 1):
            lines.append(
                f"{i}. {h['start_s']:.1f}–{h['end_s']:.1f}s  (score {h['score']:.3f})"
            )
    else:
        lines.append("_(none recorded)_")
    lines += ["", "> Approve, edit, or reject before publishing."]
    return "\n".join(lines)
