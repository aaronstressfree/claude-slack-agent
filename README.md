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

## Listener auto-respawn

The most common way Claude goes silent in long Slack sessions is forgetting to restart `listener.sh` after replying. Two layers prevent that now:

1. **Auto-respawn on reply.** `python3 scripts/inbox.py reply "..."` spawns a fresh background `listener.sh` as part of the reply, so a new listener is always waiting for the next message. The response JSON includes `listener_respawned: true`. Pass `--no-respawn` if you're shutting down.
2. **Auto-spawn on start.** `bash scripts/agent.sh start` now spawns the listener for you. You no longer need a separate `bash scripts/listener.sh` call right after start (though it stays safe as a no-op).

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
