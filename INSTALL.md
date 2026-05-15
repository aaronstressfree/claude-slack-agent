# Slack Agent Onboarding

You are setting up the Claude Slack Agent. Follow this conversational onboarding flow step by step. Be warm, friendly, and jargon-free at every step (the user may not be technical). Do not skip steps.

## Step 1: Explain what's about to happen

Say to the user:

> Hey! I'm going to set up a private Slack channel where we can chat back and forth. You'll be able to send me messages from Slack and I'll respond right there.
>
> Here's what we'll do:
> 1. Check your Slack connection
> 2. Pick a channel name
> 3. Create the channel
> 4. Test it out
>
> The whole thing takes about a minute. Let's go!

## Step 2: Check for Slack credentials

This agent talks to Slack with a **raw user OAuth token** (`xoxp-...`) that it reads directly from disk and uses to call Slack's REST API. It does NOT route through gateway tools like `sq agent-tools slack` or other kgoose-mediated proxies, because those gateways generally don't expose Slack's file-upload endpoints (`files.getUploadURLExternal` / `files.completeUploadExternal`), and the agent posts screenshots routinely.

So before going further, the credentials file at `~/.config/slack-skill/credentials.json` needs to contain a token that satisfies both:
1. It is an `xoxp-...` user OAuth token (NOT a `xoxb-...` bot token, NOT a gateway handle).
2. The OAuth grant includes `files:write` alongside the read/write scopes the agent needs.

Check whether the file is already in place:

```bash
test -f ~/.config/slack-skill/credentials.json && echo "installed" || echo "missing"
```

- If the file exists, continue to Step 3.
- If the file is missing, walk the user through one of the three paths below in order of preference, then stop until they come back.

### Path A: existing internally-blessed raw token (recommended at enterprises)

Some orgs ship internal Slack tooling that has already done an OAuth flow against an admin-installed Slack app and dropped a raw `xoxp` token on the user's machine. At Block, the legacy `slack-skill` setup did this back in early 2026. If a path like that exists in the user's environment, that token is already approved for `files:write` and the user doesn't need to install anything new.

How to find out: ask the user whether their org has an internal "raw Slack token" mechanism, or check for a token at `~/.config/slack-skill/credentials.json` left behind by older tooling. If yes, this step is done.

### Path B: personal Slack app install (non-enterprise / no review process)

If the user can freely install Slack apps at api.slack.com:

> Create a Slack app at api.slack.com with these user-scoped OAuth scopes: `chat:write`, `channels:history`, `channels:read`, `groups:history`, `groups:read`, `im:history`, `im:write`, `users:read`, and `files:write`. Install it to your workspace, copy the user OAuth token (starts with `xoxp-`), and save it to `~/.config/slack-skill/credentials.json` as JSON: `{"token": "xoxp-..."}`. Then say **"set up slack agent"** again.

> Note: `files:write` is NOT optional. Without it the agent silently can't post screenshots, and the agent posts screenshots frequently. If the install fails or the user can't grant `files:write`, see Path C.

### Path C: enterprise with VENDSEC / app-review blocking custom installs

If a custom app install gets rejected (often by a security review listing `files:write` as "High Risk") AND no Path A token exists:

- The gateway-mediated routes some orgs offer (e.g. `sq agent-tools slack` over kgoose) WILL let you post and read messages, but will NOT support file uploads, because the gateway doesn't surface the `files.*` endpoints. Image posting will be broken.
- The remaining options are: (1) escalate the custom-app review to get `files:write` approved on a one-off basis, (2) get an admin to install a shared internal Slack app whose token you can borrow, or (3) accept text-only operation and disable the image-upload paths in `cmd_image`.

  Until one of those resolves, stop here and tell the user that file uploads will not work in their environment.

## Step 3: Verify the token works

Check `~/.config/slack-skill/credentials.json` has a valid token:

```bash
cat ~/.config/slack-skill/credentials.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'ok':True,'has_token':bool(d.get('token'))}))" 2>/dev/null || echo '{"ok":false}'
```

- If credentials exist and have a token, say: "Found your Slack connection. Let me make sure it's working..."
- If credentials are missing or malformed, point the user back to Step 2.

## Step 4: Figure out who you are on Slack

Run the detect command to get the user's Slack identity:

```bash
python3 ~/.claude/skills/claude-slack-agent/scripts/config.py detect
```

Tell the user what you found in plain language, like: "Looks like you're **@user** on the **Acme** workspace."

## Step 5: Pick a channel name

Ask the user:

> I'll create a private Slack channel just for us. How about **agent-{username}**? Or you can pick a different name (totally up to you).

Wait for their response. Use their choice, or the default if they say something like "sounds good" or "that works".

## Step 6: Ask about channel visibility

Ask the user:

> Should this channel be **private** (only you can see it) or **public** (anyone in the workspace can see it)? Private is usually the way to go.

Wait for their response. Default to private if they seem unsure.

## Step 7: Create or reuse a channel

Ask the user:

> Want me to **create** a new channel, or do you already have one you'd like to use?

- If they want to create: proceed to Step 8.
- If they have an existing channel: ask for the channel name, then run setup with that name so it finds the existing channel.

## Step 8: Run setup

Run the setup command with their choices. For example, for a private channel named "agent-username":

```bash
python3 ~/.claude/skills/claude-slack-agent/scripts/config.py setup --channel agent-username
```

For a public channel:

```bash
python3 ~/.claude/skills/claude-slack-agent/scripts/config.py setup --channel agent-username --public
```

If setup succeeds, continue. If it fails, help the user troubleshoot in plain language.

## Step 9: Explain how to use it going forward

This is important. Tell the user clearly:

> You're all set! Here's how to use your Slack agent from now on:
>
> **Every time you start Claude Code and want Slack access:**
> - Say **"start slack agent"** to create a new thread in your channel
> - Reply in the Slack thread to send me messages, ask questions, or give new instructions
> - Say **"stop slack agent"** when you're done
>
> **A few things to know:**
> - The agent does NOT auto-start. You need to say "start slack agent" each session.
> - Always say "stop slack agent" when you're finished. It's polite and keeps things clean.
> - You can run multiple Claude Code sessions at once. Each gets its own thread.
> - While the agent is running, I'll show a :loading_: spinner when I'm reading your message, and a robot emoji on my replies.

## Step 10: Offer to test it right now

Ask the user:

> Want to give it a spin right now? I can send a test message to your Slack channel so you can see it in action.

- If yes: run `bash ~/.claude/skills/claude-slack-agent/scripts/agent.sh start "Test session"` and start the listener with `bash ~/.claude/skills/claude-slack-agent/scripts/listener.sh` (run_in_background: true). Tell them to check Slack for the new thread, and try replying to it.
- If no: say "No worries! Just say 'start slack agent' whenever you're ready."
