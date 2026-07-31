"""SQLite content ledger — job state, artifacts, and an op event log.

SQLite for local dev; the same schema/DDL runs on Postgres later (only the
connection layer changes). Kept dependency-free (stdlib sqlite3) so the
foundation has no ORM to fight. JSON blobs are stored as TEXT.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id   TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    path       TEXT NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL,
    op       TEXT NOT NULL,
    status   TEXT NOT NULL,
    message  TEXT NOT NULL DEFAULT '',
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_assets_run ON assets(run_id);
CREATE TABLE IF NOT EXISTS quota (
    platform TEXT NOT NULL,
    day      TEXT NOT NULL,
    units    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, day)
);
"""


def _now() -> float:
    return time.time()


class Ledger:
    def __init__(self, db_path: str | Path = "reelforge.db"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ---- runs ----
    def create_run(self, profile_id: str, meta: Optional[dict] = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = _now()
        self.conn.execute(
            "INSERT INTO runs(run_id,profile_id,status,created_at,updated_at,meta) VALUES (?,?,?,?,?,?)",
            (run_id, profile_id, "created", now, now, json.dumps(meta or {})),
        )
        self.conn.commit()
        return run_id

    def update_run(self, run_id: str, status: str, meta: Optional[dict] = None) -> None:
        if meta is None:
            self.conn.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE run_id=?",
                (status, _now(), run_id),
            )
        else:
            cur = self.get_run(run_id)
            merged = {**(cur.get("meta", {}) if cur else {}), **meta}
            self.conn.execute(
                "UPDATE runs SET status=?, updated_at=?, meta=? WHERE run_id=?",
                (status, _now(), json.dumps(merged), run_id),
            )
        self.conn.commit()

    def get_run(self, run_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["meta"] = json.loads(d["meta"])
        return d

    # ---- assets ----
    def add_asset(self, run_id: str, kind: str, path: str, meta: Optional[dict] = None) -> str:
        asset_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO assets(asset_id,run_id,kind,path,meta,created_at) VALUES (?,?,?,?,?,?)",
            (asset_id, run_id, kind, str(path), json.dumps(meta or {}), _now()),
        )
        self.conn.commit()
        return asset_id

    def list_assets(self, run_id: str, kind: Optional[str] = None) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM assets WHERE run_id=? AND kind=? ORDER BY created_at",
                (run_id, kind),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM assets WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d["meta"])
            out.append(d)
        return out

    # ---- events ----
    def log_event(self, run_id: str, op: str, status: str, message: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events(run_id,op,status,message,ts) VALUES (?,?,?,?,?)",
            (run_id, op, status, message, _now()),
        )
        self.conn.commit()

    def events(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- quota ----
    def quota_used(self, platform: str, day: str) -> int:
        row = self.conn.execute(
            "SELECT units FROM quota WHERE platform=? AND day=?", (platform, day)
        ).fetchone()
        return int(row["units"]) if row else 0

    def add_quota(self, platform: str, day: str, units: int) -> int:
        self.conn.execute(
            "INSERT INTO quota(platform,day,units) VALUES (?,?,?) "
            "ON CONFLICT(platform,day) DO UPDATE SET units = units + excluded.units",
            (platform, day, units),
        )
        self.conn.commit()
        return self.quota_used(platform, day)

    def close(self) -> None:
        self.conn.close()
