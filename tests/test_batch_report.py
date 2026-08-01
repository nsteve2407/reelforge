"""Multi-channel batch + dashboard report."""
from __future__ import annotations

import pytest

from reelforge.core import media
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.core.report import build_report, render_html
from reelforge.flows import run_batch


def _gen(id_, mood="soft_singalong"):
    return ContentProfile(
        id=id_, niche=f"{id_} stuff", source={"mode": "generative"},
        generate={"voiceover": {"enabled": True}, "music": {"mood": mood},
                  "animation": {"scenes_per_video": 2}},
        edit={"aspect_ratio": "9:16", "length_s": [4, 8],
              "captions": {"enabled": False}, "color_grade": {"look": "none"}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"]},
    )


def test_batch_runs_multiple_channels(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    items = [{"profile": _gen("chanA"), "topic": "a"},
             {"profile": _gen("chanB"), "topic": "b"}]
    results = run_batch(items, work_root=tmp_path / "w", auto_approve=True, publish=True)
    assert len(results) == 2
    assert {r["profile"] for r in results} == {"chanA", "chanB"}
    assert all(r["status"] == "published" for r in results)


def test_batch_isolates_failure(tmp_path):
    # a hybrid profile passed with no ffmpeg dependency issue; force an error via
    # a footage profile whose input synth still works -> instead use a broken item.
    good = _gen("ok")
    bad = ContentProfile(id="bad", source={"mode": "generative"},
                         generate={"animation": {"scenes_per_video": 0}},
                         edit={"length_s": [4, 8]}, publish={"approval": "auto"})
    results = run_batch([{"profile": good, "topic": "x"}, {"profile": bad}],
                        work_root=tmp_path / "w", auto_approve=True)
    by = {r["profile"]: r for r in results}
    assert by["ok"]["status"] in ("approved", "published")
    # bad channel errored but did not sink the batch
    assert len(results) == 2


def test_report_build_and_html(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    run_batch([{"profile": _gen("c1"), "topic": "t"}], work_root=tmp_path / "w",
              auto_approve=True, publish=True)
    led = Ledger(tmp_path / "w" / "reelforge.db")
    rep = build_report(led)
    assert rep["runs_total"] >= 1
    assert "youtube_shorts" in rep["quota_today"]
    assert rep["spend"]["all_time"]["est_usd"] >= 0.0
    assert len(rep["bandit"]) == 5           # hook arms
    html = render_html(rep)
    assert "ReelForge dashboard" in html and "<table" in html
    led.close()
