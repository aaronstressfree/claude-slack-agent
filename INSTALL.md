# Slack Agent Onboarding

You are setting up the Claude Slack Agent. Follow this conversational onboarding flow step by step. Be warm, friendly, and jargon-free at every step -- the user may not be technical. Do not skip steps.

## Step 1: Say hello

Say to the user:

> Hey! I'm going to get you set up with a Slack channel where we can chat. It only takes a minute. Let me check a few things first...

## Step 2: Check for Slack credentials

Check if `~/.config/slack-skill/credentials.json` exists:

```bash
cat ~/.config/slack-skill/credentials.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'ok':True,'has_token':bool(d.get('token'))}))" 2>/dev/null || echo '{"ok":false}'
```

- If credentials exist and have a token, say: "Found your Slack connection. Let me make sure it's working..."
- If credentials are missing, say:
  > Looks like we need to connect to Slack first. No worries -- it's quick.
  >
  > If you already have the **slack-alerts** skill installed, just say **"authenticate with slack"** and I'll handle it.
  >
  > If not, we'll need to set up a Slack connection before we can continue. Let me know if you need help with that!
  >
  > Once you're connected, come back and say **"set up slack agent"** again.

  Then stop here.

## Step 3: Figure out who you are on Slack

Run the detect command to get the user's Slack identity:

```bash
python3 ~/.claude/skills/slack-agent/scripts/config.py detect
```

Tell the user what you found in plain language, like: "Looks like you're **@aaron** on the **Acme** workspace."

## Step 4: Pick a channel name

Ask the user:

> I'll create a private Slack channel just for us. How about **agent-{username}**? Or you can pick a different name -- totally up to you.

Wait for their response. Use their choice, or the default if they say something like "sounds good" or "that works".

## Step 5: Ask about channel visibility

Ask the user:

> Should this channel be **private** (only you can see it) or **public** (anyone in the workspace can see it)? Private is usually the way to go.

Wait for their response. Default to private if they seem unsure.

## Step 6: Create or reuse a channel

Ask the user:

> Want me to **create** a new channel, or do you already have one you'd like to use?

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

If setup succeeds, continue. If it fails, help the user troubleshoot in plain language.

## Step 8: Explain how it works

Tell the user:

> You're all set! Here's how it works:
>
> - Say **"start slack agent"** whenever you want to connect me to Slack
> - Say **"stop slack agent"** when you're done
> - Once I'm connected, just reply in the Slack thread to talk to me
>
> Each time you start a session, I'll create a new thread in your channel. Easy as that.

## Step 9: Offer to start now

Ask the user:

> Want to give it a spin right now? I can connect to Slack so you can see it in action.

- If yes: run `bash ~/.claude/skills/slack-agent/scripts/agent.sh start "Test session"` and start the listener with `bash ~/.claude/skills/slack-agent/scripts/listener.sh` (run_in_background: true). Tell them to check Slack for the new thread.
- If no: say "No worries! Just say 'start slack agent' whenever you're ready."
