# CLAUDE.md — Claude Orchestrator

A macOS daemon that automates coding task queues, controlled entirely via Telegram.

## Architecture

Two concurrent async loops run side-by-side:
1. **Telegram bot** — receives commands, sends notifications
2. **Execution loop** — polls queue every 60s, runs tasks via `claude` CLI

Entry point: `mac_daemon.py` → `main()` → `build_app()` + `execution_loop()`

## Key Files

| File | Purpose |
|------|---------|
| `mac_daemon.py` | Entry point, execution loop, `build_app()`, `_tick()`, `notify()` |
| `orchestrator/bot.py` | All Telegram command handlers and inline button callbacks |
| `orchestrator/queue.py` | Queue persistence (`queue.json`): tasks, paused state, limit tracking |
| `orchestrator/config.py` | Load/merge `projects.yaml` + `projects.local.yaml` + env vars |
| `orchestrator/runner.py` | Run `claude` CLI, `commit_and_push()` |
| `orchestrator/limits.py` | Detect 5-hour/weekly limits, parse reset times, `probe()` |
| `orchestrator/task_reader.py` | Parse `tasks.md`, extract PENDING tasks |
| `orchestrator/state.py` | Legacy state file (minimal use) |

## Configuration

- `projects.yaml` — project list (public, in git): `active`, `tasks_file`, `branch`, `claude_md`
- `projects.local.yaml` — gitignored: `repo_path`, `bot_token`, `admin_chat_id`
- Env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CLAUDE_PATH`
- Config merges: base YAML → local YAML → env vars (env wins)

## Telegram Bot Commands

| Command | Handler | Description |
|---------|---------|-------------|
| `/menu` | `cmd_menu` | Main menu with inline buttons (hamburger menu) |
| `/list [project]` | `cmd_list` | Show next 10 PENDING tasks |
| `/queue <project> 1 2 3` | `cmd_queue` | Queue tasks by index |
| `/queue <project> next [n]` | `cmd_queue` | Queue next n tasks |
| `/status` | `cmd_status` | Queue contents + limit state |
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

## UI Design Specs

### Main Menu (`/menu`, `orch:menu`)
```
☰ Claude Orchestrator

🟢 Limits OK · ▶️ Running      ← limit state · paused state
📋 3 task(s) queued             ← queue count (or "Queue empty")

[ 📋 List Tasks ] [ 📊 Status ]
[ ⏸ Stop        ] [ ⏭ Skip Next ]   ← Skip only shown if queue not empty
[ 🗑 Clear Queue ]                   ← only shown if queue not empty
[ ❓ Help        ]
```
Stop/Resume toggles based on current `paused` state. Opens on `/start` and `/menu`.

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
| Task starting | `⚙️ *Starting task*\n[project] title` |
| Task done | `✅ *Done* — [project] title\n\n<output[:400]>\n_Changes committed and pushed._` |
| Limit hit | `⏸ *Limit hit* (5HOUR)\n[project] title\n\nReset in approx. *Xh Ym*` |
| Limit reset | `🟢 *Limits reset* (5HOUR)\nResuming queue...` |
| Error | `❌ *Error* — [project] title\n\n\`\`\`<output[:400]>\`\`\`` |
| Bad repo path | `❌ Repo path not found for *project*: \`/path\`` |

## Task Execution Flow

1. `_tick()` runs every 60s
2. If limit hit: wait 4.5h then probe; notify on recovery
3. If not paused and queue not empty: `peek_next()` → `run_task()` → `commit_and_push()`
4. On limit: `set_limit_hit()`, task stays in queue
5. On success: `pop_next()`, commit+push, notify
6. On error: `pop_next()`, notify with output excerpt

## Task File Format

Tasks live in each project's `tasks_file` (e.g., `docs/tasks.md`). Parser looks for `PENDING` marker. Tasks have `id`, `title`, `description`.

## Queue State (queue.json)

```json
{
  "tasks": [{"project": "...", "id": "...", "title": "...", "queued_at": "..."}],
  "paused": false,
  "limit": {"type": null, "hit_at": null, "reset_at": null}
}
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
