"""
Claude Orchestrator — Mac daemon entry point.

Runs two concurrent loops:
  1. Telegram bot  — receives /queue /status /stop /resume /skip /clear /stats /health commands
  2. Execution loop — works through the task queue, detects and waits out limits
  3. Heartbeat loop — sends a daily status summary via Telegram

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
from typing import Optional

from telegram import MenuButtonCommands
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import orchestrator.queue as q
import orchestrator.stats as stats
import orchestrator.bot_state as bot_state
from orchestrator.bot import (
    cmd_clear, cmd_health, cmd_help, cmd_list, cmd_menu, cmd_queue,
    cmd_resume, cmd_skip, cmd_stats, cmd_status, cmd_stop,
    on_button,
)
from orchestrator.config import load as load_config, active_projects
from orchestrator.limits import probe, detect_limit_type, parse_reset_time, is_limit_error, time_until
from orchestrator.runner import run_task, commit_and_push
from orchestrator.queue import requeue_at_front

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
HEARTBEAT_INTERVAL    = 24 * 3600 # daily heartbeat
IDLE_ALERT_MINS       = 10        # alert if queue non-empty but nothing ran for this long
CLAUDE_PATH           = os.getenv("CLAUDE_PATH", "/opt/homebrew/bin/claude")

_last_idle_alert: Optional[datetime] = None


def _time_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return "never"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return f"{round(secs)}s"
    elif secs < 3600:
        return f"{round(secs / 60)}m"
    elif secs < 86400:
        return f"{round(secs / 3600)}h"
    return f"{round(secs / 86400)}d"


async def notify(app: Application, text: str) -> None:
    cfg = load_config()
    chat_id = cfg["telegram"]["admin_chat_id"]
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error("Telegram notify failed: %s", e)


async def _startup_notify(app: Application) -> None:
    tasks = q.all_tasks()
    lim = q.get_limit()
    paused = q.is_paused()

    lim_state = "🟢 Limits OK"
    if q.is_limit_hit():
        reset = datetime.fromisoformat(lim["reset_at"])
        remaining = time_until(reset)
        ltype = lim.get("type", "").upper()
        lim_state = f"⏸ Limit hit ({ltype}) — resets in {remaining}"

    status = "⏸ Paused" if paused else "▶️ Running"
    await notify(
        app,
        f"🔄 *Orchestrator started*\n"
        f"Queue: {len(tasks)} task(s) | {status} | {lim_state}",
    )


async def _request_task_approval(app: Application, task: dict) -> None:
    """Send a Telegram approval request using commands declared in the task definition."""
    commands = task["requires_approval"]
    q.set_task_pending_approval(task["project"], task["id"], commands)

    cfg = load_config()
    chat_id = cfg["telegram"]["admin_chat_id"]
    label = f"[{task['project']}] {task['title']}"
    pid = task["project"]
    tid = task["id"]

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cmd_list = "\n".join(f"  • `{c}`" for c in commands)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve all", callback_data=f"orch:approve_all:{pid}:{tid}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"orch:deny:{pid}:{tid}"),
        ],
    ])
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ *Permission request*\n_{label}_\n\n"
                f"Commands requiring approval:\n{cmd_list}"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Failed to send approval request: %s", e)


async def _heartbeat_loop(app: Application) -> None:
    """Send a daily status summary."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            s = stats.summary(hours=24)
            last = stats.last_ran_at()
            queue_count = len(q.all_tasks())
            await notify(
                app,
                f"🟢 *Orchestrator alive*\n\n"
                f"Tasks (24h): ✅ {s['success']}  ❌ {s['error']}  ⏸ {s['limit']}\n"
                f"Queue: {queue_count} pending\n"
                f"Last task: {_time_ago(last)} ago",
            )
        except Exception as e:
            logger.error("Heartbeat failed: %s", e)


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
    global _last_idle_alert

    if q.is_paused():
        return

    # ── Limit recovery ────────────────────────────────────────────────────────
    if q.is_limit_hit():
        lim = q.get_limit()
        hit_at = datetime.fromisoformat(lim["hit_at"])
        elapsed_h = (datetime.now(timezone.utc) - hit_at).total_seconds() / 3600

        if elapsed_h < LIMIT_PROBE_START_H:
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

        limit_type = lim.get("type", "unknown")
        q.clear_limit()
        logger.info("Limits reset (%s). Resuming queue.", limit_type)
        await notify(app, f"🟢 *Limits reset* ({limit_type.upper()})\nResuming queue...")
        return  # next tick will pick up the task

    # ── Idle detection ────────────────────────────────────────────────────────
    if not q.is_empty():
        last = stats.last_ran_at()
        if last:
            idle_mins = (datetime.now(timezone.utc) - last).total_seconds() / 60
            already_alerted = (
                _last_idle_alert is not None
                and (datetime.now(timezone.utc) - _last_idle_alert).total_seconds() < 3600
            )
            if idle_mins > IDLE_ALERT_MINS and not already_alerted:
                _last_idle_alert = datetime.now(timezone.utc)
                queue_count = len(q.all_tasks())
                await notify(
                    app,
                    f"⚠️ *Idle alert* — queue has {queue_count} task(s) but nothing ran for "
                    f"{round(idle_mins)}m",
                )

    # ── Task execution ────────────────────────────────────────────────────────
    if q.is_empty():
        return

    task = q.peek_next()
    if task is None:
        return  # all queued tasks are pending approval

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

    # ── Per-task approval gate ─────────────────────────────────────────────────
    # Tasks declare required commands via "Requires approval:" in tasks.md.
    # If declared and not yet approved, gate execution until user responds.
    if (
        task.get("requires_approval")
        and not task.get("approved_commands")
        and task.get("approval_status") != "pending"
    ):
        logger.info("Requesting approval for task: %s / %s", task["project"], task["title"])
        await _request_task_approval(app, task)
        return

    logger.info("Running task: %s / %s", task["project"], task["title"])
    await notify(app, f"⚙️ *Starting task*\n[{task['project']}] {task['title']}")

    started_at = datetime.now(timezone.utc)
    success, output, was_limit = await asyncio.get_event_loop().run_in_executor(
        None, run_task, task, proj_cfg, CLAUDE_PATH
    )
    finished_at = datetime.now(timezone.utc)

    if was_limit:
        limit_type = detect_limit_type(output)
        reset_at = parse_reset_time(output)
        q.set_limit_hit(limit_type, reset_at)
        remaining = time_until(reset_at)
        stats.record(task, "limit", started_at, finished_at)
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
        stats.record(task, "success", started_at, finished_at)
        summary = output[:400] if output else "No output."
        await notify(
            app,
            f"✅ *Done* — [{task['project']}] {task['title']}\n\n"
            f"{summary}\n\n"
            f"{'_Changes committed and pushed._' if committed else '_Commit failed — check logs._'}",
        )
        logger.info("Task complete: %s", task["title"])
    else:
        max_retries = proj_cfg.get("max_retries", 0)
        retries_used = task.get("retries_used", 0)

        if retries_used < max_retries:
            task_to_retry = q.pop_next()
            task_to_retry["retries_used"] = retries_used + 1
            requeue_at_front(task_to_retry)
            stats.record(task, "error", started_at, finished_at)
            await notify(
                app,
                f"⚠️ *Task failed — retrying* ({retries_used + 1}/{max_retries})\n"
                f"[{task['project']}] {task['title']}\n\n```\n{output[:300]}\n```",
            )
            logger.warning("Task failed, retry %d/%d: %s", retries_used + 1, max_retries, task["title"])
        else:
            q.pop_next()
            stats.record(task, "error", started_at, finished_at)
            retry_note = f" (failed after {max_retries} retr{'y' if max_retries == 1 else 'ies'})" if max_retries > 0 else ""
            await notify(
                app,
                f"❌ *Error{retry_note}* — [{task['project']}] {task['title']}\n\n```\n{output[:400]}\n```",
            )
            logger.error("Task failed: %s\n%s", task["title"], output[:400])


async def _set_commands(app: Application) -> None:
    await app.bot.set_my_commands([
        ("menu",   "open the main menu"),
        ("list",   "list <project> — show next 10 PENDING tasks"),
        ("queue",  "queue <project> next [n] — add tasks to queue"),
        ("status", "queue contents + limit state"),
        ("stats",  "execution stats for the last 24h"),
        ("health", "daemon health: uptime, last task, error rate"),
        ("stop",   "pause execution (queue preserved)"),
        ("resume", "resume execution"),
        ("skip",   "move next queued task to end"),
        ("clear",  "wipe entire queue"),
        ("help",   "show all commands"),
    ])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def build_app(bot_token: str) -> Application:
    app = Application.builder().token(bot_token).post_init(_set_commands).build()
    app.add_handler(CommandHandler("menu",   cmd_menu))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("queue",  cmd_queue))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("skip",   cmd_skip))
    app.add_handler(CommandHandler("clear",  cmd_clear))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("start",  cmd_menu))
    app.add_handler(CallbackQueryHandler(on_button, pattern="^orch:"))
    return app


async def main() -> None:
    cfg = load_config()
    bot_token = cfg["telegram"]["bot_token"]
    if not bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN not set. Check projects.yaml or env vars.")

    app = build_app(bot_token)

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await _startup_notify(app)

        exec_task = asyncio.create_task(execution_loop(app))
        heartbeat_task = asyncio.create_task(_heartbeat_loop(app))
        logger.info("Claude Orchestrator running. Send /help to your Telegram bot.")

        try:
            await asyncio.Event().wait()  # run forever
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            exec_task.cancel()
            heartbeat_task.cancel()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
