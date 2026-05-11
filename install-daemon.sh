#!/bin/bash
# DEPRECATED (2026-05-10). Do not run.
#
# See scripts/daemon.py and LaunchAgents/xyz.aaronstevens.slack-alerts.plist
# headers for rationale. Short version: the launchd-owned daemon does not
# fire the harness's task-completed notification, so the agent never sees
# inbound messages. The working architecture lives in scripts/listener.sh
# and scripts/healthcheck.sh, owned by the harness as run_in_background
# tasks. See README.md.
#
# This installer is kept for forensic value only. It exits without action.
echo "install-daemon.sh is deprecated. The launchd daemon architecture was reverted."
echo "Use 'bash scripts/agent.sh start \"...\"' to start the working listener model."
echo "See README.md for the canonical architecture."
exit 0
set -euo pipefail

LABEL="xyz.aaronstevens.slack-alerts"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="$SKILL_DIR/LaunchAgents/$LABEL.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$PLIST_TEMPLATE" ]; then
  echo "error: plist template not found at $PLIST_TEMPLATE" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/.config/slack-alerts"

# Rewrite HOME placeholder so the plist is portable.
sed "s|HOME_PLACEHOLDER|$HOME|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

# Unload first if already loaded (idempotent).
if launchctl list | grep -q "$LABEL"; then
  echo "unloading existing $LABEL..."
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load with -w so it's enabled at every login.
launchctl load -w "$PLIST_DEST"

# Verify it's running.
sleep 1
if launchctl list | grep -q "$LABEL"; then
  echo "ok: daemon loaded as $LABEL"
  echo "logs: tail -f $HOME/.config/slack-alerts/daemon.log"
  echo "stop: launchctl unload $PLIST_DEST"
else
  echo "error: daemon failed to load. Check $HOME/.config/slack-alerts/launchd.err" >&2
  exit 1
fi
