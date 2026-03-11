"""
Claude Orchestrator — Mac daemon entry point.

Runs two concurrent loops:
  1. Telegram bot  — receives /queue /status /stop /resume /skip /clear commands
  2. Execution loop — works through the task queue, detects and waits out limits

Start:   python mac_daemon.py
Install: python install.py   (registers as macOS launchd service, auto-starts on boot)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from telegram.ext import Application, CommandHandler

import orchestrator.queue as q
from orchestrator.bot import (
    cmd_clear, cmd_help, cmd_list, cmd_queue,
    cmd_resume, cmd_skip, cmd_status, cmd_stop,
)
from orchestrator.config import load as load_config, active_projects
from orchestrator.limits import probe, detect_limit_type, parse_reset_time, is_limit_error, time_until
from orchestrator.runner import run_task, commit_and_push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "orchestrator.log"),
    ],
)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60        # check queue every 60s when no limit hit
LIMIT_POLL_SECONDS    = 15 * 60   # check every 15 min when limit is hit
LIMIT_PROBE_START_H   = 4.5       # start probing after 4.5 hours
CLAUDE_PATH           = os.getenv("CLAUDE_PATH", "/opt/homebrew/bin/claude")


async def notify(app: Application, text: str) -> None:
    cfg = load_config()
    chat_id = cfg["telegram"]["admin_chat_id"]
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error("Telegram notify failed: %s", e)


async def execution_loop(app: Application) -> None:
    """Main task execution loop — runs concurrently with the Telegram bot."""
    logger.info("Execution loop started.")

    while True:
        try:
            await _tick(app)
        except Exception as e:
            logger.exception("Unexpected error in execution loop: %s", e)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _tick(app: Application) -> None:
    if q.is_paused():
        return

    # ── Limit recovery ────────────────────────────────────────────────────────
    if q.is_limit_hit():
        lim = q.get_limit()
        hit_at = datetime.fromisoformat(lim["hit_at"])
        elapsed_h = (datetime.now(timezone.utc) - hit_at).total_seconds() / 3600

        if elapsed_h < LIMIT_PROBE_START_H:
            # Too early to probe — sleep longer
            logger.info(
                "Limit hit %s ago. Not probing until %.1fh mark.",
                time_until(datetime.now(timezone.utc) - (datetime.now(timezone.utc) - hit_at)),
                LIMIT_PROBE_START_H,
            )
            await asyncio.sleep(LIMIT_POLL_SECONDS - POLL_INTERVAL_SECONDS)
            return

        logger.info("Probing claude limits...")
        available, output = await asyncio.get_event_loop().run_in_executor(
            None, probe, CLAUDE_PATH
        )

        if not available:
            logger.info("Still limited. Waiting...")
            await asyncio.sleep(LIMIT_POLL_SECONDS - POLL_INTERVAL_SECONDS)
            return

        # Limits cleared!
        limit_type = lim.get("type", "unknown")
        q.clear_limit()
        logger.info("Limits reset (%s). Resuming queue.", limit_type)
        await notify(app, f"🟢 *Limits reset* ({limit_type.upper()})\nResuming queue...")
        return  # next tick will pick up the task

    # ── Task execution ────────────────────────────────────────────────────────
    if q.is_empty():
        return

    task = q.peek_next()
    cfg = load_config()
    projects = active_projects(cfg)
    proj_cfg = projects.get(task["project"])

    if not proj_cfg:
        logger.warning("Project '%s' not found or inactive. Skipping task.", task["project"])
        q.pop_next()
        return

    repo_path = os.path.expanduser(proj_cfg.get("repo_path", ""))
    if not repo_path or not os.path.isdir(repo_path):
        await notify(app, f"❌ Repo path not found for *{task['project']}*: `{repo_path}`")
        q.pop_next()
        return

    logger.info("Running task: %s / %s", task["project"], task["title"])
    await notify(app, f"⚙️ *Starting task*\n[{task['project']}] {task['title']}")

    success, output, was_limit = await asyncio.get_event_loop().run_in_executor(
        None, run_task, task, proj_cfg, CLAUDE_PATH
    )

    if was_limit:
        limit_type = detect_limit_type(output)
        reset_at = parse_reset_time(output)
        q.set_limit_hit(limit_type, reset_at)
        remaining = time_until(reset_at)
        await notify(
            app,
            f"⏸ *Limit hit* ({limit_type.upper()})\n"
            f"[{task['project']}] {task['title']}\n\n"
            f"Task will resume automatically.\n"
            f"Reset in approx. *{remaining}*",
        )
        logger.info("Limit hit (%s). Reset at %s.", limit_type, reset_at)
        return  # task stays in queue, will retry after reset

    if success:
        q.pop_next()
        committed = await asyncio.get_event_loop().run_in_executor(
            None, commit_and_push, task, proj_cfg
        )
        summary = output[:400] if output else "No output."
        await notify(
            app,
            f"✅ *Done* — [{task['project']}] {task['title']}\n\n"
            f"{summary}\n\n"
            f"{'_Changes committed and pushed._' if committed else '_Commit failed — check logs._'}",
        )
        logger.info("Task complete: %s", task["title"])
    else:
        q.pop_next()
        await notify(
            app,
            f"❌ *Error* — [{task['project']}] {task['title']}\n\n```\n{output[:400]}\n```",
        )
        logger.error("Task failed: %s\n%s", task["title"], output[:400])


def build_app(bot_token: str) -> Application:
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("queue",  cmd_queue))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("skip",   cmd_skip))
    app.add_handler(CommandHandler("clear",  cmd_clear))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("start",  cmd_help))
    return app


async def main() -> None:
    cfg = load_config()
    bot_token = cfg["telegram"]["bot_token"]
    if not bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN not set. Check projects.yaml or env vars.")

    app = build_app(bot_token)

    # Start execution loop as a background task alongside the Telegram bot
    async with app:
        await app.start()
        task = asyncio.create_task(execution_loop(app))
        logger.info("Claude Orchestrator running. Send /help to your Telegram bot.")
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            await asyncio.Event().wait()  # run forever
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            task.cancel()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
