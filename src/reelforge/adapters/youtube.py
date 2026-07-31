"""YouTube Data API v3 publisher (credential-gated).

Requires OAuth credentials with the youtube.upload scope and a verified
Google Cloud project for public uploads. Uploads via a resumable
videos.insert; YouTube auto-classifies vertical <=60s + #Shorts as a Short.
Not exercised by the test suite (which uses the dry-run publisher).

creds dict keys: token, refresh_token, client_id, client_secret, token_uri
(or pass token_file path). Install extras: google-api-python-client,
google-auth, google-auth-oauthlib.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.publish import PublishMeta, PublishResult

_PRIVACY = {"public", "private", "unlisted"}


class YouTubePublisher:
    platform = "youtube_shorts"

    def __init__(self, creds: dict, cost: int = 1600):
        self.creds = creds
        self.cost = cost

    def _credentials(self):
        from google.oauth2.credentials import Credentials  # lazy

        c = self.creds
        if "token_file" in c:
            data = json.loads(Path(c["token_file"]).read_text())
        else:
            data = c
        return Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )

    def publish(self, video_path: str, meta: PublishMeta) -> PublishResult:
        from googleapiclient.discovery import build  # lazy
        from googleapiclient.http import MediaFileUpload

        privacy = meta.privacy if meta.privacy in _PRIVACY else "public"
        status = {
            "privacyStatus": "private" if meta.publish_at else privacy,
            "selfDeclaredMadeForKids": bool(meta.made_for_kids),
        }
        if meta.publish_at:
            status["publishAt"] = meta.publish_at  # RFC3339; video stays private until then
        body = {
            "snippet": {
                "title": meta.title,
                "description": meta.description,
                "tags": meta.tags,
                "categoryId": "17",  # Sports; caller may override via profile later
            },
            "status": status,
        }
        youtube = build("youtube", "v3", credentials=self._credentials(),
                        cache_discovery=False)
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True,
                                mimetype="video/*")
        request = youtube.videos().insert(part="snippet,status", body=body,
                                          media_body=media)
        response = None
        while response is None:
            _status, response = request.next_chunk()
        vid = response["id"]
        return PublishResult(
            ok=True, platform=self.platform, video_id=vid,
            url=f"https://youtube.com/shorts/{vid}", dry_run=False,
            scheduled_at=meta.publish_at,
            message=f"uploaded to YouTube ({status['privacyStatus']})",
        )
