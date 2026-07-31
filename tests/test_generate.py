"""Generative mode: script fallback, dry-run media gen, mux, captions, e2e."""
from __future__ import annotations

from pathlib import Path

import pytest

from reelforge.core import media
from reelforge.core.profile import ContentProfile
from reelforge.ops import generate as G
from reelforge.ops import build
from reelforge.flows import run_generative


def _gen_profile(**over):
    base = dict(
        id="rhymes", niche="happy animals",
        source={"mode": "generative"},
        generate={"voiceover": {"enabled": True}, "music": {"mood": "soft_singalong"},
                  "animation": {"scenes_per_video": 3}},
        edit={"aspect_ratio": "9:16", "length_s": [6, 12],
              "captions": {"enabled": True, "style": "singalong_lyrics"},
              "color_grade": {"look": "warm_storybook"}},
        publish={"approval": "auto", "platforms": ["youtube_shorts"],
                 "made_for_kids": True, "ai_disclosure": True},
    )
    base.update(over)
    return ContentProfile(**base)


# ---- script (LLM-gated fallback) ----

def test_write_script_fallback(ctx, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = G.op_write_script(ctx, topic="tiny turtles", n_scenes=4)
    sc = res.outputs["script"]
    assert res.outputs["source"] == "fallback"
    assert len(sc["scenes"]) == 4
    assert sc["narration"] and sc["title"]
    assert all(s["seconds"] > 0 for s in sc["scenes"])


# ---- dry-run media generation ----

def test_gen_scene_clip_dims_and_duration(ctx):
    res = G.op_gen_scene_clip(ctx, 0, "a happy sun", (216, 384), 2.0)
    info = media.probe(res.outputs["clip"])
    assert (info.width, info.height) == (216, 384)
    assert 1.5 <= info.duration_s <= 2.6
    assert info.has_audio  # silent track present so concat works


def test_gen_voice_and_music(ctx):
    v = G.op_gen_voiceover(ctx, "la la la", 3.0).outputs["audio"]
    m = G.op_gen_music(ctx, "soft_singalong", 3.0).outputs["audio"]
    for a in (v, m):
        # audio-only files: ffprobe format duration
        import subprocess, json
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "json", a],
                             capture_output=True, text=True).stdout
        assert 2.5 <= float(json.loads(out)["format"]["duration"]) <= 3.6


def test_mux_and_script_captions(ctx):
    a = G.op_gen_scene_clip(ctx, 0, "x", (216, 384), 2.0).outputs["clip"]
    b = G.op_gen_scene_clip(ctx, 1, "y", (216, 384), 2.0).outputs["clip"]
    video = build.op_render(ctx, [a, b], name="s").outputs["draft"]
    voice = G.op_gen_voiceover(ctx, "hello", 4.0).outputs["audio"]
    music = G.op_gen_music(ctx, "soft_singalong", 4.0).outputs["audio"]
    muxed = build.op_mux_audio(ctx, video, [{"path": voice, "gain": 1.0},
                                            {"path": music, "gain": 0.3}]).outputs["path"]
    assert media.probe(muxed).has_audio
    scenes = [{"text": "hello", "seconds": 2.0}, {"text": "world", "seconds": 2.0}]
    res = build.op_captions_from_script(ctx, muxed, scenes)
    assert Path(res.outputs["path"]).exists()
    assert media.probe(res.outputs["path"]).duration_s > 0


# ---- end to end ----

def test_generative_flow_end_to_end(tmp_path):
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    prof = _gen_profile()
    res = run_generative(prof, topic="dancing ducks", work_root=tmp_path / "w",
                         auto_approve=True, publish=True, dry_run=True)
    assert res["status"] == "published"
    info = media.probe(res["draft"])
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio
    assert res["n_scenes"] == 3
    assert res["published"] and res["published"][0]["dry_run"] is True


def test_footage_profile_rejected_by_generative():
    with pytest.raises(ValueError):
        run_generative(ContentProfile(id="f", source={"mode": "footage"}))
