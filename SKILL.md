---
name: 0-slack-alerts
description: "Two-way Slack agent for chatting with Aaron via #agent-aaron. Say 'start slack agent' to begin, 'stop slack agent' to end. Supports multiple concurrent sessions, image uploads, and conversation context."
allowed-tools:
  - Bash(*/0-slack-alerts/scripts/agent.sh:*)
  - Bash(*/0-slack-alerts/install-daemon.sh:*)
  - Bash(python3 */0-slack-alerts/scripts/alert.py:*)
  - Bash(python3 */0-slack-alerts/scripts/inbox.py:*)
  - Bash(launchctl *)
metadata:
  author: claude
  version: "10.0"
  status: stable
---

# Slack Agent

Two-way Slack chat with Aaron via `#agent-aaron` on Block workspace.

## Architecture (2026-05-10 rewrite)

Polling lives in a **launchd-owned daemon**, not in a harness-owned listener. The old listener.sh model died every 2-3 minutes when the harness reaped idle background tasks, and every reap posted `:warning: Listener died` warnings into the channel. The daemon is owned by macOS, survives harness reaps, agent dispatches, idle periods, sleep/wake, and reboots (relaunches at login).

```
launchd
  └─ python3 daemon.py  (every 3s)
       └─ for each ~/.config/slack-alerts/sessions/<id>/ with thread.json:
            └─ fetch new Slack replies > daemon_cursor
                 └─ append to <id>/inbox-queue.jsonl

claude code session
  ├─ agent.sh start "..."  → ensures daemon is loaded, creates thread
  ├─ inbox.py check         → reads queue (no Slack round-trip)
  ├─ inbox.py reply "..."   → posts to Slack, advances queue consume cursor
  └─ agent.sh stop          → touches session.ended marker, daemon skips it
```

## One-time install

```bash
bash ~/.claude/skills/0-slack-alerts/install-daemon.sh
```

This copies the plist into `~/Library/LaunchAgents/`, runs `launchctl load -w`, and the daemon starts at every login.

## Daemon management

| Command | Purpose |
|---------|---------|
| `launchctl list \| grep slack-alerts` | Status |
| `launchctl unload ~/Library/LaunchAgents/xyz.aaronstevens.slack-alerts.plist` | Stop |
| `bash ~/.claude/skills/0-slack-alerts/install-daemon.sh` | (Re)load |
| `tail -f ~/.config/slack-alerts/daemon.log` | Logs |

## Quick Start

**"start slack agent"** / **"turn on slack"**:
```bash
bash ~/.claude/skills/0-slack-alerts/scripts/agent.sh start "Descriptive title based on what the session is doing"
```

`agent.sh start` ensures the daemon is loaded (idempotent). If you have never run `install-daemon.sh`, it is called automatically on first start.

**Thread naming**: Use a descriptive title based on the session focus, e.g. "Building reporting dashboard", "Migrating to React", "Debugging CI failures". NOT generic titles like "Claude Code session" or "New session". The title becomes the parent message in Slack and helps Aaron find the right thread when multiple sessions are running.

**"stop slack agent"** / **"turn off slack"**:
```bash
bash ~/.claude/skills/0-slack-alerts/scripts/agent.sh stop
```

Stop touches a `session.ended` marker that the daemon respects on its next poll cycle. The daemon itself keeps running, ready for the next session.

## Handling Messages

There is no listener task. Instead, poll the queue at the start of each turn via the optional UserPromptSubmit hook (recommended), or by calling `inbox.py check` explicitly.

1. `python3 inbox.py check` reads new messages from the local queue.
2. `python3 inbox.py reply "response"` posts to Slack and advances the consume cursor.

The reply automatically advances the cursor past every message currently in the queue, so "one reply addresses everything" still works exactly like before.

## Files in $STATE_DIR

- `thread.json`: Active Slack thread metadata.
- `inbox-queue.jsonl`: Append-only queue. Daemon writes; `inbox.py check` reads.
- `daemon_cursor.json`: Daemon high-water mark of Slack ts already written to queue.
- `cursor.json`: Consume cursor. Highest queue ts the agent has acknowledged.
- `session.ended`: Marker file. Daemon skips this session when present.
- `caffeinate.pid`: PID of the keep-Mac-awake process for this session.
- `heartbeat.pid`: PID of the optional status poster.

## Commands

| Command | Purpose |
|---------|---------|
| `agent.sh start <title>` | Ensure daemon loaded, create thread, start caffeinate |
| `agent.sh stop` | Mark session.ended, kill caffeinate, post `_Session ended._` |
| `agent.sh status [text]` | Set or read the heartbeat status line |
| `alert.py start <title>` | Create thread (used internally by agent.sh start) |
| `alert.py post <msg>` | Post update (robot prefix + divider) |
| `alert.py alert <msg>` | Post with @mention + push notification |
| `alert.py ack` | Post `:loading_:` typing indicator |
| `alert.py end` | Post `_Session ended._` |
| `alert.py image <path> [caption]` | Upload screenshot/image to thread |
| `inbox.py check` | Read new messages from local queue + recent Slack context |
| `inbox.py reply <msg>` | Reply, advance queue consume cursor |
| `inbox.py health` | Report daemon_alive, queue_unread, thread_ts |
| `listener.sh` | DEPRECATED stub (silent no-op) |
| `healthcheck.sh` | DEPRECATED stub (silent no-op) |

## Reliability

The new model is structurally bulletproof against the old failure modes:

1. **No harness lifecycle.** The daemon is owned by launchd. Claude Code starting, stopping, restarting, dispatching subagents, or being idle has zero effect.
2. **KeepAlive.** If the daemon crashes, launchd relaunches it within `ThrottleInterval` seconds (10s in the plist).
3. **No respawn warnings.** The "Listener died" channel noise is gone. The daemon does not die in normal operation, and even if it does, launchd recovers silently.
4. **Per-session queues.** Each Claude Code session has its own state dir and queue file. Cross-session bleed is structurally impossible.
5. **Session prefix.** Every bot post still includes the `[abc123] ` prefix so Aaron can visually disambiguate concurrent sessions in the channel.

First debug step if you suspect a problem: `python3 inbox.py health`. Returns `daemon_alive`, `daemon_pid`, `queue_unread`, `thread_ts`, etc.

## Message Format

- **Bot messages**: Start with `[abc123] :robot_face:`, end with `─ ─ ─` divider
- **Ack**: `:loading_:` (shown while processing)
- **Session header**: `[abc123] :robot_face:  **Title**` (parent message only)
- **Session end**: `_Session ended._`
- **@mention**: Only in alerts or when Aaron needs to see it in activity
- **Images**: `alert.py image /path/to/screenshot.png "Caption here"`

## Status Update Style

```
✓ completed items
→ what is happening next
⏳ waiting on something
⚠️ errors or blockers
💬 prompting for input
```

## Long-Running Tasks

For bigger jobs (builds, extractions, CI monitoring), use `run.sh` to wrap the command. It auto-posts start/done/failed to Slack:

```bash
bash ~/.claude/skills/0-slack-alerts/scripts/run.sh "Extracting tarball" tar xzf ~/Downloads/big-file.tar.gz -C ~/
```

For tasks with multiple steps, just use `alert.py post` at milestones.

## Multi-Session

Multiple Claude Code sessions run simultaneously. Each gets its own thread and state dir (`~/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/`). The daemon polls every active session each cycle. `agent.sh stop` only marks that session `session.ended`; other sessions keep getting polled.

## Conversation Context

`inbox.py check` still fetches `recent_context` (the last 5 thread messages, both human and bot) from Slack so responses feel conversational. This is the only Slack round-trip on the read path.

## Optional: UserPromptSubmit safety net

`scripts/check-unread-hook.sh` is a belt-and-suspenders UserPromptSubmit hook. If the agent ever skips a queue check, the next user prompt triggers this hook, which reads the queue and surfaces a system reminder before the turn runs. To enable, add to `~/.claude/settings.json`:

```json
"hooks": {
  "UserPromptSubmit": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash ~/.claude/skills/0-slack-alerts/scripts/check-unread-hook.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

The hook is silent when no Slack session is active and times out gracefully if the queue read is slow.

## Technical Details

- **Channel**: `#agent-aaron` (C0AP4PD0ENN) on Block workspace (T05HJ0CKWG5)
- **User ID**: U03U7J0DG9Z
- **Identity**: Posts as Goose bot (bot_id: B0AKFE545AL) via xoxp token
- **Detection**: Aaron messages have no `bot_id`; bot messages have `bot_id` set OR start with `:robot_face:`/`:loading_:`
- **Caffeinate**: Prevents Mac sleep while a session is active
- **State**: `~/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/`
- **Daemon**: `~/Library/LaunchAgents/xyz.aaronstevens.slack-alerts.plist`
