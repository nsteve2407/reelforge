"""Credential catalog: env loading, readiness status, nested creds resolution."""
from __future__ import annotations

from reelforge.core.credentials import CATALOG, load_credentials, env_status
from reelforge.core.context import OpContext
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.core.storage import Storage
from reelforge.ops import publish as P


def _ctx(tmp_path, profile):
    led = Ledger(tmp_path / "db.sqlite")
    return OpContext(run_id=led.create_run(profile.id), profile=profile,
                     storage=Storage(tmp_path / "w"), ledger=led)


def test_catalog_covers_key_components():
    keys = {c.key for c in CATALOG}
    assert {"anthropic", "fal", "youtube_shorts", "instagram_reels"} <= keys


def test_load_credentials_shapes_nested_dict():
    env = {
        "ANTHROPIC_API_KEY": "sk-ant", "FAL_KEY": "fal-123",
        "REELFORGE_FAL_VIDEO_MODEL": "fal-ai/veo3/fast",
        "REELFORGE_IG_USER_ID": "178", "REELFORGE_IG_ACCESS_TOKEN": "tok",
        "REELFORGE_YT_TOKEN_FILE": "/tmp/yt.json",
    }
    creds = load_credentials(env)
    assert creds["anthropic"]["api_key"] == "sk-ant"
    assert creds["fal"]["api_key"] == "fal-123"
    assert creds["fal"]["video_model"] == "fal-ai/veo3/fast"
    assert creds["instagram_reels"] == {"ig_user_id": "178", "access_token": "tok"}
    assert creds["youtube_shorts"]["token_file"] == "/tmp/yt.json"
    assert "minimax" not in creds  # not provided


def test_load_credentials_empty():
    assert load_credentials({}) == {}


def test_env_status_ready_and_missing():
    env = {"ANTHROPIC_API_KEY": "x"}
    rows = {r["key"]: r for r in env_status(env)}
    assert rows["anthropic"]["ready"] is True
    assert rows["instagram_reels"]["ready"] is False
    assert "REELFORGE_IG_USER_ID" in rows["instagram_reels"]["missing_required"]


def test_op_publish_accepts_nested_creds_dry_run(tmp_path):
    prof = ContentProfile(id="b", publish={"platforms": ["youtube_shorts"],
                                           "schedule": "asap_on_trigger"})
    ctx = _ctx(tmp_path, prof)
    # nested creds present but dry_run -> still dry-run publisher, no error
    creds = {"youtube_shorts": {"token_file": "/tmp/yt.json"}}
    res = P.op_publish(ctx, "/tmp/draft.mp4", "youtube_shorts", dry_run=True, creds=creds)
    assert res.ok and res.outputs["dry_run"] is True
