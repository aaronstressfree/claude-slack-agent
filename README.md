# Claude Slack Agent

Chat with Claude from Slack. Each Claude Code session creates a thread in a private Slack channel. You send messages in the thread, Claude responds. It is like texting your AI.

## How it works

When you are working in Claude Code and want to stay in touch without staring at the terminal:

1. **Say "start slack agent"** at the beginning of a session. Claude creates a new thread in your private Slack channel.
2. **Reply in the thread** to send instructions, ask questions, or redirect Claude mid-task.
3. **Claude shows you what is happening.** A `:loading_:` spinner means it is reading your message, a robot emoji marks its replies, and a `--- --- ---` divider separates each response so the thread stays easy to scan.
4. **Say "stop slack agent"** when you are done. It closes the thread and frees things up.

You can run multiple Claude Code sessions at the same time. Each one gets its own thread, so nothing crosses wires.

While the agent is running, it keeps your Mac awake so polling does not get interrupted.

## Architecture (2026-05-10 rewrite)

The poll loop runs in a **launchd-owned daemon**, not in a Claude Code background task. This survives harness reaps, agent dispatches, idle periods, Mac sleep/wake, and reboots (relaunches at next login).

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

## Prerequisites

You will need the Block Slack skill installed (`sq agents skills add slack`). The setup will check for this and guide you if it is missing.

## Install

Open Claude Code and paste this one line:

```
curl -sL https://raw.githubusercontent.com/aaronstressfree/claude-slack-agent/main/install.sh | bash
```

Then install the launchd daemon (one time only):

```
bash ~/.claude/skills/0-slack-alerts/install-daemon.sh
```

The daemon now starts at every login automatically.

## Daemon management

| Command | Purpose |
|---------|---------|
| `launchctl list \| grep slack-alerts` | Status |
| `launchctl unload ~/Library/LaunchAgents/xyz.aaronstevens.slack-alerts.plist` | Stop |
| `bash ~/.claude/skills/0-slack-alerts/install-daemon.sh` | (Re)load |
| `tail -f ~/.config/slack-alerts/daemon.log` | Logs |

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
| **start slack agent** | Ensures daemon loaded, creates a thread, listens for replies |
| **stop slack agent** | Marks session ended, closes the thread |

That is the whole interface. Two phrases.

**Important:** The agent does not auto-start a session. Every time you open Claude Code and want Slack access, say "start slack agent". When you are done, say "stop slack agent" to keep things clean and let Claude know you are finished. The daemon itself stays loaded across all of this.

## Reliability

The new model is structurally bulletproof against the old failure modes:

1. **No harness lifecycle.** The daemon is owned by launchd. Claude Code starting, stopping, restarting, dispatching subagents, or being idle has zero effect.
2. **KeepAlive.** If the daemon crashes, launchd relaunches it within `ThrottleInterval` seconds (10s in the plist).
3. **No respawn warnings.** The old `:warning: Listener died` channel noise is gone. The daemon does not die in normal operation, and even if it does, launchd recovers silently.
4. **Per-session queues.** Each Claude Code session has its own state dir and queue file. Cross-session bleed is structurally impossible.
5. **Session prefix.** Every bot post includes a short `[abc123]` prefix so you can visually disambiguate concurrent sessions in the channel.

First debug step if you suspect a problem: `python3 ~/.claude/skills/0-slack-alerts/scripts/inbox.py health`. Returns `daemon_alive`, `daemon_pid`, `queue_unread`, `thread_ts`, etc.

## Optional: UserPromptSubmit safety net

For a belt-and-suspenders guard against missed messages, register `scripts/check-unread-hook.sh` as a UserPromptSubmit hook in `~/.claude/settings.json`:

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

On every user prompt, the hook reads the local queue file. If there are unread messages, it surfaces a warning to Claude before the turn runs so Claude reads and replies before doing anything else. The hook is silent when no Slack session is active and times out gracefully if the queue read is slow.
