"""
Detect Claude Code usage limits and parse when they reset.

Claude Code has two limit types:
  - 5-hour:  short rolling window, resets after ~5 hours
  - weekly:  longer cap, resets Monday 00:00 UTC

Detection: run a cheap probe call and inspect the output.
Parsing:   extract the reset time from the error message if present,
           otherwise fall back to conservative defaults.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

LIMIT_PHRASES = [
    "usage limit",
    "rate limit",
    "quota exceeded",
    "try again later",
    "limit reached",
    "limit exceeded",
    "you've reached",
]

WEEKLY_PHRASES = ["week", "weekly", "7 day", "seven day"]

CLAUDE_PATH = "/opt/homebrew/bin/claude"
PROBE_PROMPT = "reply with exactly: ok"


def probe(claude_path: str = CLAUDE_PATH) -> tuple[bool, str]:
    """
    Run a minimal claude call.
    Returns (limits_available, raw_output).
    """
    try:
        result = subprocess.run(
            [claude_path, "--print", "--dangerously-skip-permissions", PROBE_PROMPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        if is_limit_error(output):
            return False, output
        return True, output
    except FileNotFoundError:
        logger.error("claude not found at %s", claude_path)
        return False, "claude not found"
    except subprocess.TimeoutExpired:
        return False, "probe timed out"


def is_limit_error(output: str) -> bool:
    lower = output.lower()
    return any(p in lower for p in LIMIT_PHRASES)


def detect_limit_type(output: str) -> str:
    """Return 'weekly' or '5hour' based on error message content."""
    lower = output.lower()
    if any(p in lower for p in WEEKLY_PHRASES):
        return "weekly"
    return "5hour"


def parse_reset_time(output: str) -> datetime:
    """
    Try to extract the reset time from claude's error message.
    Falls back to conservative defaults if parsing fails.
    """
    now = datetime.now(timezone.utc)
    lower = output.lower()
    limit_type = detect_limit_type(output)

    # Try "resets in X hours / X minutes"
    match = re.search(r"resets?\s+in\s+(\d+)\s*hour", lower)
    if match:
        return now + timedelta(hours=int(match.group(1)), minutes=15)

    match = re.search(r"resets?\s+in\s+(\d+)\s*min", lower)
    if match:
        return now + timedelta(minutes=int(match.group(1)) + 5)

    # Try "resets at HH:MM" (assume UTC)
    match = re.search(r"resets?\s+at\s+(\d{1,2}):(\d{2})", lower)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    # Try "resets in X days"
    match = re.search(r"resets?\s+in\s+(\d+)\s*day", lower)
    if match:
        return now + timedelta(days=int(match.group(1)))

    # Defaults
    if limit_type == "weekly":
        # Next Monday 00:00 UTC
        days_until_monday = (7 - now.weekday()) % 7 or 7
        return (now + timedelta(days=days_until_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        # 5 hours + 15 min buffer
        return now + timedelta(hours=5, minutes=15)


def time_until(reset_at: datetime) -> str:
    """Human-readable time until reset."""
    now = datetime.now(timezone.utc)
    delta = reset_at - now
    if delta.total_seconds() <= 0:
        return "now"
    total_min = int(delta.total_seconds() / 60)
    if total_min < 60:
        return f"{total_min}m"
    h, m = divmod(total_min, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"
