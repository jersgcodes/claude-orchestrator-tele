# Claude Orchestrator — Task Backlog

Tasks for improving the orchestrator itself. Not processed by the orchestrator.

---

## Monitoring System

### TASK: Add execution stats tracking
**Status:** DONE
**Priority:** High

Track per-task execution outcomes in a `stats.json` file (or append to queue.json):
- task title, project, started_at, finished_at, duration_seconds, outcome (success/error/limit)
- Keep last N entries (e.g. 500) to avoid unbounded growth
- Expose via `/stats` Telegram command: success rate, avg duration, error count, tasks today

**Implemented:** `orchestrator/stats.py` — `record()`, `summary()`, `last_ran_at()`. `/stats` command in `bot.py`. Stats recorded in `_tick()` for all outcomes.

---

### TASK: Add daemon health monitoring via Telegram
**Status:** DONE
**Priority:** High

Detect and report when the daemon itself is unhealthy:
- Send a daily/periodic heartbeat message (e.g. "🟢 Orchestrator alive — 12 tasks done today")
- Detect if the execution loop has been idle too long (e.g. queue non-empty but no task ran in >10min)
- Alert if repeated task failures on the same task (stuck task detection)
- Consider a `/health` command showing: uptime, tasks today, last task ran at, error rate

**Implemented:** `_heartbeat_loop()` in `mac_daemon.py` (daily). Idle detection in `_tick()` (alerts once/hour if queue non-empty >10min with no task running). `/health` command in `bot.py`.

---

### TASK: Add `/stats` Telegram command
**Status:** DONE
**Priority:** Medium

Show a summary of recent execution history:
```
📈 Stats (last 24h)
✅ Done: 8   ❌ Failed: 1   ⏸ Limits: 0
⏱ Avg duration: 4m 12s
Last task: 23 mins ago
```

**Implemented:** `cmd_stats()` in `bot.py`. Requires `orchestrator/stats.py`.

---

### TASK: Smarter resume detection on task start
**Status:** DONE
**Priority:** Medium

Before running a task, do a Python-side `git status --porcelain` check rather than asking Claude to do it.

**Implemented:** `_has_uncommitted_changes()` in `runner.py`. If uncommitted changes exist, a stronger "you were interrupted — review and continue" prompt is used. If repo is clean, a lightweight "start fresh" prompt is used.

---

### TASK: Add task retry on failure
**Status:** DONE
**Priority:** Medium

Add `max_retries` per-project config (default 0). On failure, if retries remaining, re-queue the task at the front with an incremented `retries_used` counter. Notify on each retry attempt and on final failure.

**Implemented:** `requeue_at_front()` in `queue.py`. Retry logic in `_tick()` in `mac_daemon.py`. Configure via `max_retries: 2` in `projects.yaml` per project.

---

### TASK: Add `/logs` command to tail recent log output
**Status:** PENDING
**Priority:** Medium

Send last 20 lines of orchestrator.log as a Telegram message (inside a code block).
Useful for debugging without SSH-ing into the machine.
Cap at 4000 chars (Telegram message limit).

---

### TASK: Log rotation for orchestrator.log
**Status:** PENDING
**Priority:** Low

orchestrator.log grows unbounded. Switch `logging.basicConfig` to `RotatingFileHandler`
(e.g. 5MB max, keep 3 backups). Prevents disk issues on long-running deployments.

---

### TASK: Per-task permission pre-approval via Telegram
**Status:** DONE
**Priority:** High

Allow users to pre-approve specific bash commands for a task before it runs, without granting blanket `--dangerously-skip-permissions`.

**Workflow:**
1. Task author adds `**Requires approval:**` section to the task in `tasks.md` listing exact commands
2. When the task is next in queue, the orchestrator sends a Telegram approval request with those declared commands
3. User approves or denies via inline buttons
4. On approve: `approved_commands` stored on task, runs with `--allowedTools Bash(cmd),...` allowlist
5. On deny: task removed from queue

**Implemented:**
- `task_reader.py` parses `**Requires approval:**` bullet section from tasks.md into `task["requires_approval"]`
- Tasks declare their own required commands — no auto-analysis, no project flag needed
- `set_task_pending_approval()`, `approve_task()`, `deny_task()`, `get_task()` in `queue.py`
- `peek_next()` skips `pending_approval` tasks so other tasks proceed
- `_request_task_approval()` in `mac_daemon.py` — sends Telegram approval request using declared commands
- `orch:approve_all:<project>:<id>` and `orch:deny:<project>:<id>` callbacks in `bot.py`

**Task format:**
```markdown
### Task 3 — Add pytest and write tests for auth module
**Status:** PENDING
**Requires approval:**
- pip install pytest
- pytest
```

---

## Infrastructure

### TASK: Notify on daemon restart
**Status:** DONE
**Priority:** High

When the daemon starts (or restarts after a crash/reboot), send a Telegram message so the user knows:
- Current queue depth and paused state
- Any limit state that was persisted in queue.json

**Implemented:** `_startup_notify()` in `mac_daemon.py`, called in `main()` after bot starts.

---

### TASK: Add projects.yaml validation on startup
**Status:** PENDING
**Priority:** Medium

On daemon start, validate all active projects:
- `repo_path` exists and is a git repo
- `tasks_file` exists
- `claude_md` path exists (warn if missing, don't fail)
Notify via Telegram on startup with any config warnings.

---

### TASK: Graceful shutdown on task in progress
**Status:** PENDING
**Priority:** Low

Currently `/stop` only prevents the next tick from starting a task. If a task is actively
running (subprocess), stopping should ideally wait for it to finish rather than leaving
a half-executed task. Track the running subprocess PID in queue state so it can be
inspected or terminated cleanly.

---

### TASK: API registry audit
**Status:** PENDING
**Priority:** Low

Run `scripts/audit_api_registry.py` to scan all projects for API usage patterns
and compare against `~/claude/API_REGISTRY.md`. Update the registry with any
new APIs found, remove any that no longer exist. Queue this monthly.

---

### TASK: Support multiple active projects with round-robin queue
**Status:** PENDING
**Priority:** Low

Currently tasks from all projects are interleaved in one flat queue in the order they were
added. A round-robin mode (one task per project per cycle) would be fairer for multi-project
setups. Add a `queue_mode: roundrobin` global config option.
