"""Workspace config — your project-level settings (separate from secrets).

Two config layers, on purpose:
- `reelforge.yaml` (this): non-secret workspace prefs — which profile you're
  working on (`active_profile`), where profiles/work live, default toggles.
  Safe to commit.
- `.env` (secrets): API keys / tokens read by core.credentials. Gitignored.
  Auto-loaded at CLI startup via `load_dotenv`.

`active_profile` is a convenience record + `config show` hint; it does NOT make
the CLI silently assume a profile — `run` still takes `--profile` explicitly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

DEFAULT_PATH = "reelforge.yaml"


class WorkspaceConfig(BaseModel):
    model_config = {"extra": "ignore"}

    active_profile: Optional[str] = None
    profiles_dir: str = "profiles"
    work_dir: str = ".rf_work"
    auto_approve: bool = False
    enforce_budget: bool = False


def load_workspace(path: str | Path = DEFAULT_PATH) -> WorkspaceConfig:
    p = Path(path)
    if not p.exists():
        return WorkspaceConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return WorkspaceConfig.model_validate(data)


def save_workspace(cfg: WorkspaceConfig, path: str | Path = DEFAULT_PATH) -> Path:
    p = Path(path)
    p.write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False), encoding="utf-8")
    return p


def load_dotenv(path: str | Path = ".env") -> bool:
    """Load a .env into os.environ (without overriding existing vars). Returns True if loaded."""
    p = Path(path)
    if not p.exists():
        return False
    try:
        from dotenv import load_dotenv as _ld  # python-dotenv (dep of pydantic-settings)
        return bool(_ld(dotenv_path=str(p), override=False))
    except Exception:  # noqa: BLE001 - minimal fallback parser
        import os
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return True
