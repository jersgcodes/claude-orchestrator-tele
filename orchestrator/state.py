"""Persist orchestrator state to state.json between runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).parent.parent / "state.json"

_PROJ_DEFAULTS = {
    "current_task": None,       # {id, title, description, started_at}
    "pending_approval": None,   # {task, next_3} waiting for user reply
    "scheduled_tasks": [],      # [{task, run_at}]
    "last_rate_limit_at": None, # ISO timestamp if API rate limited
    "status": "idle",           # idle | running | awaiting_approval | rate_limited
}


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"projects": {}, "telegram_offset": 0}


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def project(state: dict, name: str) -> dict:
    if name not in state["projects"]:
        state["projects"][name] = dict(_PROJ_DEFAULTS)
    return state["projects"][name]


def set_project(state: dict, name: str, data: dict) -> None:
    state["projects"][name] = data


def update_project(state: dict, name: str, **kwargs: Any) -> None:
    p = project(state, name)
    p.update(kwargs)
