# Claude Slack Agent

Chat with Claude from Slack. Each Claude Code session creates a thread in a private Slack channel. You send messages in the thread, Claude responds. It is like texting your AI.

## How it works

When you are working in Claude Code and want to stay in touch without staring at the terminal:

1. **Say "start slack agent"** at the beginning of a session. Claude creates a new thread in your private Slack channel.
2. **Reply in the thread** to send instructions, ask questions, or redirect Claude mid-task.
3. **Claude shows you what is happening.** A `:loading_:` spinner means it is reading your message, a robot emoji marks its replies, and a `─ ─ ─` divider separates each response so the thread stays easy to scan.
4. **Say "stop slack agent"** when you are done. It closes the thread and frees things up.

You can run multiple Claude Code sessions at the same time. Each one gets its own thread, so nothing crosses wires.

While the agent is running, it keeps your Mac awake so polling does not get interrupted.

## Architecture

The polling listener runs as a **foreground child of the Claude Code harness**, not a detached daemon. This is the load-bearing detail: the harness fires a "task completed" notification to the agent only when a child process spawned via `Bash run_in_background:true` exits. The agent reads that exit's stdout and uses it as the trigger for the next turn. A detached daemon (launchd, nohup, double-fork) writes to a file but the agent never sees the signal.

So the contract is:

1. `listener.sh` polls Slack on a 6-second loop.
2. On new messages, it posts a one-time-per-batch `:mag: Looking into it...` ack, prints the message JSON to stdout, and exits cleanly.
3. The harness fires the task-completed notification to the agent.
4. The agent reads stdout, calls `inbox.py reply "..."` to post a response, then explicitly restarts `listener.sh` via a fresh `Bash run_in_background:true` call.
5. A silent `healthcheck.sh` watchdog (also harness-owned) respawns the listener if it dies between cycles. The watchdog stays quiet on isolated failures and only posts a single `:warning:` after three consecutive respawn failures, so a normal harness reap creates no Slack noise.

```
claude code session (harness)
  ├─ agent.sh start "title"
  │    ├─ alert.py start "title"       (creates thread.json)
  │    ├─ caffeinate                   (keeps Mac awake)
  │    ├─ nohup listener.sh &          (spawns initial listener)
  │    └─ nohup healthcheck.sh &       (spawns silent watchdog)
  │
  ├─ listener.sh (run_in_background)
  │    └─ on new messages: ack once, print JSON, exit 0
  │
  ├─ agent reads stdout, calls inbox.py reply "..."
  ├─ agent restarts listener.sh via fresh Bash run_in_background
  │
  └─ agent.sh stop
       ├─ kill listener, healthcheck, heartbeat, caffeinate
       └─ alert.py end                 (posts _Session ended._)
```

### Why not launchd

We tried. Twice. Both times the agent stopped seeing inbound messages because the harness only fires task notifications on child-process exits, and a launchd-owned process is not a child of the harness. The messages landed in a queue file but the agent had no signal to read it. See the deprecated headers in `scripts/daemon.py` and the LaunchAgents plist for the full history.

The watchdog covers the only failure case the daemon was trying to address: the harness reaps idle background tasks every 2 to 3 minutes with exit 144. The watchdog notices, silently respawns, and the user never sees it.

### Invariants

- **One listener per session.** `listener.sh` claims `$STATE_DIR/listener.pid` on startup. A second invocation while one is alive exits silently (rc 0). Spam-calling 100 times produces exactly one process.
- **One-time-per-batch ack.** `listener.sh` only posts `:mag: Looking into it...` when the highest message ts in the current batch is newer than `$STATE_DIR/last_acked_ts`. A respawned listener finding the same queued messages does not re-ack.
- **Strict session isolation.** Every script requires `CLAUDE_SESSION_ID` and refuses to operate on global state. Each session has its own `~/.config/slack-alerts/sessions/<id>/` dir with its own thread, cursor, queue, and PID files.
- **Session prefix in posts.** Every bot message starts with `[abc123] ` (the first 6 chars of the session ID) so multiple concurrent sessions are visually distinguishable in the channel.

## Prerequisites

You will need the Block Slack skill installed (`sq agents skills add slack`) or equivalent Slack credentials at `~/.config/slack-skill/credentials.json`. The setup flow checks for this and guides you if it is missing.

## Install

Open Claude Code and paste this one line:

```
curl -sL https://raw.githubusercontent.com/aaronstressfree/claude-slack-agent/main/install.sh | bash
```

That is the whole install. There is no launchd daemon to set up.

## What happens after install

Open Claude Code and say **"set up slack agent"**. Claude walks you through everything in a friendly conversation:

- It detects your Slack identity automatically
- You pick a channel name (it suggests one)
- It creates a private channel for you
- It tests the connection

No config files to edit. No environment variables. Just a conversation.

## Day-to-day usage

| Say this in Claude Code | What happens |
|---|---|
| **start slack agent** | Creates a thread, spawns listener and watchdog, starts caffeinate |
| **stop slack agent** | Kills child processes, posts `_Session ended._`, clears PID files |

That is the whole interface. Two phrases.

**Important:** The agent does not auto-start a session. Every time you open Claude Code and want Slack access, say "start slack agent". When you are done, say "stop slack agent" to keep things clean.

## Debugging

First step when you suspect silence:

```bash
python3 ~/.claude/skills/claude-slack-agent/scripts/inbox.py health
```

Returns `listener_alive`, `listener_pid`, `thread_ts`, `session_id`, and `state_dir`. If `listener_alive` is `false`, restart the listener via `Bash run_in_background:true` (or just run `agent.sh start` again, which is idempotent).

Logs live at:

- `$STATE_DIR/listener.log` (listener output and errors)
- `$STATE_DIR/healthcheck.log` (watchdog activity)
- `$STATE_DIR/heartbeat.log` (optional status poster)

where `$STATE_DIR` is `~/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/`.

## Optional: UserPromptSubmit safety net

For a belt-and-suspenders guard against missed messages, register `scripts/check-unread-hook.sh` as a UserPromptSubmit hook in `~/.claude/settings.json`:

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

On every user prompt, the hook checks for unread messages and surfaces a warning to Claude before the turn runs so Claude reads and replies before doing anything else. The hook is silent when no Slack session is active and times out gracefully if the Slack API is slow.

## Files

| File | Purpose |
|---|---|
| `scripts/agent.sh` | Session lifecycle: `start <title>`, `stop`, `status [text]` |
| `scripts/listener.sh` | Foreground poll loop. Exits on new messages |
| `scripts/healthcheck.sh` | Silent watchdog. Respawns dead listeners |
| `scripts/inbox.py` | `check`, `reply`, `health` |
| `scripts/alert.py` | `start`, `post`, `alert`, `ack`, `end`, `image` |
| `scripts/heartbeat.sh` | Optional status-line poster |
| `scripts/check-unread-hook.sh` | Optional UserPromptSubmit safety net |
| `scripts/config.py` | Interactive setup and shared Slack API helper |
| `scripts/run.sh` | Wraps long commands with auto post/done/failed updates |
| `scripts/daemon.py` | **DEPRECATED.** Launchd architecture. Do not use |
| `LaunchAgents/*.plist` | **DEPRECATED.** Launchd plist. Do not load |
| `install-daemon.sh` | **DEPRECATED.** Launchd installer. Stubbed out |
