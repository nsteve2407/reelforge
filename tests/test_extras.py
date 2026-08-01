"""Integration hardening: OAuth helper, retry wrapper, hosting, Prefect adapter."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from reelforge.core import oauth, orchestrate, hosting
from reelforge.core.profile import ContentProfile
from reelforge.flows import prefect_flow


# ---- OAuth helper ----

def test_validate_client_secrets(tmp_path):
    good = tmp_path / "cs.json"
    good.write_text(json.dumps({"installed": {
        "client_id": "x", "client_secret": "y",
        "auth_uri": "https://a", "token_uri": "https://t"}}))
    ok, _ = oauth.validate_client_secrets(good)
    assert ok

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"installed": {"client_id": "x"}}))
    ok, why = oauth.validate_client_secrets(bad)
    assert not ok and "missing" in why

    assert not oauth.validate_client_secrets(tmp_path / "nope.json")[0]


def test_load_token_and_creds(tmp_path):
    p = tmp_path / "tok.json"
    p.write_text(json.dumps({"token": "t", "refresh_token": "r", "client_id": "c",
                             "client_secret": "s", "token_uri": "u", "scopes": []}))
    creds = oauth.token_to_creds(oauth.load_token(p))
    assert creds["token"] == "t" and creds["refresh_token"] == "r"


# ---- retry wrapper ----

def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    out = orchestrate.retry(flaky, retries=3, backoff=0, sleep=lambda _: None)
    assert out == "ok" and calls["n"] == 3


def test_retry_exhausts_and_raises():
    calls = {"n": 0}

    def always():
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        orchestrate.retry(always, retries=2, backoff=0, sleep=lambda _: None)
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_with_retries_decorator():
    state = {"n": 0}

    @orchestrate.with_retries(retries=2, backoff=0, sleep=lambda _: None)
    def f():
        state["n"] += 1
        if state["n"] < 2:
            raise IOError("x")
        return 42

    assert f() == 42 and state["n"] == 2


# ---- hosting ----

def test_local_file_host_serves(tmp_path):
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "clip.txt"
    f.write_bytes(b"hello-reel")
    with hosting.LocalFileHost(tmp_path) as h:
        url = h.url_for("sub/clip.txt")
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == b"hello-reel"


def test_ensure_public_url_prefers_media_url(tmp_path):
    assert hosting.ensure_public_url(tmp_path / "x.mp4",
                                     {"media_url": "https://cdn/x.mp4"}) == "https://cdn/x.mp4"
    assert hosting.ensure_public_url(tmp_path / "x.mp4", None) is None
    assert hosting.ensure_public_url(tmp_path / "x.mp4", {}) is None


def test_get_host_selection():
    assert hosting.get_host(None) is None
    assert hosting.get_host({}) is None
    h = hosting.get_host({"s3_bucket": "b"})
    assert h is not None and h.provider == "s3" and h.bucket == "b"


# ---- prefect adapter ----

def test_prefect_available_is_bool():
    assert isinstance(prefect_flow.prefect_available(), bool)


def test_orchestrated_footage_fallback(tmp_path):
    from reelforge.core import media
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    clip = str(media.synth_test_clip(tmp_path / "c.mp4", duration=8.0, fps=24, size="320x240"))
    prof = ContentProfile(id="orch", source={"proxy_transcode": False},
                          edit={"length_s": [2, 4], "clips_per_video": [1, 1],
                                "captions": {"enabled": False}},
                          publish={"approval": "auto"})
    res = prefect_flow.run_footage_orchestrated(clip, prof, work_root=tmp_path / "w",
                                                auto_approve=True)
    assert res["status"] == "approved" and Path(res["draft"]).exists()
