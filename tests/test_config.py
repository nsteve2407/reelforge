"""Workspace config + .env loading."""
from __future__ import annotations

import os
from pathlib import Path

from reelforge.core.config import (WorkspaceConfig, load_workspace, save_workspace,
                                   load_dotenv)

REPO = Path(__file__).resolve().parents[1]


def test_defaults_when_missing(tmp_path):
    cfg = load_workspace(tmp_path / "nope.yaml")
    assert cfg.active_profile is None
    assert cfg.profiles_dir == "profiles" and cfg.work_dir == ".rf_work"


def test_shipped_config_has_bike_pov():
    cfg = load_workspace(REPO / "reelforge.yaml")
    assert cfg.active_profile == "bike_pov"


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "reelforge.yaml"
    save_workspace(WorkspaceConfig(active_profile="nursery_rhymes", auto_approve=True), p)
    cfg = load_workspace(p)
    assert cfg.active_profile == "nursery_rhymes" and cfg.auto_approve is True


def test_load_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('REELFORGE_TEST_KEY=hello123\n# comment\nFAL_KEY="abc"\n')
    monkeypatch.delenv("REELFORGE_TEST_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert load_dotenv(env) is True
    assert os.environ["REELFORGE_TEST_KEY"] == "hello123"
    assert os.environ["FAL_KEY"] == "abc"
    assert load_dotenv(tmp_path / "absent.env") is False


def test_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("REELFORGE_TEST_KEY2", "original")
    (tmp_path / ".env").write_text("REELFORGE_TEST_KEY2=changed\n")
    load_dotenv(tmp_path / ".env")
    assert os.environ["REELFORGE_TEST_KEY2"] == "original"  # setdefault semantics
