"""Manage the task queue persisted in queue.json."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_FILE = Path(__file__).parent.parent / "queue.json"

_DEFAULTS = {
    "tasks": [],
    "paused": False,
    "limit": {"type": None, "hit_at": None, "reset_at": None},
}


def load() -> dict:
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return dict(_DEFAULTS)


def save(q: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(q, indent=2, default=str))


# ── Queue operations ──────────────────────────────────────────────────────────

def add_tasks(tasks: list[dict]) -> int:
    """Append tasks (deduped by id+project). Returns count added."""
    q = load()
    existing = {(t["project"], t["id"]) for t in q["tasks"]}
    added = 0
    for task in tasks:
        key = (task["project"], task["id"])
        if key not in existing:
            task["queued_at"] = datetime.now(timezone.utc).isoformat()
            q["tasks"].append(task)
            existing.add(key)
            added += 1
    save(q)
    return added


def peek_next() -> Optional[dict]:
    """Return first task that is not pending approval."""
    q = load()
    for task in q["tasks"]:
        if task.get("approval_status") != "pending":
            return task
    return None


def get_task(project: str, task_id: int) -> Optional[dict]:
    """Return a task by project + id, or None."""
    q = load()
    for task in q["tasks"]:
        if task["project"] == project and task["id"] == task_id:
            return task
    return None


def set_task_pending_approval(project: str, task_id: int, predicted_commands: list) -> None:
    """Mark a task as awaiting approval and store predicted commands."""
    q = load()
    for task in q["tasks"]:
        if task["project"] == project and task["id"] == task_id:
            task["approval_status"] = "pending"
            task["predicted_commands"] = predicted_commands
            break
    save(q)


def approve_task(project: str, task_id: int, approved_commands: list) -> None:
    """Mark a task as approved with the given command list."""
    q = load()
    for task in q["tasks"]:
        if task["project"] == project and task["id"] == task_id:
            task["approval_status"] = "approved"
            task["approved_commands"] = approved_commands
            task.pop("predicted_commands", None)
            break
    save(q)


def deny_task(project: str, task_id: int) -> bool:
    """Remove a task from the queue. Returns True if found."""
    q = load()
    before = len(q["tasks"])
    q["tasks"] = [t for t in q["tasks"] if not (t["project"] == project and t["id"] == task_id)]
    save(q)
    return len(q["tasks"]) < before


def pop_next() -> Optional[dict]:
    q = load()
    if not q["tasks"]:
        return None
    task = q["tasks"].pop(0)
    save(q)
    return task


def skip_next() -> Optional[dict]:
    """Move first task to end of queue."""
    q = load()
    if not q["tasks"]:
        return None
    task = q["tasks"].pop(0)
    q["tasks"].append(task)
    save(q)
    return task


def clear() -> None:
    q = load()
    q["tasks"] = []
    save(q)


def is_empty() -> bool:
    return len(load()["tasks"]) == 0


def is_paused() -> bool:
    return load()["paused"]


def set_paused(paused: bool) -> None:
    q = load()
    q["paused"] = paused
    save(q)


def all_tasks() -> list[dict]:
    return load()["tasks"]


# ── Limit tracking ────────────────────────────────────────────────────────────

def set_limit_hit(limit_type: str, reset_at: datetime) -> None:
    q = load()
    q["limit"] = {
        "type": limit_type,
        "hit_at": datetime.now(timezone.utc).isoformat(),
        "reset_at": reset_at.isoformat(),
    }
    save(q)
    logger.info("Limit hit (%s). Reset at %s", limit_type, reset_at)


def clear_limit() -> None:
    q = load()
    q["limit"] = {"type": None, "hit_at": None, "reset_at": None}
    save(q)


def get_limit() -> dict:
    return load()["limit"]


def is_limit_hit() -> bool:
    lim = get_limit()
    if not lim.get("reset_at"):
        return False
    reset = datetime.fromisoformat(lim["reset_at"])
    return datetime.now(timezone.utc) < reset


def get_reset_at() -> Optional[datetime]:
    lim = get_limit()
    if lim.get("reset_at"):
        return datetime.fromisoformat(lim["reset_at"])
    return None
