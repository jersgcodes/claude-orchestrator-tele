"""Parse a project's tasks.md and extract PENDING tasks in order."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def _parse_requires_approval(lines: list[str]) -> list[str]:
    """
    Extract commands from a **Requires approval:** section in a task's lines.
    Returns list of command strings, or [] if section not present.

    Example task format:
        **Requires approval:**
        - npm install --save-dev jest
        - npm test
    """
    commands: list[str] = []
    in_section = False
    for line in lines:
        if re.match(r"^\*\*Requires approval:\*\*", line.strip()):
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("- "):
                commands.append(line.strip()[2:].strip())
            elif line.strip() and not line.strip().startswith("-"):
                # Non-bullet, non-empty line ends the section
                in_section = False
    return commands


def _flush_task(task: dict, lines: list[str]) -> None:
    """Populate task description and requires_approval from collected lines."""
    task["description"] = "\n".join(lines).strip()
    approval_commands = _parse_requires_approval(lines)
    if approval_commands:
        task["requires_approval"] = approval_commands


def get_pending_tasks(repo_path: str, tasks_file: str) -> list[dict]:
    """
    Return list of PENDING tasks from tasks_file, in document order.
    Each task dict: {id, title, description, priority, requires_approval?}
    """
    path = Path(repo_path) / tasks_file
    if not path.exists():
        return []

    text = path.read_text()
    tasks = []
    current_priority = ""
    task_id = 0

    current_task: Optional[dict] = None
    current_lines: list[str] = []

    for line in text.splitlines():
        # Detect priority headers (## PRIORITY N — ...)
        priority_match = re.match(r"^## (PRIORITY \d+|COMPLETED)", line)
        if priority_match:
            if current_task and current_lines:
                _flush_task(current_task, current_lines)
                tasks.append(current_task)
            current_task = None
            current_lines = []
            current_priority = priority_match.group(1)
            continue

        # Skip completed section entirely
        if current_priority == "COMPLETED":
            continue

        # Detect task headers (### Task N — ...)
        task_match = re.match(r"^### (Task \d+(?:\.\d+)? — .+)", line)
        if task_match:
            if current_task and current_lines:
                _flush_task(current_task, current_lines)
                tasks.append(current_task)
            task_id += 1
            current_task = {
                "id": task_id,
                "title": task_match.group(1),
                "priority": current_priority,
                "description": "",
                "status": "PENDING",
            }
            current_lines = []
            continue

        if current_task is None:
            continue

        # Detect status line
        if "Status: DONE" in line or "Status: COMPLETE" in line:
            current_task["status"] = "DONE"
        elif "Status: PENDING" in line:
            current_task["status"] = "PENDING"
        elif "Status: IN PROGRESS" in line:
            current_task["status"] = "IN PROGRESS"
        elif "Status: USER ACTION" in line:
            current_task["status"] = "USER ACTION"
        elif "Status: BLOCKED" in line:
            current_task["status"] = "BLOCKED"

        current_lines.append(line)

    # Flush last task
    if current_task and current_lines:
        _flush_task(current_task, current_lines)
        tasks.append(current_task)

    return [t for t in tasks if t["status"] not in ("DONE", "COMPLETE", "USER ACTION", "BLOCKED")]


def get_next_tasks(repo_path: str, tasks_file: str, n: int = 4) -> list[dict]:
    """Return the next n PENDING tasks."""
    return get_pending_tasks(repo_path, tasks_file)[:n]
