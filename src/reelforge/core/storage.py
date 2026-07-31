"""Storage abstraction — local-first, cloud-ready.

The MVP ships a local filesystem backend. The interface deliberately mirrors
the subset of fsspec we need (path/exists/read/write/open) so a future S3/GCS
backend (via fsspec) can drop in without touching op code. Ops NEVER build
paths by hand — they go through a Storage rooted at the run's workdir.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import IO


class Storage:
    """A rooted view of a filesystem. All paths are relative to `root`."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        return p

    def ensure_dir(self, *parts: str) -> Path:
        p = self.path(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()

    def write_bytes(self, data: bytes, *parts: str) -> Path:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def write_text(self, text: str, *parts: str) -> Path:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def read_bytes(self, *parts: str) -> bytes:
        return self.path(*parts).read_bytes()

    def read_text(self, *parts: str) -> str:
        return self.path(*parts).read_text(encoding="utf-8")

    def open(self, mode: str, *parts: str) -> IO:
        p = self.path(*parts)
        if "w" in mode or "a" in mode:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p.open(mode)

    def copy_in(self, src: str | Path, *parts: str) -> Path:
        """Copy an external file into storage, returning the stored path."""
        dst = self.path(*parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    def url(self, *parts: str) -> str:
        return self.path(*parts).as_uri()

    def sub(self, *parts: str) -> "Storage":
        """A child Storage rooted at a subdirectory (e.g. per-run workdir)."""
        return Storage(self.path(*parts))
