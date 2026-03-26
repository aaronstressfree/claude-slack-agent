# Claude Slack Agent

A Claude Code skill that gives Claude a persistent two-way Slack channel for communication. When active, Claude posts status updates and receives instructions through a dedicated private `#agent-{username}` channel in your Slack workspace.

## Requirements

- Slack credentials at `~/.config/slack-skill/credentials.json` (obtained via the [slack skill](https://github.com/anthropics/claude-code-skills) auth flow)
- macOS (uses `caffeinate` to prevent sleep)
- Python 3

## Installation

Copy this skill into your Claude Code skills directory, then say "set up slack agent" in Claude Code. Claude will walk you through the rest.

```bash
# Option A: copy
cp -r ~/Development/claude-slack-agent ~/.claude/skills/slack-agent

# Option B: via git
git clone <repo-url> ~/.claude/skills/slack-agent
```

Then in Claude Code, just say:

> set up slack agent

Claude will guide you through a conversational setup -- checking credentials, picking a channel name, creating the channel, and configuring everything.

## Usage

- **"start slack agent"** -- Creates a thread in your agent channel and begins listening for messages
- **"stop slack agent"** -- Ends the session and stops listening
- Reply in the Slack thread to send instructions to Claude
- Claude shows :loading: when processing and a robot emoji on replies

## Config

View current config:

```bash
python3 scripts/config.py show
```

Config is stored at `~/.config/claude-slack-agent/config.json` and contains your user ID, channel ID, workspace ID, and credentials path. No secrets are stored in the config itself.
