---
name: claude-slack-agent
description: "Two-way Slack agent for chatting via a dedicated private agent channel. Say 'start slack agent' to begin, 'stop slack agent' to end. Say 'set up slack agent' to run conversational onboarding. Supports multiple concurrent sessions, image uploads, and conversation context."
allowed-tools:
  - Bash(*/claude-slack-agent/scripts/agent.sh:*)
  - Bash(*/claude-slack-agent/scripts/listener.sh:*)
  - Bash(*/claude-slack-agent/scripts/healthcheck.sh:*)
  - Bash(python3 */claude-slack-agent/scripts/alert.py:*)
  - Bash(python3 */claude-slack-agent/scripts/inbox.py:*)
  - Bash(python3 */claude-slack-agent/scripts/config.py:*)
metadata:
  author: claude
  version: "11.0"
  status: stable
---

# Slack Agent

Two-way Slack chat via a dedicated private agent channel.

## Setup / Installation

When the user says **"set up slack agent"**, **"install slack agent"**, or **"configure slack agent"**:

1. Read the file `INSTALL.md` in this skill's directory.
2. Follow the conversational onboarding flow described there step by step.
3. Walk the user through credential checks, channel naming, and configuration.

## Thread Naming

When starting a session, use a descriptive title based on what the session is doing. Examples: "Building reporting dashboard", "Debugging CI failures", "Migrating to React". NOT generic titles like "Claude Code session" or "New session".

## Quick Start

**"start slack agent"** / **"turn on slack"**:

```bash
bash scripts/agent.sh start "Descriptive title"
# agent.sh start spawns listener.sh AND healthcheck.sh internally.
# Both are single-instance, so a second call is a safe no-op.
```

Then run the listener as a fresh `Bash run_in_background:true` task so its exit fires a task-completed notification to the agent:

```bash
bash scripts/listener.sh
# run_in_background: true
```

**"stop slack agent"** / **"turn off slack"**:

```bash
bash scripts/agent.sh stop
```

## Architecture (canonical)

Polling is a **foreground child of the harness**, not a launchd daemon. The harness fires a task-completed notification only on child-process exits. A detached daemon does not fire it, so the agent never sees inbound messages even when they land in a queue file. We learned this the hard way. See deprecated headers in `scripts/daemon.py`, `LaunchAgents/*.plist`, and `install-daemon.sh`.

Three independent layers keep the bot alive:

1. **Single-listener invariant.** `listener.sh` claims `$STATE_DIR/listener.pid` on startup. If a live listener already owns the slot, a new invocation exits silently (rc 0). Spam-calling produces exactly one process. Verify with `ps aux | grep listener.sh`.
2. **One-time-per-batch ack.** When messages arrive, `listener.sh` posts `:mag: Looking into it...` only if the highest ts in the batch is newer than `$STATE_DIR/last_acked_ts`. A respawned listener finding the same queued messages does not re-ack.
3. **Silent watchdog.** `healthcheck.sh` auto-starts with `agent.sh start` and polls the listener PID every 30 seconds (override with `HEALTHCHECK_INTERVAL`). If the listener dies (the harness reaps idle tasks with exit 144 every 2 to 3 minutes), the watchdog respawns silently. Only after three consecutive respawn failures does it post a single `:warning:`. Happy-path Slack noise is zero.

First debug step when you suspect silence: `python3 scripts/inbox.py health`. Returns `listener_alive`, `listener_pid`, `thread_ts`, `session_id`, `state_dir`.

## Handling Messages

When the listener exits (task-completed notification fires), do these two steps:

1. Read the user's message from the captured stdout.
2. `python3 inbox.py reply "response"` to post and advance the cursor.
3. Restart `listener.sh` via a fresh `Bash run_in_background:true` call.

If multiple messages came in fast, `check` returns all of them. One reply addresses everything; the next listener cycle covers the next batch.

## Commands

| Command | Purpose |
|---------|---------|
| `agent.sh start <title>` | Create thread, start caffeinate + listener + watchdog |
| `agent.sh stop` | End session, kill all child processes, clear PID files |
| `agent.sh status [text]` | Set or read the heartbeat status line |
| `listener.sh` | Background poll. Single-instance, exits on message |
| `healthcheck.sh` | Background watchdog. Respawns a dead listener |
| `heartbeat.sh` | Optional status poster (reads `$STATE_DIR/status.txt`) |
| `alert.py start <title>` | Create thread |
| `alert.py post <msg>` | Post update (robot prefix + divider) |
| `alert.py alert <msg>` | Post with @mention + push notification |
| `alert.py ack` | Post `:loading_:` typing indicator |
| `alert.py end` | Post `_Session ended._` |
| `alert.py image <path> [caption]` | Upload screenshot/image to thread |
| `inbox.py check` | Check for messages + recent context |
| `inbox.py reply <msg>` | Reply, advance cursor (agent restarts listener) |
| `inbox.py reply --dry-run` | Test path without posting |
| `inbox.py health` | Report listener_alive, pid, thread_ts. Read-only |
| `config.py setup` | Interactive onboarding (detect user, find/create channel) |
| `config.py show` | Display current config |

## Message Format

- **Bot messages**: Start with `[abc123] :robot_face:`, end with `─ ─ ─` divider
- **Ack**: `:mag: Looking into it...` (one per batch, when messages arrive)
- **Session header**: `[abc123] :robot_face:  *Title*` (parent message only)
- **Session end**: `_Session ended._`
- **@mention**: Only in alerts or when the user needs to see it in activity
- **Images**: `alert.py image /path/to/screenshot.png "Caption"`

## Status Update Style

Use plain symbols Slack renders cleanly:

```
✓ completed
→ next up
⏳ waiting on something
⚠️ errors or blockers
💬 needs input
```

## Long-Running Tasks

For bigger jobs (builds, extractions, CI monitoring), use `run.sh` to wrap the command. It auto-posts start/done/failed to Slack:

```bash
bash scripts/run.sh "Extracting tarball" tar xzf ~/Downloads/big-file.tar.gz -C ~/
# run_in_background: true
```

For multi-step tasks, use `alert.py post` at milestones:

```bash
python3 alert.py post "✓ Step 1 done, starting step 2"
```

Use judgment. Small quick tasks do not need progress updates. Anything over ~30 seconds should post something so the user knows what is happening.

## Multi-Session

Multiple Claude Code sessions run simultaneously. Each gets its own thread and state dir at `~/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/`. `agent.sh stop` only kills that session's child processes.

## Conversation Context

`inbox.py check` and `inbox.py reply` include `recent_context`, the last 5 thread messages (both human and bot), so responses feel conversational without re-reading the full thread.

## Optional: UserPromptSubmit safety net

`scripts/check-unread-hook.sh` is a belt-and-suspenders UserPromptSubmit hook. If the agent ever misses a listener completion, the next user prompt triggers this hook, which checks for unread Slack messages and surfaces a system reminder before the turn runs. To enable, add to `~/.claude/settings.json`:

```json
"hooks": {
  "UserPromptSubmit": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash ~/.claude/skills/claude-slack-agent/scripts/check-unread-hook.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

(Adjust the path to wherever you installed the skill.) The hook is silent when no Slack session is active for the current Claude session and times out gracefully if the Slack API is slow.

## Technical Details

- **Config**: `~/.config/slack-alerts/config.json` (auto-generated on first run)
- **Credentials**: `~/.config/slack-skill/credentials.json` (Slack token)
- **State**: `~/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/`
- **Detection**: User messages have no `bot_id`; bot messages have `bot_id` set OR start with `:robot_face:` / `:loading_:` / `:mag:`
- **Caffeinate**: Prevents Mac sleep while the agent is on

## Deprecated files (do not use)

| File | Why |
|---|---|
| `scripts/daemon.py` | Launchd architecture. Detached process does not fire harness task notifications, so agent never sees inbound messages |
| `LaunchAgents/*.plist` | Same reason |
| `install-daemon.sh` | Stubbed out. Exits without action |

The deprecated path is kept in the repo for forensic value. If anyone is tempted to revisit launchd, the headers explain why it cannot work with the current harness contract.
