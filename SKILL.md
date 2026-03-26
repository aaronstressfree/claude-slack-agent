---
name: claude-slack-agent
description: "Two-way Slack agent for chatting via a dedicated private #agent-{username} channel. Say 'start slack agent' to begin, 'stop slack agent' to end. Say 'set up slack agent', 'install slack agent', or 'configure slack agent' to run the conversational onboarding flow. Supports multiple concurrent sessions, image uploads, and conversation context."
allowed-tools:
  - Bash(*/slack-agent/scripts/agent.sh:*)
  - Bash(*/slack-agent/scripts/listener.sh:*)
  - Bash(python3 */slack-agent/scripts/alert.py:*)
  - Bash(python3 */slack-agent/scripts/inbox.py:*)
  - Bash(python3 */slack-agent/scripts/config.py:*)
metadata:
  author: claude
  version: "1.1"
  status: stable
---

# Slack Agent

Two-way Slack chat via a dedicated private `#agent-{username}` channel.

## Setup / Installation

When the user says **"set up slack agent"**, **"install slack agent"**, or **"configure slack agent"**:

1. Read the file `INSTALL.md` in this skill's directory
2. Follow the conversational onboarding flow described there step by step
3. Walk the user through credential checks, channel naming, and configuration

## Thread Naming

When starting a session, use a descriptive title based on what the session is doing -- e.g. 'Building reporting dashboard', 'Debugging CI failures'. NOT generic titles like 'Claude Code session'.

## Quick Start

**"start slack agent"** / **"turn on slack"**:
```bash
bash scripts/agent.sh start "Brief description"
bash scripts/listener.sh  # run_in_background: true
```

**"stop slack agent"** / **"turn off slack"**:
```bash
bash scripts/agent.sh stop
```

On first start, if `~/.config/claude-slack-agent/config.json` does not exist, `agent.sh` automatically runs `config.py setup` to detect your Slack identity, find or create your private agent channel, and save config. No manual setup needed beyond having Slack credentials at `~/.config/slack-skill/credentials.json`.

## Handling Messages

When the listener exits (task notification), always do these 3 steps:

1. `cat <output_file>` -- read the user's message
2. `python3 inbox.py reply "response"` -- respond (advances cursor)
3. `bash listener.sh` -- restart (run_in_background: true)

If multiple messages came in fast, `check` returns all of them. Reply addresses everything, then restart.

## Commands

| Command | Purpose |
|---------|---------|
| `agent.sh start <title>` | Create thread + start caffeinate |
| `agent.sh stop` | End session + kill caffeinate |
| `listener.sh` | Background poll, exits on message |
| `alert.py start <title>` | Create thread |
| `alert.py post <msg>` | Post update (robot prefix + divider) |
| `alert.py alert <msg>` | Post with @mention + push notification |
| `alert.py ack` | Post `:loading_:` typing indicator |
| `alert.py end` | Post `_Session ended._` |
| `alert.py image <path> [caption]` | Upload screenshot/image to thread |
| `run.sh <desc> <cmd> [args]` | Run command, auto-post start/done/failed |
| `inbox.py check` | Check for messages + recent context |
| `inbox.py reply <msg>` | Reply (robot prefix + divider) + advance cursor |
| `config.py setup` | Interactive onboarding (detect user, find/create channel) |
| `config.py show` | Display current config |

## Message Format

- **Bot messages**: Start with :robot_face:, end with `--- --- ---` divider
- **Ack**: `:loading_:` (shown while processing)
- **Session header**: `:robot_face:  **Title**` (parent message only)
- **Session end**: `_Session ended._`
- **@mention**: Only in alerts or when the user needs to see it in activity
- **Images**: `alert.py image /path/to/screenshot.png "Caption here"`

## Status Update Style

```
checkmark completed items
arrow what's happening next
hourglass waiting on something
warning errors or blockers
speech prompting for input
```

## Long-Running Tasks

For bigger jobs (builds, extractions, CI monitoring), use `run.sh` to wrap the command. It auto-posts start/done/failed to Slack:

```bash
bash scripts/run.sh "Extracting tarball" tar xzf ~/Downloads/big-file.tar.gz -C ~/
# ^ run_in_background: true
```

For tasks with multiple steps, just use `alert.py post` at milestones:
```bash
python3 alert.py post "checkmark Step 1 done, starting step 2"
```

Use judgment -- small quick tasks don't need progress updates. Bigger jobs that take more than ~30 seconds should post something so the user knows what's happening.

## Multi-Session

Multiple Claude Code sessions can run simultaneously. Each gets its own thread and state dir (`~/.config/claude-slack-agent/sessions/<CLAUDE_SESSION_ID>/`). `agent.sh stop` only kills that session's listener.

## Conversation Context

`inbox.py check` and `inbox.py reply` include `recent_context` -- the last 5 thread messages (both human and bot) -- so responses feel conversational without re-reading the full thread.

## Technical Details

- **Config**: `~/.config/claude-slack-agent/config.json` (auto-generated on first run)
- **Identity**: Posts via the token in your Slack credentials
- **Detection**: User messages have no `bot_id`; bot messages have `bot_id` set
- **Caffeinate**: Prevents Mac sleep while agent is on
- **State**: `~/.config/claude-slack-agent/` (or per-session under `sessions/`)
