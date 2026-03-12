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

### TASK: Add task retry on failure
**Status:** PENDING
**Priority:** Medium

Currently failed tasks are dropped. Add a `max_retries` per-project config (default 0).
On failure, if retries remaining, re-queue the task at the front with a decremented retry counter.
Notify on final failure after all retries exhausted.

---

### TASK: Log rotation for orchestrator.log
**Status:** PENDING
**Priority:** Low

orchestrator.log grows unbounded. Switch `logging.basicConfig` to `RotatingFileHandler`
(e.g. 5MB max, keep 3 backups). Prevents disk issues on long-running deployments.

---

### TASK: Add `/logs` command to tail recent log output
**Status:** PENDING
**Priority:** Low

Send last 20 lines of orchestrator.log as a Telegram message (inside a code block).
Useful for debugging without SSH-ing into the machine.
Cap at 4000 chars (Telegram message limit).

---

### TASK: Smarter resume detection on task start
**Status:** PENDING
**Priority:** Medium

Currently the prompt always asks Claude to check `git status` before starting (basic "continue" behaviour). A smarter version:
- Before running the task, do a quick `git status --porcelain` check in the runner itself (not via claude)
- If there are uncommitted changes, prepend a stronger "you were interrupted — review and continue" prompt
- If the repo is clean, use the normal "start fresh" prompt
- Optionally: store a `started_at` timestamp on the task in queue.json so we know how long it's been interrupted

---

### TASK: Graceful shutdown on task in progress
**Status:** PENDING
**Priority:** Low

Currently `/stop` only prevents the next tick from starting a task. If a task is actively
running (subprocess), stopping should ideally wait for it to finish rather than leaving
a half-executed task. Track the running subprocess PID in queue state so it can be
inspected or terminated cleanly.

---

### TASK: Per-task permission pre-approval via Telegram
**Status:** DONE
**Priority:** High

Allow users to pre-approve specific bash commands for a task before it runs, without granting blanket `--dangerously-skip-permissions`.

**Workflow:**
1. Task is written in `tasks.md` as normal (title + description)
2. When the task is next in queue, the orchestrator runs a **dry-run analysis** step — calls claude with a special prompt asking it to identify all bash commands it anticipates needing
3. Bot sends a Telegram message listing the predicted restricted commands with Approve all / Deny buttons
4. Approved commands are stored on the queued task as `approved_commands: [...]`
5. When the task executes, runner passes approved commands to claude via `--allowedTools Bash(cmd),...` pattern
6. Task runs with only those specific bash commands pre-approved — no blanket skip

**Implemented:**
- `task_reader.py` parses `**Requires approval:**` bullet section from tasks.md into `task["requires_approval"]`
- Tasks declare their own required commands — no auto-analysis, no project flag needed
- `set_task_pending_approval()`, `approve_task()`, `deny_task()`, `get_task()` in `queue.py`
- `peek_next()` skips `pending_approval` tasks so other tasks proceed
- `_request_task_approval()` in `mac_daemon.py` — sends Telegram approval request using declared commands
- `orch:approve_all:<project>:<id>` and `orch:deny:<project>:<id>` callbacks in `bot.py`

**Task format:**
```markdown
### Task 3 — Install and configure Jest
**Status:** PENDING
**Requires approval:**
- npm install --save-dev jest
- npm test
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

### TASK: Support multiple active projects with round-robin queue
**Status:** PENDING
**Priority:** Low

Currently tasks from all projects are interleaved in one flat queue in the order they were
added. A round-robin mode (one task per project per cycle) would be fairer for multi-project
setups. Add a `queue_mode: roundrobin` global config option.
