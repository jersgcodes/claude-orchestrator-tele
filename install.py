"""
Install Claude Orchestrator as a macOS launchd service.
Starts automatically on login and restarts on crash.

Usage:
  python install.py          — install and start
  python install.py remove   — stop and uninstall
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.claude.orchestrator"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"

DAEMON_SCRIPT = Path(__file__).parent.resolve() / "mac_daemon.py"
PYTHON = sys.executable
LOG_DIR = Path(__file__).parent.resolve()


def install() -> None:
    PLIST_DIR.mkdir(parents=True, exist_ok=True)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before installing.")
        print("  export TELEGRAM_BOT_TOKEN=xxx")
        print("  export TELEGRAM_CHAT_ID=yyy")
        print("  python install.py")
        sys.exit(1)

    repo_dir = str(Path(__file__).parent.resolve())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{DAEMON_SCRIPT}</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>{bot_token}</string>
        <key>TELEGRAM_CHAT_ID</key>
        <string>{chat_id}</string>
        <key>PYTHONPATH</key>
        <string>{repo_dir}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{LOG_DIR}/orchestrator.log</string>

    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/orchestrator-error.log</string>
</dict>
</plist>
"""
    PLIST_PATH.write_text(plist)
    print(f"Wrote {PLIST_PATH}")

    # Unload first if already installed
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"Service '{LABEL}' installed and started.")
    print(f"Logs: {LOG_DIR}/orchestrator.log")
    print(f"      {LOG_DIR}/orchestrator-error.log")


def remove() -> None:
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print(f"Service '{LABEL}' stopped and removed.")
    else:
        print("Service not installed.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        remove()
    else:
        install()
