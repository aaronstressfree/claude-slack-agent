# Claude Slack Agent

Chat with Claude from Slack. Each Claude Code session creates a thread in a private Slack channel. You send messages in the thread, Claude responds. It's like texting your AI.

## How it works

When you're working in Claude Code and want to stay in touch without staring at the terminal:

1. **Say "start slack agent"** at the beginning of a session. Claude creates a new thread in your private Slack channel.
2. **Reply in the thread** to send instructions, ask questions, or redirect Claude mid-task.
3. **Claude shows you what's happening** -- a :loading_: spinner means it's reading your message, a robot emoji marks its replies, and a `--- --- ---` divider separates each response so the thread stays easy to scan.
4. **Say "stop slack agent"** when you're done. It closes the thread and frees things up.

You can run multiple Claude Code sessions at the same time -- each one gets its own thread, so nothing crosses wires.

While the agent is running, it keeps your Mac awake so polling doesn't get interrupted.

## Prerequisites

You'll need the Block Slack skill installed (`sq agents skills add slack`). The setup will check for this and guide you if it's missing.

## Install

Open Claude Code and paste this one line:

```
curl -sL https://raw.githubusercontent.com/aaronstressfree/claude-slack-agent/main/install.sh | bash
```

That's it. One line. Done.

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
| **start slack agent** | Creates a new thread in your Slack channel and starts listening |
| **stop slack agent** | Ends the session and closes the thread |

That's the whole interface. Two phrases.

**Important:** The agent does not auto-start. Every time you open Claude Code and want Slack access, say "start slack agent". When you're done, say "stop slack agent" -- it keeps things clean and lets Claude know you're finished.

## Reliability (one listener per session, period)

The bot is bulletproof against the historical failure modes (listener stacking, silent death, missed messages). Three independent layers make sure it stays alive:

1. **Single-listener invariant.** `listener.sh` claims a session-scoped PID file on startup. If a live listener already owns the slot, a new invocation exits silently. Spam-calling `listener.sh` 100 times results in exactly one running process. No more stacking.
2. **Auto-respawn on reply, with self-test.** `python3 scripts/inbox.py reply "..."` spawns a fresh listener and verifies via the PID file that a listener is actually alive afterward. The JSON output includes `listener_respawned` AND `listener_alive`, both grounded in real PID checks (no more blind `true`).
3. **Watchdog (healthcheck.sh).** Auto-starts with `agent.sh start`. Polls the listener PID every 30 seconds (override with `HEALTHCHECK_INTERVAL`). If the listener dies between replies, the watchdog respawns it **silently** by default. Only after 3 consecutive failed respawns (override with `HEALTHCHECK_FAILURE_THRESHOLD`) does the watchdog post a warning to the thread, indicating a genuinely broken listener.

## Why listeners restart so often

The harness reaps long-poll background tasks with exit 144 every ~2-3 minutes of idle. The listener treats this as normal: it self-respawns on natural batch-exit (before returning to the caller) and the watchdog catches anything that slips through. You will NOT see warnings for exit-144 reaps. Only a true broken listener (3+ consecutive respawn failures) posts to the channel.

## Session prefix in bot posts

Every bot post is prepended with a 6-character session prefix in brackets, e.g. `[0d24f7] :robot_face: ...`. This lets you disambiguate multiple concurrent sessions in the channel-level view, where the thread title isn't visible. The prefix is the first 6 characters of `CLAUDE_SESSION_ID`.

First debug step if you suspect the bot has gone silent: `python3 scripts/inbox.py health`. Returns listener_alive, listener_pid, thread_ts. Read-only and instant.

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

(Adjust the path to your install location.) On every user prompt, the hook checks for unread Slack messages in the current Claude session's thread. If there are unread messages, it surfaces a warning to Claude before the turn runs so Claude reads and replies before doing anything else. The hook is silent when no Slack session is active and times out gracefully if Slack is slow.
