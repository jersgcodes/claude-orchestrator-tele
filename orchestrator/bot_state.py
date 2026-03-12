"""Shared daemon state accessible from both mac_daemon.py and bot.py."""
from datetime import datetime, timezone

start_time: datetime = datetime.now(timezone.utc)
