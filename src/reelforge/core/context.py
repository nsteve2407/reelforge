"""OpContext — the single object every atomic op receives.

Carries the run id, the resolved ContentProfile, a Storage rooted at the
run's workdir, and the Ledger. Ops read inputs from arguments and write
outputs under `ctx.storage`; cross-cutting logging goes through `ctx`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .profile import ContentProfile
from .state import Ledger
from .storage import Storage


@dataclass
class OpContext:
    run_id: str
    profile: ContentProfile
    storage: Storage          # rooted at the per-run workdir
    ledger: Ledger

    def log(self, op: str, status: str, message: str = "") -> None:
        self.ledger.log_event(self.run_id, op, status, message)

    def asset(self, kind: str, path: str, **meta) -> str:
        return self.ledger.add_asset(self.run_id, kind, str(path), meta or None)
