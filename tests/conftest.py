"""Shared test fixtures: a tmp OpContext and a synthetic test clip."""
from __future__ import annotations

import pytest

from reelforge.core.context import OpContext
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.core.storage import Storage
from reelforge.core import media


@pytest.fixture
def profile() -> ContentProfile:
    return ContentProfile(id="test", niche="testing")


@pytest.fixture
def ctx(tmp_path, profile) -> OpContext:
    ledger = Ledger(tmp_path / "db.sqlite")
    storage = Storage(tmp_path / "work")
    run_id = ledger.create_run(profile.id)
    return OpContext(run_id=run_id, profile=profile, storage=storage, ledger=ledger)


@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """A real synthesized mp4 with video+audio (needs ffmpeg)."""
    if not media.have_ffmpeg():
        pytest.skip("ffmpeg not available")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    return str(media.synth_test_clip(out, duration=8.0, fps=24, size="320x240"))
