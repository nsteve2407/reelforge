"""Review-gate ops: thumbnail + local review card."""
from __future__ import annotations

import json
from pathlib import Path

from reelforge.core.profile import ContentProfile
from reelforge.core.context import OpContext
from reelforge.core.state import Ledger
from reelforge.core.storage import Storage
from reelforge.core.types import Highlight
from reelforge.ops import review


def _ctx(tmp_path, approval="required"):
    prof = ContentProfile(id="rev", niche="testing",
                          publish={"approval": approval, "hashtags": ["#Shorts"],
                                   "platforms": ["youtube_shorts"]})
    led = Ledger(tmp_path / "db.sqlite")
    return OpContext(run_id=led.create_run(prof.id), profile=prof,
                     storage=Storage(tmp_path / "w"), ledger=led)


def test_render_preview(tmp_path, sample_clip):
    ctx = _ctx(tmp_path)
    res = review.op_render_preview(ctx, sample_clip)
    assert res.ok
    assert Path(res.outputs["thumb"]).exists()


def test_notify_required(tmp_path, sample_clip):
    ctx = _ctx(tmp_path, approval="required")
    hi = [Highlight(1.0, 4.0, 0.9, {"motion": 0.8}), Highlight(5.0, 7.0, 0.5)]
    res = review.op_notify(ctx, sample_clip, thumb=None, highlights=hi)
    assert res.outputs["approval_required"] is True
    card = json.loads(Path(res.outputs["card"]).read_text())
    assert card["profile"] == "rev"
    assert card["hashtags"] == ["#Shorts"]
    assert len(card["highlights"]) == 2
    md = Path(res.artifacts["review_md"]).read_text()
    assert "Review:" in md and "Highlights used" in md


def test_notify_auto(tmp_path, sample_clip):
    ctx = _ctx(tmp_path, approval="auto")
    res = review.op_notify(ctx, sample_clip, thumb=None, highlights=[])
    assert res.outputs["approval_required"] is False
