# CLAUDE.md — Claude Orchestrator

A macOS daemon that automates coding task queues, controlled entirely via Telegram.

## Architecture

Three concurrent async loops run side-by-side:
1. **Telegram bot** — receives commands, sends notifications
2. **Execution loop** — polls queue every 60s, runs tasks via `claude` CLI
3. **Heartbeat loop** — sends a daily status summary

Entry point: `mac_daemon.py` → `main()` → `build_app()` + `execution_loop()` + `_heartbeat_loop()`

## Key Files

| File | Purpose |
|------|---------|
| `mac_daemon.py` | Entry point, execution loop, `_tick()`, `notify()`, `_startup_notify()`, `_heartbeat_loop()`, `_request_task_approval()` |
| `orchestrator/bot.py` | All Telegram command handlers and inline button callbacks |
| `orchestrator/queue.py` | Queue persistence (`queue.json`): tasks, paused state, limit tracking, approval state |
| `orchestrator/stats.py` | Execution stats persistence (`stats.json`): `record()`, `summary()`, `last_ran_at()` |
| `orchestrator/bot_state.py` | Shared daemon state: `start_time` (used by `/health`) |
| `orchestrator/config.py` | Load/merge `projects.yaml` + `projects.local.yaml` + env vars |
| `orchestrator/runner.py` | Run `claude` CLI, `commit_and_push()`, `dry_run_analysis()` |
| `orchestrator/limits.py` | Detect 5-hour/weekly limits, parse reset times, `probe()` |
| `orchestrator/task_reader.py` | Parse `tasks.md`, extract PENDING tasks |

## Configuration

- `projects.yaml` — project list (public, in git): `active`, `tasks_file`, `branch`, `claude_md`
- `projects.local.yaml` — gitignored: `repo_path`, `bot_token`, `admin_chat_id`
- Env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CLAUDE_PATH`
- Config merges: base YAML → local YAML → env vars (env wins)

### Per-project flags

| Flag | Default | Description |
|------|---------|-------------|
| `active` | `false` | Include project in queue/list operations |

> **Note:** `--dangerously-skip-permissions` is intentionally not supported. Use the per-task `**Requires approval:**` section in `tasks.md` to pre-approve specific commands instead. Blanket permission bypass is not recommended.

## Telegram Bot Commands

| Command | Handler | Description |
|---------|---------|-------------|
| `/menu` | `cmd_menu` | Main menu with inline buttons (hamburger menu) |
| `/list [project]` | `cmd_list` | Show next 10 PENDING tasks |
| `/queue <project> 1 2 3` | `cmd_queue` | Queue tasks by index |
| `/queue <project> next [n]` | `cmd_queue` | Queue next n tasks |
| `/status` | `cmd_status` | Queue contents + limit state |
| `/stats` | `cmd_stats` | Execution stats (last 24h): done/failed/limits, avg duration, last task |
| `/health` | `cmd_health` | Daemon health: uptime, error rate, last task, queue depth |
| `/stop` | `cmd_stop` | Pause execution |
| `/resume` | `cmd_resume` | Resume execution |
| `/skip` | `cmd_skip` | Move next task to end of queue |
| `/clear` | `cmd_clear` | Clear entire queue |
| `/help` | `cmd_help` | Show all commands |
| `/start` | → `cmd_menu` | Opens main menu on first use |

## Inline Button System

All buttons use `callback_data` prefixed `orch:`. Handler: `on_button()` in `bot.py`.

| Callback | Action |
|----------|--------|
| `orch:menu` | Show/refresh main menu |
| `orch:stop` / `orch:resume` | Toggle pause |
| `orch:skip` | Skip next task |
| `orch:clear` | Clear queue |
| `orch:list` | Show pending tasks (default project) |
| `orch:status` | Show status |
| `orch:help` | Show help text |
| `orch:qnext:<project>:<n>` | Queue next n tasks for project |
| `orch:approve_all:<project>:<id>` | Approve all predicted commands for task |
| `orch:deny:<project>:<id>` | Remove task from queue (deny approval) |

## UI Design Specs

### Native Telegram Menu Button (hamburger ≡, bottom-left of chat input)

**Recommended approach.** Set via `set_chat_menu_button(MenuButtonCommands())` in `_set_commands()`. Telegram renders a `≡` button natively — tapping it shows the full command list registered with `set_my_commands()`.

Commands shown in the native menu (order matters — first = most prominent):
```
≡  menu    — open the main menu
   list    — list <project> — show next 10 PENDING tasks
   queue   — queue <project> next [n] — add tasks to queue
   status  — queue contents + limit state
   stats   — execution stats for the last 24h
   health  — daemon health: uptime, last task, error rate
   stop    — pause execution (queue preserved)
   resume  — resume execution
   skip    — move next queued task to end
   clear   — wipe entire queue
   help    — show all commands
```

### Inline Menu Message (`/menu`, `orch:menu`)

A supplementary hub message with action buttons, shown on `/start`, `/menu`, or the `☰ Menu` button from other keyboards.

```
☰ Claude Orchestrator

🟢 Limits OK · ▶️ Running      ← limit state · paused state
📋 3 task(s) queued             ← queue count (or "Queue empty")

[ 📋 List Tasks ] [ 📊 Status ]
[ ⏸ Stop        ] [ ⏭ Skip Next ]   ← Skip only shown if queue not empty
[ 🗑 Clear Queue ]                   ← only shown if queue not empty
[ ❓ Help        ]
```
Stop/Resume toggles based on current `paused` state.

### Status keyboard (`/status`, `orch:status`)
```
[ ⏸ Stop / ▶️ Resume ] [ ⏭ Skip next ]   ← Skip only if queue not empty
[ 🗑 Clear queue      ]                   ← only if queue not empty
[ ☰ Menu              ]
```

### List keyboard (`/list`, `orch:list`)
```
[ Queue next 1 ] [ Queue next 3 ] [ Queue next 5 ]
[ ☰ Menu ]
```

### Keyboard helper functions (bot.py)

- `_main_menu_keyboard(paused, queue_empty)` — hamburger menu hub
- `_status_keyboard(paused, queue_empty)` — Stop/Resume + Skip/Clear + Menu
- `_list_keyboard(project)` — Queue next 1/3/5 + Menu

### Notification messages (sent by `_tick()` in mac_daemon.py)

| Event | Format |
|-------|--------|
| Daemon started | `🔄 *Orchestrator started*\nQueue: N task(s) \| Status \| Limits` |
| Task starting | `⚙️ *Starting task*\n[project] title` |
| Task done | `✅ *Done* — [project] title\n\n<output[:400]>\n_Changes committed and pushed._` |
| Limit hit | `⏸ *Limit hit* (5HOUR)\n[project] title\n\nReset in approx. *Xh Ym*` |
| Limit reset | `🟢 *Limits reset* (5HOUR)\nResuming queue...` |
| Error | `❌ *Error* — [project] title\n\n\`\`\`<output[:400]>\`\`\`` |
| Idle alert | `⚠️ *Idle alert* — queue has N task(s) but nothing ran for Xm` |
| Heartbeat (daily) | `🟢 *Orchestrator alive*\nTasks (24h): ✅ N ❌ N ⏸ N\nQueue: N pending\nLast task: Xm ago` |
| Approval request | `⚠️ *Permission request*\n_[project] title_\n\nPredicted commands:\n  • cmd` |
| Auto-approved | `✅ No restricted commands for _title_\nAuto-approved.` |

## Task Execution Flow

1. `_tick()` runs every 60s
2. If paused: return
3. If limit hit: wait 4.5h then probe; notify on recovery
4. Idle detection: if queue non-empty and last task >10min ago, alert (once/hour)
5. `peek_next()` — returns first task not in `pending_approval` state
6. If `require_approval` and no `approved_commands`: run `_request_task_approval()`, return
7. `run_task()` → `commit_and_push()`
8. Record outcome in `stats.json`
9. On limit: `set_limit_hit()`, task stays in queue
10. On success: `pop_next()`, commit+push, notify
11. On error: `pop_next()`, notify with output excerpt

## Per-Task Approval Flow

Tasks declare required bash commands directly in `tasks.md` using a `**Requires approval:**` section. No auto-analysis, no project flag — the task author fills in exactly what needs approval.

### Task format with approval

```markdown
### Task 3 — Install and configure Jest
**Status:** PENDING
**Requires approval:**
- npm install --save-dev jest @types/jest
- npm test

Install Jest for unit testing and add a basic test suite for the auth module.
```

### Execution flow

1. `task_reader.py` parses `**Requires approval:**` bullets into `task["requires_approval"]`
2. When queued, `requires_approval` is carried on the task dict in `queue.json`
3. `peek_next()` returns the task (not yet pending)
4. `_tick()` sees `requires_approval` is set, `approved_commands` not yet set → calls `_request_task_approval()`
5. `_request_task_approval()` marks task `approval_status: "pending"` and sends Telegram message with Approve all / Deny buttons
6. User taps Approve → `approve_task()` stores commands as `approved_commands`, clears `pending_approval`
7. Next tick: `peek_next()` returns task (approved), `run_task()` uses `Bash(cmd)` allowlist
8. User taps Deny → `deny_task()` removes task from queue

Tasks without a `**Requires approval:**` section run immediately with no gate.

## Task File Format

Tasks live in each project's `tasks_file` (e.g., `docs/tasks.md`). Parser looks for `PENDING` marker. Tasks have `id`, `title`, `description`.

## Queue State (queue.json)

```json
{
  "tasks": [
    {
      "project": "...", "id": 1, "title": "...", "queued_at": "...",
      "approval_status": "pending|approved",   // only if require_approval
      "predicted_commands": ["npm install"],    // set during analysis
      "approved_commands": ["npm install"]      // set after user approves
    }
  ],
  "paused": false,
  "limit": {"type": null, "hit_at": null, "reset_at": null}
}
```

## Stats (stats.json)

Rolling log of last 500 task outcomes. Each entry:
```json
{"title": "...", "project": "...", "started_at": "...", "finished_at": "...", "duration_seconds": 142, "outcome": "success|error|limit"}
```

## Limit Handling

- Two limit types: `5hour`, `weekly`
- On detection: `set_limit_hit()` stores type + timestamps
- Probing starts after 4.5h elapsed since hit
- `probe()` runs a minimal `claude` call to check availability
- On recovery: `clear_limit()`, notify user, resume next tick

## macOS Daemon

- `install.py` registers as launchd service: `com.claude.orchestrator`
- Logs: `orchestrator.log` (stdout), `orchestrator-error.log` (stderr)
- Auto-starts on login, auto-restarts on crash
- Claude CLI path: `/opt/homebrew/bin/claude` (override via `CLAUDE_PATH`)
- On each start: sends a startup notification via Telegram with current queue/limit state
