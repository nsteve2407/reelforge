"""fal.ai media generator (credential-gated aggregator).

One surface for many models — pass model ids via `creds` and swap without code
changes (the aggregator-first strategy from the plan). Requires `fal-client`
and FAL_KEY (or creds['api_key']). Not exercised by the test suite.

creds keys: api_key, video_model, tts_model, music_model.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

from ..core.generate import GenResult


def _find_url(node) -> str | None:
    """Recursively find the first media URL in a fal result (handles audio_file,
    video, image(s), files, url, nested dicts/lists)."""
    if isinstance(node, str):
        return node if node.startswith("http") else None
    if isinstance(node, dict):
        if isinstance(node.get("url"), str):
            return node["url"]
        for v in node.values():
            u = _find_url(v)
            if u:
                return u
    if isinstance(node, list):
        for v in node:
            u = _find_url(v)
            if u:
                return u
    return None


class FalGenerator:
    provider = "fal"

    def __init__(self, creds: dict):
        self.creds = creds
        if creds.get("api_key"):
            os.environ.setdefault("FAL_KEY", creds["api_key"])

    def _run(self, model: str, args: dict, out: str) -> None:
        import fal_client  # lazy

        result = fal_client.subscribe(model, arguments=args)
        url = _find_url(result)
        if not url:
            raise RuntimeError(f"fal model {model} returned no media url: {result}")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, out)

    def video(self, out, prompt, *, w, h, seconds, index=0) -> GenResult:
        model = self.creds.get("video_model", "fal-ai/veo3/fast")
        ar = "9:16" if h > w else ("1:1" if h == w else "16:9")
        self._run(model, {"prompt": prompt, "aspect_ratio": ar,
                          "duration": int(round(seconds))}, str(out))
        return GenResult(str(out), seconds, "video", self.provider, dry_run=False,
                         message=f"fal {model}")

    def voice(self, out, text, *, seconds) -> GenResult:
        model = self.creds.get("tts_model", "fal-ai/kokoro")
        self._run(model, {"text": text}, str(out))
        return GenResult(str(out), seconds, "voice", self.provider, dry_run=False,
                         message=f"fal {model}")

    def music(self, out, *, mood, seconds) -> GenResult:
        model = self.creds.get("music_model", "fal-ai/stable-audio")
        prompt = (f"{mood}. Instrumental, no vocals, catchy and dynamic, "
                  f"clean stereo mix, studio quality, seamless.")
        # Stable Audio caps a single generation at 47s; the mixer loops/trims it
        # to the clip length, so request at most the model max.
        secs = max(1, min(47, int(round(seconds))))
        self._run(model, {"prompt": prompt, "seconds_total": secs}, str(out))
        return GenResult(str(out), seconds, "music", self.provider, dry_run=False,
                         message=f"fal {model}")
