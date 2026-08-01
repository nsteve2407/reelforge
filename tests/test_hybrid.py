"""Hybrid mode: narration (generated or real) + AI b-roll."""
from __future__ import annotations

import pytest

from reelforge.core import media
from reelforge.core.profile import ContentProfile
from reelforge.flows import run_hybrid


def _hybrid_profile():
    return ContentProfile(
        id="tv", niche="show hot takes",
        source={"mode": "hybrid"},
        generate={"broll": {"provider": "veo"}, "voiceover": {"enabled": True},
                  "music": {"mood": "tension_underscore"},
                  "animation": {"scenes_per_video": 3}},
        edit={"aspect_ratio": "9:16", "length_s": [6, 12],
              "captions": {"enabled": True, "style": "bold_dynamic"},
              "color_grade": {"look": "clean_bright"}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"],
                 "ai_disclosure": True},
    )


def test_hybrid_generated_narration(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    res = run_hybrid(_hybrid_profile(), topic="finale theories",
                     work_root=tmp_path / "w", auto_approve=True, publish=True)
    assert res["status"] == "published"
    assert res["narration"] == "generated"
    info = media.probe(res["draft"])
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio
    assert res["n_scenes"] == 3


def test_hybrid_real_voice_sets_timeline(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    voice = str(media.synth_test_clip(tmp_path / "voice.mp4", duration=5.0, fps=24,
                                      size="160x120"))
    res = run_hybrid(_hybrid_profile(), topic="episode recap", voice_input=voice,
                     work_root=tmp_path / "w", auto_approve=True)
    assert res["narration"] == "input"
    dur = media.probe(res["draft"]).duration_s
    assert 4.0 <= dur <= 6.5          # timeline follows the ~5s narration


def test_non_hybrid_rejected():
    with pytest.raises(ValueError):
        run_hybrid(ContentProfile(id="g", source={"mode": "generative"}))
