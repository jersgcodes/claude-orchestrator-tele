# Claude Orchestrator — Task Backlog

Tasks for improving the orchestrator itself. Not processed by the orchestrator.

---

## Monitoring System

### TASK: Add execution stats tracking
**Status:** PENDING
**Priority:** High

Track per-task execution outcomes in a `stats.json` file (or append to queue.json):
- task title, project, started_at, finished_at, duration_seconds, outcome (success/error/limit)
- Keep last N entries (e.g. 500) to avoid unbounded growth
- Expose via `/stats` Telegram command: success rate, avg duration, error count, tasks today

---

### TASK: Add daemon health monitoring via Telegram
**Status:** PENDING
**Priority:** High

Detect and report when the daemon itself is unhealthy:
- Send a daily/periodic heartbeat message (e.g. "🟢 Orchestrator alive — 12 tasks done today")
- Detect if the execution loop has been idle too long (e.g. queue non-empty but no task ran in >10min)
- Alert if repeated task failures on the same task (stuck task detection)
- Consider a `/health` command showing: uptime, tasks today, last task ran at, error rate

---

### TASK: Add `/stats` Telegram command
**Status:** PENDING
**Priority:** Medium

Show a summary of recent execution history:
```
📈 Stats (last 24h)
✅ Done: 8   ❌ Failed: 1   ⏸ Limits: 0
⏱ Avg duration: 4m 12s
Last task: 23 mins ago
```
Requires stats tracking task above.

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

---

### TASK: Per-task permission pre-approval via Telegram
**Status:** PENDING
**Priority:** High

Allow users to pre-approve specific bash commands for a task before it runs, without granting blanket `--dangerously-skip-permissions`.

**Workflow:**
1. Task is written in `tasks.md` as normal (title + description)
2. When user queues the task (`/queue` or button), the orchestrator runs a **dry-run analysis** step first — calls claude with a special prompt asking it to identify all bash commands it anticipates needing that would require permission (e.g. `npm install`, `pip install`, `rm -rf dist/`, `pytest`)
3. Bot sends a Telegram message listing the predicted restricted commands with inline approve/deny buttons per command:
   ```
   ⚠️ Task requires permission for:
   • npm install --save-dev jest
   • rm -rf dist/
   [ ✅ Approve all ] [ ❌ Deny & skip ]
   Or approve individually:
   [ ✅ npm install ] [ ✅ rm -rf dist ] [ ❌ rm -rf dist ]
   ```
4. Approved commands are stored on the queued task as `approved_commands: [...]`
5. When the task executes, runner passes approved commands to claude via `--allowedTools Bash(npm install),Bash(rm -rf dist/)` pattern (Claude Code supports per-command bash allowlisting)
6. Task runs with only those specific bash commands pre-approved — no blanket skip

**Implementation notes:**
- Dry-run analysis prompt: `"List only the bash commands this task would require that need user permission. Be concise, exact commands only. Task: {title}\n{description}"`
- Store `approved_commands` list in the task dict in queue.json
- In runner.py: if `approved_commands` set and not `skip_permissions`, build `--allowedTools` string with `Bash(cmd)` entries instead of plain `Bash`
- Timeout the approval request: if no response in 24h, task stays queued but unapproved (notify again when limit clears and task is next)
- New queue state: `pending_approval` alongside existing `paused`

**New bot callbacks needed:**
- `orch:approve_all:<task_id>` — approve all predicted commands
- `orch:approve_cmd:<task_id>:<cmd_idx>` — approve individual command
- `orch:deny:<task_id>` — skip the task

## Infrastructure

### TASK: Notify on daemon restart
**Status:** PENDING
**Priority:** High

When the daemon starts (or restarts after a crash/reboot), send a Telegram message so the user knows:
- Whether this is a fresh start or a launchd-triggered restart
- Current queue depth and paused state
- Any limit state that was persisted in queue.json

Message format:
```
🔄 Orchestrator started
Queue: 3 task(s) | Status: Running | Limits: OK
```
Or if restarting while a limit was active:
```
🔄 Orchestrator started
Queue: 1 task(s) | Status: ⏸ Limit hit (DAILY) — resets in 2h 14m
```

**Implementation:** Add a startup notification call in `main()` in `mac_daemon.py`, after the bot is started and before `await asyncio.Event().wait()`. Reuse the existing `notify()` helper.

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
