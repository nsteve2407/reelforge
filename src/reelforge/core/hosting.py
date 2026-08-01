"""Public-URL hosting — Instagram's Graph API fetches media from a public URL.

`LocalFileHost` serves a directory over HTTP (great for testing / same-LAN use).
`S3Host` / `GCSHost` upload to a bucket and return a public URL (credential-gated,
lazy-imported, not run in tests). `ensure_public_url` is what the IG publish path
calls: returns an already-provided url, or hosts the file, or None.
"""
from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional


class LocalFileHost:
    """Serve `root` over HTTP on 127.0.0.1:<ephemeral>. Use as a context manager."""

    def __init__(self, root: str | Path, host: str = "127.0.0.1"):
        self.root = str(Path(root).resolve())
        self.host = host
        self._srv: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "LocalFileHost":
        handler = functools.partial(SimpleHTTPRequestHandler, directory=self.root)
        self._srv = ThreadingHTTPServer((self.host, 0), handler)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def port(self) -> int:
        return self._srv.server_address[1] if self._srv else 0

    def url_for(self, rel_path: str | Path) -> str:
        rel = Path(rel_path)
        if rel.is_absolute():
            rel = rel.relative_to(self.root)
        return f"http://{self.host}:{self.port}/{rel.as_posix()}"

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> "LocalFileHost":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


class S3Host:
    provider = "s3"

    def __init__(self, creds: dict):
        self.bucket = creds["s3_bucket"]
        self.prefix = creds.get("s3_prefix", "reelforge")
        self.region = creds.get("s3_region")

    def upload(self, path: str | Path) -> str:
        import boto3  # lazy
        key = f"{self.prefix}/{Path(path).name}"
        s3 = boto3.client("s3", region_name=self.region)
        s3.upload_file(str(path), self.bucket, key,
                       ExtraArgs={"ContentType": "video/mp4"})
        base = f"https://{self.bucket}.s3.amazonaws.com"
        return f"{base}/{key}"


class GCSHost:
    provider = "gcs"

    def __init__(self, creds: dict):
        self.bucket = creds["gcs_bucket"]
        self.prefix = creds.get("gcs_prefix", "reelforge")

    def upload(self, path: str | Path) -> str:
        from google.cloud import storage  # lazy
        client = storage.Client()
        blob = client.bucket(self.bucket).blob(f"{self.prefix}/{Path(path).name}")
        blob.upload_from_filename(str(path), content_type="video/mp4")
        return blob.public_url


def get_host(creds: Optional[dict]):
    if not creds:
        return None
    if creds.get("s3_bucket"):
        return S3Host(creds)
    if creds.get("gcs_bucket"):
        return GCSHost(creds)
    return None


def ensure_public_url(path: str | Path, creds: Optional[dict]) -> Optional[str]:
    """Return a public URL for `path`: given media_url, else upload via a host, else None."""
    if creds and creds.get("media_url"):
        return creds["media_url"]
    host = get_host(creds)
    return host.upload(path) if host else None
