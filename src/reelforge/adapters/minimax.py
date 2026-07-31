"""MiniMax media generator (credential-gated).

MiniMax exposes TTS, music, image and video (Hailuo) under one account and also
ships an official MCP server. Here we call the REST API directly. Requires
creds['api_key'] (+ creds['group_id'] for some endpoints). Not run in tests.

This is a concise, credential-gated adapter; endpoint shapes may need updating
against MiniMax's current API version before live use.
"""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path

from ..core.generate import GenResult

_BASE = "https://api.minimax.io/v1"


class MinimaxGenerator:
    provider = "minimax"

    def __init__(self, creds: dict):
        self.creds = creds
        self.key = creds["api_key"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _download(self, url: str, out: str) -> None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, out)

    def video(self, out, prompt, *, w, h, seconds, index=0) -> GenResult:
        import requests  # lazy

        model = self.creds.get("video_model", "MiniMax-Hailuo-02")
        r = requests.post(f"{_BASE}/video_generation", headers=self._headers(),
                          json={"model": model, "prompt": prompt}, timeout=60)
        r.raise_for_status()
        task_id = r.json()["task_id"]
        for _ in range(60):  # poll
            q = requests.get(f"{_BASE}/query/video_generation?task_id={task_id}",
                             headers=self._headers(), timeout=30).json()
            if q.get("status") == "Success":
                self._download(q["file"]["download_url"], str(out))
                return GenResult(str(out), seconds, "video", self.provider,
                                 dry_run=False, message=f"minimax {model}")
            if q.get("status") in ("Fail", "Error"):
                raise RuntimeError(f"minimax video failed: {q}")
            time.sleep(5)
        raise TimeoutError("minimax video generation timed out")

    def voice(self, out, text, *, seconds) -> GenResult:
        import requests  # lazy

        r = requests.post(f"{_BASE}/t2a_v2", headers=self._headers(), json={
            "model": self.creds.get("tts_model", "speech-2.5-hd"),
            "text": text, "voice_setting": {"voice_id": self.creds.get("voice", "Wise_Woman")},
        }, timeout=60)
        r.raise_for_status()
        self._download(r.json()["data"]["audio"], str(out))
        return GenResult(str(out), seconds, "voice", self.provider, dry_run=False,
                         message="minimax tts")

    def music(self, out, *, mood, seconds) -> GenResult:
        import requests  # lazy

        r = requests.post(f"{_BASE}/music_generation", headers=self._headers(), json={
            "model": "music-1.5", "prompt": f"{mood} instrumental",
        }, timeout=60)
        r.raise_for_status()
        self._download(r.json()["data"]["audio"], str(out))
        return GenResult(str(out), seconds, "music", self.provider, dry_run=False,
                         message="minimax music")
