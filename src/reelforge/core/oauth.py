"""YouTube OAuth token helper — mint/validate/load the token JSON used to publish.

The real minting runs the Google installed-app OAuth flow (opens a browser),
so it's credential + interaction gated and not exercised by the test suite. The
validation and token-file read/write are pure and tested.

Token JSON shape (what adapters/youtube.py consumes via REELFORGE_YT_TOKEN_FILE):
    {token, refresh_token, client_id, client_secret, token_uri, scopes}
"""
from __future__ import annotations

import json
from pathlib import Path

YT_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def validate_client_secrets(path: str | Path) -> tuple[bool, str]:
    """Structurally validate a Google OAuth client_secrets.json (no network)."""
    p = Path(path)
    if not p.exists():
        return False, f"file not found: {p}"
    try:
        data = json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        return False, f"invalid JSON: {e}"
    root = data.get("installed") or data.get("web")
    if not isinstance(root, dict):
        return False, "expected an 'installed' or 'web' client (Desktop app recommended)"
    missing = [k for k in ("client_id", "client_secret", "auth_uri", "token_uri")
               if not root.get(k)]
    if missing:
        return False, f"missing keys: {', '.join(missing)}"
    return True, "ok"


def load_token(path: str | Path) -> dict:
    """Load a saved token JSON."""
    return json.loads(Path(path).read_text())


def token_to_creds(token: dict) -> dict:
    """Normalize a saved token dict into the creds shape adapters expect."""
    return {k: token.get(k) for k in
            ("token", "refresh_token", "client_id", "client_secret", "token_uri")}


def mint_youtube_token(client_secrets: str | Path, out: str | Path,
                       scopes: list[str] | None = None, *, port: int = 0) -> Path:
    """Run the installed-app OAuth flow and save the token JSON. Interactive."""
    ok, why = validate_client_secrets(client_secrets)
    if not ok:
        raise ValueError(f"bad client secrets: {why}")
    from google_auth_oauthlib.flow import InstalledAppFlow  # lazy, gated

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), scopes or [YT_UPLOAD_SCOPE])
    creds = flow.run_local_server(port=port)
    token = {
        "token": creds.token, "refresh_token": creds.refresh_token,
        "client_id": creds.client_id, "client_secret": creds.client_secret,
        "token_uri": creds.token_uri, "scopes": list(creds.scopes or []),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(token, indent=2))
    return out
