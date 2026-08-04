"""End-to-end footage flow: synth clip -> ranked highlights -> vertical draft."""
from __future__ import annotations

from pathlib import Path

import pytest

from reelforge.core import media
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.flows import run_footage


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    out = tmp_path_factory.mktemp("m") / "ride.mp4"
    return str(media.synth_test_clip(out, duration=14.0, fps=24, size="640x360"))


def test_footage_flow_end_to_end(tmp_path, clip):
    prof = ContentProfile(
        id="flow_test", niche="test ride",
        source={"proxy_transcode": False},
        edit={"length_s": [3, 6], "clips_per_video": [1, 2],
              "color_grade": {"look": "vivid_action"}, "captions": {"enabled": False}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"]},
    )
    res = run_footage(clip, prof, work_root=tmp_path / "work", auto_approve=True)

    assert res["status"] == "approved"
    draft = Path(res["draft"])
    assert draft.exists()
    info = media.probe(draft)
    assert (info.width, info.height) == (1080, 1920)   # reframed to 9:16
    assert res["n_highlights"] >= 1
    assert res["n_clips"] >= 1
    assert Path(res["review_card"]).exists()

    # ledger recorded the run + a draft asset + op events
    led = Ledger(tmp_path / "work" / "reelforge.db")
    run = led.get_run(res["run_id"])
    assert run["status"] == "approved"
    assert any(a["kind"] == "draft" for a in led.list_assets(res["run_id"]))
    ops_seen = {e["op"] for e in led.events(res["run_id"])}
    assert {"probe", "detect_scenes", "fuse_highlights", "render", "notify"} <= ops_seen


def test_generative_profile_rejected(tmp_path, clip):
    prof = ContentProfile(id="gen", source={"mode": "generative"})
    with pytest.raises(ValueError):
        run_footage(clip, prof, work_root=tmp_path / "w", auto_approve=True)


def test_vibe_selection_drives_captions_and_tags(tmp_path, clip):
    """A selected vibe swaps caption themes/keywords, the music mood, and the
    publish hashtags — proving one knob keeps words + music + tags coherent."""
    vibes = {
        "adrenaline": {
            "themes": ["adrenaline", "send it"],
            "keywords": ["throttle", "redline"],
            "music_mood": "aggressive electronic rock, 140 BPM",
            "hashtags": ["#sendit", "#adrenaline"],
            "look": "vivid_action",
        }
    }
    prof = ContentProfile(
        id="vibe_test", niche="test ride",
        source={"proxy_transcode": False},
        edit={"length_s": [3, 6], "clips_per_video": [1, 1],
              "captions": {"enabled": False}, "music": {"enabled": False}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"],
                 "hashtags": ["#default"]},
        vibes=vibes,
    )
    res = run_footage(clip, prof, work_root=tmp_path / "w", auto_approve=True,
                      publish=True, dry_run=True, vibe="adrenaline")
    assert res["status"] == "published"
    # the vibe's hashtags replaced the profile default for this run
    assert prof.publish.hashtags == ["#sendit", "#adrenaline"]
    # the vibe's color-grade look was applied for this run
    assert prof.edit.color_grade.look == "vivid_action"


def test_unknown_vibe_falls_back(tmp_path, clip):
    prof = ContentProfile(
        id="vibe_fallback", niche="test ride",
        source={"proxy_transcode": False},
        edit={"length_s": [3, 6], "clips_per_video": [1, 1],
              "captions": {"enabled": False}, "music": {"enabled": False}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"],
                 "hashtags": ["#default"]},
    )
    res = run_footage(clip, prof, work_root=tmp_path / "w", auto_approve=True,
                      vibe="does_not_exist")
    assert res["status"] == "approved"          # no crash on unknown vibe
    assert prof.publish.hashtags == ["#default"]  # untouched
