"""Budget guardrails: cost estimation, spend ledger, guard, flow trimming."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from reelforge.core import media
from reelforge.core.budget import estimate_cost, BudgetGuard, VIDEO_USD_PER_S
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.flows import run_generative


def _day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_estimate_cost():
    assert estimate_cost("video", "veo", seconds=10) == round(10 * VIDEO_USD_PER_S["veo"], 4)
    assert estimate_cost("video", None, seconds=4) == round(4 * VIDEO_USD_PER_S["dryrun"], 4)
    assert estimate_cost("voice", chars=2000) == round(2 * 0.015, 4)
    assert estimate_cost("music") == 0.20
    assert estimate_cost("image") == 0.04
    assert estimate_cost("other") == 0.0


def test_spend_ledger(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    rid = led.create_run("p")
    led.add_spend(rid, _day(), "video", "veo", 1.5, dry_run=False)
    led.add_spend(rid, _day(), "music", "fal", 0.2, dry_run=True)
    rs = led.run_spend(rid)
    assert rs["est_usd"] == pytest.approx(1.7)
    assert rs["charged_usd"] == pytest.approx(1.5)   # dry-run not charged
    assert led.day_spend(_day())["est_usd"] == pytest.approx(1.7)
    assert led.total_spend()["charged_usd"] == pytest.approx(1.5)


def test_budget_guard_allow(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    prof = ContentProfile(id="p", budget={"max_usd_per_video": 1.0})
    rid = led.create_run("p")
    g = BudgetGuard(led, prof)
    assert g.allow(rid, 0.8) is True
    g.record(rid, "video", "veo", seconds=6, dry_run=True)  # 6*0.15=0.90
    assert g.run_est(rid) == pytest.approx(0.90)
    assert g.allow(rid, 0.05) is True     # 0.95 <= 1.0
    assert g.allow(rid, 0.2) is False     # 1.10 > 1.0


def _gen_profile(budget, scenes=5):
    return ContentProfile(
        id="rhymes", niche="animals", source={"mode": "generative"},
        generate={"voiceover": {"enabled": True}, "music": {"mood": "soft_singalong"},
                  "animation": {"scenes_per_video": scenes}},
        edit={"aspect_ratio": "9:16", "length_s": [8, 12],
              "captions": {"enabled": False}, "color_grade": {"look": "none"}},
        publish={"approval": "auto"}, budget={"max_usd_per_video": budget},
    )


def test_generative_budget_trims_scenes(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    full = run_generative(_gen_profile(budget=99.0), topic="t",
                          work_root=tmp_path / "a", auto_approve=True)
    tight = run_generative(_gen_profile(budget=0.30), topic="t",
                           work_root=tmp_path / "b", auto_approve=True,
                           enforce_budget=True)
    assert full["n_scenes"] == 5
    assert 1 <= tight["n_scenes"] < 5     # trimmed to stay within $0.30/video
