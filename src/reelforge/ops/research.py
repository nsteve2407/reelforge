"""Research ops — trends + ideation. Classical ranking; LLM only for hooks.

`op_fetch_trends` aggregates provider signals (injectable for testing / offline),
`op_rank_topics` ranks them deterministically, and `op_draft_hooks` writes hooks
with Claude when ANTHROPIC_API_KEY is set, else a deterministic template fallback.
This keeps the one genuine LLM touch (creative ideation) optional and gated.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from ..core.context import OpContext
from ..core.op import op
from ..core.types import OpResult

# A provider is a callable returning list[{"topic": str, "score": float, "source": str}]
Provider = Callable[[], list[dict]]


# ------------------------------------------------------------------ pure logic

def rank_topics(items: list[dict], profile) -> list[dict]:
    """Dedupe + normalize + fit-weight topics. Pure, deterministic."""
    if not items:
        return []
    # merge duplicates (case-insensitive), summing scores across sources
    merged: dict[str, dict] = {}
    for it in items:
        key = str(it.get("topic", "")).strip().lower()
        if not key:
            continue
        m = merged.setdefault(key, {"topic": it["topic"], "score": 0.0, "sources": set()})
        m["score"] += float(it.get("score", 0.0))
        m["sources"].add(it.get("source", "?"))
    vals = list(merged.values())
    hi = max((m["score"] for m in vals), default=1.0) or 1.0
    niche_words = set((profile.niche or "").lower().split())
    out = []
    for m in vals:
        base = m["score"] / hi
        fit = 1.0 + 0.25 * len(niche_words & set(m["topic"].lower().split()))
        cross = 1.0 + 0.1 * (len(m["sources"]) - 1)  # multi-source bonus
        out.append({"topic": m["topic"], "score": round(base * fit * cross, 4),
                    "sources": sorted(m["sources"])})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _fallback_hooks(topics: list[dict], profile, n: int) -> list[str]:
    """Deterministic hook templates when no LLM is available."""
    tone = (profile.audience.tone or "").replace("_", " ")
    templates = [
        "POV: {t}",
        "The truth about {t} nobody tells you",
        "{t} — but make it {tone}",
        "You won't believe this {t} moment",
        "3 things about {t} that changed everything",
        "Watch this before you try {t}",
    ]
    hooks: list[str] = []
    picks = topics or [{"topic": profile.niche or profile.id}]
    i = 0
    while len(hooks) < n:
        t = picks[i % len(picks)]["topic"]
        tmpl = templates[len(hooks) % len(templates)]
        hooks.append(tmpl.format(t=t, tone=tone or "unmissable").strip())
        i += 1
        if i > n * len(templates):  # safety
            break
    return hooks[:n]


# --------------------------------------------------------------- providers (opt)

def youtube_trending_provider(region: str = "US",
                              api_key: Optional[str] = None) -> list[dict]:
    """YouTube most-popular via Data API. Returns [] without a key / on error."""
    api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return []
    try:
        from googleapiclient.discovery import build  # lazy
        yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        resp = yt.videos().list(part="snippet,statistics", chart="mostPopular",
                                regionCode=region, maxResults=25).execute()
        out = []
        for it in resp.get("items", []):
            views = float(it.get("statistics", {}).get("viewCount", 0))
            out.append({"topic": it["snippet"]["title"], "score": views,
                        "source": "youtube_trending"})
        return out
    except Exception:  # noqa: BLE001
        return []


def google_trends_provider(keywords: Optional[list[str]] = None) -> list[dict]:
    """Google Trends via pytrends. Returns [] if pytrends absent / on error."""
    try:
        from pytrends.request import TrendReq  # lazy, optional
    except Exception:  # noqa: BLE001
        return []
    try:
        pt = TrendReq()
        df = pt.trending_searches()
        return [{"topic": str(t), "score": float(len(df) - i), "source": "google_trends"}
                for i, t in enumerate(df[0].tolist())]
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------------ ops

@op("fetch_trends")
def op_fetch_trends(ctx: OpContext, providers: Optional[list[Provider]] = None) -> OpResult:
    """Aggregate trend signals from providers. One job: collect raw trends."""
    if providers is None:
        providers = [youtube_trending_provider, google_trends_provider]
    items: list[dict] = []
    used: list[str] = []
    for prov in providers:
        try:
            got = prov() or []
        except Exception:  # noqa: BLE001
            got = []
        if got:
            used.append(got[0].get("source", "?"))
        items.extend(got)
    return OpResult(outputs={"trends": items, "sources": used},
                    metrics={"n_trends": float(len(items))},
                    message=f"{len(items)} trend item(s) from {len(set(used))} source(s)")


@op("rank_topics")
def op_rank_topics(ctx: OpContext, items: list[dict]) -> OpResult:
    """Rank/merge topics by fit + cross-source. One job: ranking (pure)."""
    ranked = rank_topics(items, ctx.profile)
    return OpResult(outputs={"topics": ranked}, metrics={"n_topics": float(len(ranked))},
                    message=f"ranked {len(ranked)} topic(s)")


@op("draft_hooks")
def op_draft_hooks(ctx: OpContext, topics: list[dict], n: int = 5) -> OpResult:
    """Draft hook lines. Claude if ANTHROPIC_API_KEY set, else template fallback."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            hooks = _claude_hooks(ctx.profile, topics, n)
            return OpResult(outputs={"hooks": hooks, "source": "claude"},
                            message=f"{len(hooks)} hook(s) via Claude")
        except Exception as e:  # noqa: BLE001 - fall back rather than fail the run
            ctx.log("draft_hooks", "warn", f"claude failed, fallback: {e}")
    hooks = _fallback_hooks(topics, ctx.profile, n)
    return OpResult(outputs={"hooks": hooks, "source": "fallback"},
                    message=f"{len(hooks)} hook(s) via fallback")


def _claude_hooks(profile, topics: list[dict], n: int) -> list[str]:
    import anthropic  # lazy, optional

    client = anthropic.Anthropic()
    topic_list = ", ".join(t["topic"] for t in topics[:8]) or (profile.niche or profile.id)
    prompt = (
        f"You write punchy short-form video hooks. Niche: {profile.niche}. "
        f"Audience: {profile.audience.segment} ({profile.audience.tone}). "
        f"Trending topics: {topic_list}. "
        f"Write {n} distinct <=12-word hooks, one per line, no numbering."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return [ln.strip("-• ").strip() for ln in text.splitlines() if ln.strip()][:n]
