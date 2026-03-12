"""Track per-task execution outcomes in stats.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATS_FILE = Path(__file__).parent.parent / "stats.json"
MAX_ENTRIES = 500


def record(task: dict, outcome: str, started_at: datetime, finished_at: datetime) -> None:
    """Record a task outcome. outcome: 'success' | 'error' | 'limit'"""
    entries = _load()
    duration = (finished_at - started_at).total_seconds()
    entries.append({
        "title": task["title"],
        "project": task["project"],
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(duration),
        "outcome": outcome,
    })
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    STATS_FILE.write_text(json.dumps(entries, indent=2))


def _load() -> list[dict]:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text())
    return []


def summary(hours: int = 24) -> dict:
    """Return summary stats for the last `hours` hours."""
    entries = _load()
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    recent = [
        e for e in entries
        if datetime.fromisoformat(e["started_at"]).timestamp() > cutoff
    ]
    total = len(recent)
    success = sum(1 for e in recent if e["outcome"] == "success")
    error = sum(1 for e in recent if e["outcome"] == "error")
    limit = sum(1 for e in recent if e["outcome"] == "limit")
    durations = [e["duration_seconds"] for e in recent if e["outcome"] == "success"]
    avg_duration = round(sum(durations) / len(durations)) if durations else None
    last = max((e["finished_at"] for e in recent), default=None)
    return {
        "total": total,
        "success": success,
        "error": error,
        "limit": limit,
        "avg_duration": avg_duration,
        "last_finished_at": last,
    }


def last_ran_at() -> Optional[datetime]:
    """Return datetime of the most recently finished task."""
    entries = _load()
    if not entries:
        return None
    last = max(entries, key=lambda e: e["finished_at"])
    return datetime.fromisoformat(last["finished_at"])
