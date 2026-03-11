"""
Telegram bot handlers — queue control via commands.

Commands:
  /list [project]           — show next 10 PENDING tasks with index numbers
  /queue <project> 1 2 3    — add tasks by index to queue
  /queue <project> next [n] — add next n pending tasks (default 1)
  /status                   — queue contents + limit state
  /stop                     — pause execution
  /resume                   — resume execution
  /skip                     — skip the next queued task (move to end)
  /clear                    — clear entire queue
  /help                     — show commands
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

import orchestrator.queue as q
from orchestrator.limits import time_until
from orchestrator.task_reader import get_next_tasks
from orchestrator.config import load as load_config

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_repo_path(project_name: str) -> str:
    cfg = load_config()
    proj = cfg.get("projects", {}).get(project_name, {})
    import os
    return os.path.expanduser(proj.get("repo_path", ""))


def _get_tasks_file(project_name: str) -> str:
    cfg = load_config()
    proj = cfg.get("projects", {}).get(project_name, {})
    return proj.get("tasks_file", "docs/tasks.md")


def _default_project() -> str:
    cfg = load_config()
    active = {k: v for k, v in cfg.get("projects", {}).items() if v.get("active")}
    return next(iter(active), "")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show next 10 PENDING tasks for a project."""
    project = ctx.args[0] if ctx.args else _default_project()
    if not project:
        await update.message.reply_text("No active projects configured.")
        return

    repo_path = _get_repo_path(project)
    tasks_file = _get_tasks_file(project)
    tasks = get_next_tasks(repo_path, tasks_file, n=10)

    if not tasks:
        await update.message.reply_text(f"No PENDING tasks in *{project}*.", parse_mode="Markdown")
        return

    lines = [f"📋 *{project}* — PENDING tasks:\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(f"  `{i}` {t['title']}")
    lines.append(f"\nUse `/queue {project} 1 3 5` to queue by number.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /queue <project> 1 2 3        — queue tasks by index
    /queue <project> next [n]     — queue next n tasks
    """
    if not ctx.args:
        await update.message.reply_text(
            "Usage:\n`/queue <project> 1 2 3`\n`/queue <project> next [n]`",
            parse_mode="Markdown",
        )
        return

    project = ctx.args[0]
    rest = ctx.args[1:]

    repo_path = _get_repo_path(project)
    tasks_file = _get_tasks_file(project)

    if not rest:
        await update.message.reply_text(
            f"Usage: `/queue {project} 1 2 3` or `/queue {project} next 3`",
            parse_mode="Markdown",
        )
        return

    all_pending = get_next_tasks(repo_path, tasks_file, n=50)

    to_add: list[dict] = []

    if rest[0].lower() == "next":
        n = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else 1
        to_add = all_pending[:n]
    else:
        indices = [int(x) for x in rest if x.isdigit()]
        for idx in indices:
            if 1 <= idx <= len(all_pending):
                to_add.append(all_pending[idx - 1])

    if not to_add:
        await update.message.reply_text("No valid tasks found. Use `/list` to see indices.")
        return

    for t in to_add:
        t["project"] = project

    added = q.add_tasks(to_add)
    total = len(q.all_tasks())
    names = "\n".join(f"  • {t['title']}" for t in to_add[:5])
    await update.message.reply_text(
        f"✅ Added {added} task(s) to queue ({total} total):\n{names}",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show queue contents and limit state."""
    tasks = q.all_tasks()
    lim = q.get_limit()
    paused = q.is_paused()

    lines = ["📊 *Claude Orchestrator Status*\n"]

    # Limit state
    if lim.get("reset_at"):
        from datetime import datetime, timezone
        reset = datetime.fromisoformat(lim["reset_at"])
        remaining = time_until(reset)
        emoji = "🔴" if q.is_limit_hit() else "🟢"
        ltype = lim.get("type", "unknown").upper()
        if q.is_limit_hit():
            lines.append(f"{emoji} *LIMIT HIT* ({ltype})")
            lines.append(f"Resets: {reset.strftime('%a %Y-%m-%d %H:%M UTC')} (in {remaining})")
        else:
            lines.append(f"{emoji} Limits available (last hit: {ltype})")
    else:
        lines.append("🟢 No limits hit")

    lines.append(f"{'⏸ Paused' if paused else '▶️ Running'}\n")

    # Queue
    if not tasks:
        lines.append("📋 Queue: empty")
    else:
        lines.append(f"📋 Queue ({len(tasks)} task{'s' if len(tasks) != 1 else ''}):")
        for i, t in enumerate(tasks[:10], 1):
            lines.append(f"  {i}. [{t['project']}] {t['title']}")
        if len(tasks) > 10:
            lines.append(f"  ... and {len(tasks) - 10} more")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q.set_paused(True)
    await update.message.reply_text("⏸ Execution paused. Queue preserved. Use /resume to continue.")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q.set_paused(False)
    await update.message.reply_text("▶️ Execution resumed.")


async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    task = q.skip_next()
    if task:
        await update.message.reply_text(
            f"⏭ Skipped: _{task['title']}_\nMoved to end of queue.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Queue is empty.")


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    count = len(q.all_tasks())
    q.clear()
    await update.message.reply_text(f"🗑 Cleared {count} task(s) from queue.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Claude Orchestrator Commands*\n\n"
        "`/list [project]` — show PENDING tasks\n"
        "`/queue <project> 1 2 3` — queue by index\n"
        "`/queue <project> next [n]` — queue next n tasks\n"
        "`/status` — queue + limit state\n"
        "`/stop` — pause execution\n"
        "`/resume` — resume execution\n"
        "`/skip` — skip next task (move to end)\n"
        "`/clear` — clear entire queue\n"
        "`/help` — this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
