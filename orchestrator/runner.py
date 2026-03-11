"""Run claude on a task inside a project repo and commit the result."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from orchestrator.limits import is_limit_error, CLAUDE_PATH

logger = logging.getLogger(__name__)


def run_task(task: dict, proj_cfg: dict, claude_path: str = CLAUDE_PATH) -> tuple[bool, str, bool]:
    """
    Execute a claude task inside the project repo.
    Returns (success, output, was_limit_error).
    """
    repo_path = Path(proj_cfg["repo_path"]).expanduser()

    # Load CLAUDE.md context if present
    context = ""
    claude_md = repo_path / proj_cfg.get("claude_md", "CLAUDE.md")
    if claude_md.exists():
        context = f"<project_context>\n{claude_md.read_text()[:4000]}\n</project_context>\n\n"

    prompt = (
        f"{context}"
        f"Project: {task['project']}\n\n"
        f"Complete this task. Make all necessary code changes, run tests if available, "
        f"ensure nothing is broken. Summarise what you changed in 2-3 sentences at the end.\n\n"
        f"## Task\n{task['title']}\n\n"
        f"## Description\n{task.get('description', '')}"
    )

    try:
        result = subprocess.run(
            [
                claude_path,
                "--print",
                "--allowedTools", "Edit,Write,Read,Bash,Glob,Grep",
                prompt,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout + result.stderr

        if is_limit_error(output):
            return False, output, True
        if result.returncode != 0:
            return False, output, False
        return True, result.stdout.strip(), False

    except subprocess.TimeoutExpired:
        return False, "Task timed out after 10 minutes.", False
    except FileNotFoundError:
        return False, f"claude CLI not found at {claude_path}", False


def commit_and_push(task: dict, proj_cfg: dict) -> bool:
    """Commit all changes in the project repo and push."""
    repo_path = Path(proj_cfg["repo_path"]).expanduser()
    branch = proj_cfg.get("branch", "main")
    msg = (
        f"chore: {task['title'][:72]}\n\n"
        f"Automated by Claude Orchestrator\n"
        f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    )
    cmds = [
        ["git", "config", "user.email", "orchestrator@claude-bot.local"],
        ["git", "config", "user.name", "Claude Orchestrator"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", msg],
        ["git", "push", "origin", branch],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            logger.error("git %s failed: %s", cmd[1], r.stderr[:200])
            return False
    return True
