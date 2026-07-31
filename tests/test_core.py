"""Foundation tests: profile parsing, storage, ledger, media + ingest ops."""
from __future__ import annotations

from pathlib import Path

import pytest

from reelforge.core.profile import ContentProfile, SourceMode, load_profile
from reelforge.core.storage import Storage
from reelforge.core.state import Ledger
from reelforge.core import media
from reelforge.core.types import Segment, SignalTrack
from reelforge.ops import ingest

PROFILES = Path(__file__).resolve().parents[1] / "profiles"


# ---- ContentProfile ----

def test_all_shipped_profiles_parse():
    ids = {}
    for y in PROFILES.glob("*.yaml"):
        p = ContentProfile.from_yaml(y)
        ids[p.id] = p
    assert {"bike_pov", "nursery_rhymes", "tv_series_talk"} <= set(ids)
    assert ids["bike_pov"].source.mode is SourceMode.footage
    assert ids["nursery_rhymes"].source.mode is SourceMode.generative
    assert ids["tv_series_talk"].source.mode is SourceMode.hybrid


def test_profile_defaults_and_aspect():
    p = ContentProfile(id="x")
    assert p.edit.aspect_ratio == "9:16"
    assert p.edit.target_w_h == (1080, 1920)
    p2 = ContentProfile(id="y", edit={"aspect_ratio": "1:1"})
    assert p2.edit.target_w_h == (1080, 1080)


def test_length_validation():
    with pytest.raises(Exception):
        ContentProfile(id="bad", edit={"length_s": [40, 10]})


def test_load_profile_by_id():
    p = load_profile("bike_pov", profiles_dir=PROFILES)
    assert p.id == "bike_pov"
    with pytest.raises(FileNotFoundError):
        load_profile("does_not_exist", profiles_dir=PROFILES)


# ---- Storage ----

def test_storage_roundtrip(tmp_path):
    s = Storage(tmp_path / "root")
    s.write_text("hi", "a", "b.txt")
    assert s.exists("a", "b.txt")
    assert s.read_text("a", "b.txt") == "hi"
    child = s.sub("clips")
    child.write_bytes(b"\x00\x01", "c.bin")
    assert child.read_bytes("c.bin") == b"\x00\x01"
    assert s.url("a", "b.txt").startswith("file://")


# ---- Ledger ----

def test_ledger_lifecycle(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    rid = led.create_run("bike_pov", {"note": "t"})
    led.update_run(rid, "running", {"extra": 1})
    run = led.get_run(rid)
    assert run["status"] == "running"
    assert run["meta"]["note"] == "t" and run["meta"]["extra"] == 1
    led.add_asset(rid, "draft", "/x/y.mp4", {"w": 1080})
    assert led.list_assets(rid, "draft")[0]["path"] == "/x/y.mp4"
    led.log_event(rid, "probe", "ok", "msg")
    assert any(e["op"] == "probe" for e in led.events(rid))


# ---- types ----

def test_segment_and_signaltrack():
    seg = Segment(1.0, 3.5)
    assert seg.duration == 2.5
    assert seg.overlaps(Segment(3.0, 4.0))
    assert not seg.overlaps(Segment(3.5, 4.0))
    with pytest.raises(ValueError):
        Segment(2.0, 1.0)
    with pytest.raises(ValueError):
        SignalTrack("x", [0.0, 1.0], [0.1])


# ---- media + ingest ops (need ffmpeg) ----

def test_probe_and_op_probe(ctx, sample_clip):
    info = media.probe(sample_clip)
    assert info.width == 320 and info.height == 240
    assert 7.0 <= info.duration_s <= 9.0
    assert info.has_audio
    res = ingest.op_probe(ctx, sample_clip)
    assert res.ok and "media" in res.outputs
    assert Path(res.artifacts["probe"]).exists()
    # event was logged
    assert any(e["op"] == "probe" for e in ctx.ledger.events(ctx.run_id))


def test_extract_audio_and_read(ctx, sample_clip):
    wav = media.extract_audio_wav(sample_clip, ctx.storage.path("a.wav"))
    data, sr = media.read_wav_mono(wav)
    assert sr == 16000 and data.ndim == 1 and data.size > 1000
    assert float(abs(data).max()) > 0.0


def test_op_dedupe(ctx, sample_clip):
    r1 = ingest.op_dedupe(ctx, sample_clip)
    assert not r1.outputs["duplicate"]
    seen = {r1.outputs["digest"]}
    r2 = ingest.op_dedupe(ctx, sample_clip, seen=seen)
    assert r2.outputs["duplicate"]
