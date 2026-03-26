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
