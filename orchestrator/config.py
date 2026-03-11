"""Load and merge projects.yaml with projects.local.yaml and env vars."""
from __future__ import annotations

import os
import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent


def load() -> dict:
    base = yaml.safe_load((ROOT / "projects.yaml").read_text())

    local_path = ROOT / "projects.local.yaml"
    if local_path.exists():
        local = yaml.safe_load(local_path.read_text()) or {}
        _deep_merge(base, local)

    # env vars override everything
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        base["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.getenv("TELEGRAM_CHAT_ID"):
        base["telegram"]["admin_chat_id"] = int(os.environ["TELEGRAM_CHAT_ID"])

    return base


def active_projects(cfg: dict) -> dict[str, dict]:
    return {k: v for k, v in cfg.get("projects", {}).items() if v.get("active")}


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
