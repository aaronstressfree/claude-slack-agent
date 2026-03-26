# Claude Slack Agent

Talk to Claude from Slack. Once installed, Claude gets its own private Slack channel where you can send it instructions, and it sends you updates -- all without leaving Slack.

## How to install

Open Claude Code and paste this:

```
curl -sL https://raw.githubusercontent.com/aaronstressfree/claude-slack-agent/main/install.sh | bash
```

That's it. One line. Done.

## What happens next

After the install finishes, type **"set up slack agent"** in Claude Code.

Claude will walk you through everything:
- Connecting to your Slack workspace
- Creating a private channel for you
- Making sure everything works

No config files to edit. No terminal wizardry. Just a conversation.

## How to use

| Say this in Claude Code | What it does |
|---|---|
| **start slack agent** | Connects Claude to your Slack channel |
| **stop slack agent** | Disconnects until next time |

Once started, just reply in your Slack thread to talk to Claude.
