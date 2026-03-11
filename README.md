# Claude Orchestrator

Mac daemon that works through your coding task queues automatically, controlled entirely via Telegram.
Queue tasks from your phone. Detects 5-hour and weekly Claude limits, waits them out, resumes automatically.

## How it works

```
Mac (on, claude auth done — uses subscription):
  mac_daemon.py runs two loops concurrently:

  Loop 1 — Telegram bot (always alive)
    /list smebot          → show PENDING tasks
    /queue smebot next 3  → add next 3 tasks to queue
    /status               → see queue + limit state
    /stop / /resume       → pause / unpause

  Loop 2 — Task executor
    Queue empty?   → sleep
    Limit hit?     → wait, probe every 15 min from 4.5h mark
    Limit cleared? → notify you, resume queue
    Task ready?    → run claude, commit, push, notify you
```

**Billing:** Uses your Claude Code subscription (Mac + `claude auth`). No API credits needed.

## Setup

### 1. Create a Telegram bot
Message [@BotFather](https://t.me/BotFather) → `/newbot` → save the token.
Get your chat ID — send any message to your bot, then visit:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Look for `"chat": {"id": 123456789}`.

### 2. Install dependencies
```bash
cd claude-orchestrator-tele
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure projects
Create `projects.local.yaml` (gitignored — keeps your local paths private):
```yaml
telegram:
  bot_token: "your-telegram-bot-token"
  admin_chat_id: 123456789

projects:
  smebot:
    repo_path: "~/code/smebot"
```

Add more projects in `projects.yaml` (set `active: true`), paths in `projects.local.yaml`.

### 4. Run
```bash
# One-off (test it works):
python mac_daemon.py

# Install as macOS service (starts on login, restarts on crash):
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=yyy
python install.py
```

### 5. Uninstall service
```bash
python install.py remove
```

## Telegram commands

| Command | What it does |
|---|---|
| `/list <project>` | Show next 10 PENDING tasks with index numbers |
| `/queue <project> 1 2 3` | Add tasks by index to queue |
| `/queue <project> next [n]` | Add next n PENDING tasks (default 1) |
| `/status` | Queue contents + limit state |
| `/stop` | Pause execution (queue preserved) |
| `/resume` | Resume execution |
| `/skip` | Move next task to end of queue |
| `/clear` | Wipe entire queue |
| `/help` | Show all commands |

## Adding a new project

1. Add to `projects.yaml`:
   ```yaml
   projects:
     my-new-project:
       active: true
       tasks_file: "docs/tasks.md"
       claude_md: "CLAUDE.md"
       branch: "main"
   ```

2. Add to `projects.local.yaml`:
   ```yaml
   projects:
     my-new-project:
       repo_path: "~/code/my-new-project"
   ```

3. Restart the daemon (or reinstall with `python install.py`).

## Task file format

The orchestrator reads tasks from your project's `tasks.md`:

```markdown
## COMPLETED
- [x] Already done

## PRIORITY 1 — Feature Name

### Task 1 — module.py: What to do
- Description
- Status: PENDING

### Task 2 — other.py: Something else
- Status: PENDING
```

Tasks with `Status: DONE` or under `## COMPLETED` are skipped.

## Limit detection

When claude returns a usage limit error, the orchestrator:
1. Detects whether it's a **5-hour** or **weekly** limit from the error message
2. Parses the reset time from the message (falls back to safe defaults: +5h15m or next Monday)
3. Notifies you via Telegram: "⏸ Limit hit (5HOUR) — resets in 4h 45m"
4. Starts probing every 15 min after the 4.5-hour mark
5. When limits clear: notifies you and resumes the queue automatically

## Logs

```
orchestrator.log        — combined info log
orchestrator-error.log  — stderr (crashes, errors)
```
