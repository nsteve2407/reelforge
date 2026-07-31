"""Research subsystem: trend fetch (injected), ranking, hook fallback."""
from __future__ import annotations

from reelforge.core.context import OpContext
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.core.storage import Storage
from reelforge.ops import research as R


def _ctx(tmp_path, profile):
    led = Ledger(tmp_path / "db.sqlite")
    return OpContext(run_id=led.create_run(profile.id), profile=profile,
                     storage=Storage(tmp_path / "w"), ledger=led)


def test_rank_topics_merges_and_weights():
    prof = ContentProfile(id="p", niche="mountain biking")
    items = [
        {"topic": "biking trails", "score": 100, "source": "youtube_trending"},
        {"topic": "Biking Trails", "score": 50, "source": "google_trends"},  # dup
        {"topic": "cooking", "score": 120, "source": "google_trends"},
    ]
    ranked = R.rank_topics(items, prof)
    topics = [r["topic"] for r in ranked]
    # 'biking trails' merges 150 across 2 sources + niche fit -> outranks cooking(120)
    assert topics[0].lower() == "biking trails"
    assert len(ranked) == 2
    assert set(ranked[0]["sources"]) == {"youtube_trending", "google_trends"}


def test_fetch_trends_with_injected_provider(tmp_path):
    prof = ContentProfile(id="p", niche="cycling")
    ctx = _ctx(tmp_path, prof)

    def fake():
        return [{"topic": "gravel", "score": 10, "source": "fake"}]

    res = R.op_fetch_trends(ctx, providers=[fake])
    assert res.outputs["trends"] and res.outputs["trends"][0]["topic"] == "gravel"


def test_fetch_trends_default_offline_is_graceful(tmp_path):
    # no API keys / pytrends -> providers return [] without network, no error
    prof = ContentProfile(id="p")
    ctx = _ctx(tmp_path, prof)
    res = R.op_fetch_trends(ctx)
    assert res.ok and isinstance(res.outputs["trends"], list)


def test_rank_topics_op(tmp_path):
    prof = ContentProfile(id="p", niche="cycling")
    ctx = _ctx(tmp_path, prof)
    ranked = R.op_rank_topics(ctx, [{"topic": "a", "score": 1, "source": "s"}])
    assert ranked.outputs["topics"][0]["topic"] == "a"


def test_draft_hooks_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prof = ContentProfile(id="p", niche="cycling",
                          audience={"segment": "gen_z_millennial", "tone": "high_energy"})
    ctx = _ctx(tmp_path, prof)
    topics = [{"topic": "gravel riding"}, {"topic": "night ride"}]
    res = R.op_draft_hooks(ctx, topics, n=5)
    hooks = res.outputs["hooks"]
    assert res.outputs["source"] == "fallback"
    assert len(hooks) == 5
    assert any("gravel riding" in h for h in hooks)   # topic surfaced in a hook
