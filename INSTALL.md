# Slack Agent Onboarding

You are setting up the Claude Slack Agent. Follow this conversational onboarding flow step by step. Be friendly and clear at each step. Do not skip steps.

## Step 1: Introduction

Say to the user:

> I'm going to set up a Slack agent so you can chat with me from Slack. Let me check a few things...

## Step 2: Check for Slack credentials

Check if `~/.config/slack-skill/credentials.json` exists:

```bash
cat ~/.config/slack-skill/credentials.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'ok':True,'has_token':bool(d.get('token'))}))" 2>/dev/null || echo '{"ok":false}'
```

- If credentials exist and have a token, say: "Found your Slack credentials. Let me verify they work..."
- If credentials are missing, guide the user:
  > I don't see Slack credentials yet. You'll need to authenticate with Slack first.
  >
  > If you have the `slack-alerts` skill installed, say "authenticate with slack" and I'll handle it.
  > Otherwise, you'll need to set up credentials at `~/.config/slack-skill/credentials.json` with a valid Slack bot token.
  >
  > Come back and say "set up slack agent" once you have credentials.

  Then stop here.

## Step 3: Detect user info

Run the detect command to get the user's Slack identity:

```bash
python3 ~/.claude/skills/slack-agent/scripts/config.py detect
```

Tell the user what you found: their username and workspace.

## Step 4: Ask about channel name

Ask the user:

> What would you like to name your agent channel? I'd suggest **agent-{username}** as a private channel, but you can pick any name.

Wait for their response. Use their choice, or the default if they say something like "that's fine" or "default".

## Step 5: Ask about channel visibility

Ask the user:

> Do you want this to be a **private** channel (recommended) or **public**? Private means only you and people you invite can see it.

Wait for their response. Default to private if they seem unsure.

## Step 6: Ask about creating vs. using existing

Ask the user:

> Do you want me to **create** the channel, or do you already have one you'd like to use?

- If they want to create: proceed to Step 7.
- If they have an existing channel: ask for the channel name, then run setup with that name so it finds the existing channel.

## Step 7: Run setup

Run the setup command with their choices. For example, for a private channel named "agent-aaron":

```bash
python3 ~/.claude/skills/slack-agent/scripts/config.py setup --channel agent-aaron
```

For a public channel:

```bash
python3 ~/.claude/skills/slack-agent/scripts/config.py setup --channel agent-aaron --public
```

If setup succeeds, continue. If it fails, help the user troubleshoot.

## Step 8: Explain how it works

Tell the user:

> All set! Here's how the Slack agent works:
>
> - Say **"start slack agent"** at the beginning of any Claude Code session to connect
> - Say **"stop slack agent"** when you're done
> - Reply in the Slack thread to send me instructions
> - I'll show :loading: when I'm processing and a robot emoji on my replies
>
> You can start and stop the agent in any session -- each one gets its own thread in your channel.

## Step 9: Offer to start now

Ask the user:

> Want me to start the agent right now for a quick test?

- If yes: run `bash ~/.claude/skills/slack-agent/scripts/agent.sh start "Test session"` and start the listener with `bash ~/.claude/skills/slack-agent/scripts/listener.sh` (run_in_background: true). Tell them to check Slack for the new thread.
- If no: say "No problem! Just say 'start slack agent' whenever you're ready."
