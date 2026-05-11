#!/bin/bash
# UserPromptSubmit hook: surface unread Slack messages at the top of every turn.
#
# Behavior:
#   1. If no Slack session is active for the current CLAUDE_CODE_SESSION_ID,
#      exit 0 silently. The hook is opt-in per session via "start slack agent".
#   2. Otherwise, bridge CLAUDE_CODE_SESSION_ID into CLAUDE_SESSION_ID (the
#      skill's scripts read the latter), call inbox.py check with a short
#      timeout, and parse the JSON.
#   3. If new_messages > 0, print a system reminder so the harness surfaces
#      it to Claude before the next prompt is processed.
#   4. If inbox.py is slow (> ~3s), emit a brief warning instead of blocking.
#
# Exit code is always 0; this hook never fails a turn.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_ID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"

# No session id, nothing to bridge. Stay silent.
if [ -z "$SESSION_ID" ]; then
  exit 0
fi

STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"

# No Slack session active for this Claude session. Stay silent.
if [ ! -d "$STATE_DIR" ]; then
  exit 0
fi
if [ ! -s "$STATE_DIR/thread.json" ]; then
  exit 0
fi

export CLAUDE_SESSION_ID="$SESSION_ID"

# Run inbox.py check with a hard cap so a slow Slack API call never blocks
# the user's prompt. macOS lacks GNU `timeout`, so use a portable shim.
run_with_timeout() {
  local secs="$1"
  shift
  ( "$@" ) &
  local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null ) &
  local watcher=$!
  wait "$pid" 2>/dev/null
  local rc=$?
  kill "$watcher" 2>/dev/null
  return $rc
}

RESULT="$(run_with_timeout 3 python3 "$SCRIPT_DIR/inbox.py" check 2>/dev/null)"
RC=$?

if [ $RC -ne 0 ] || [ -z "$RESULT" ]; then
  # Slow or failed; emit a soft warning instead of blocking.
  echo "Warning: Slack unread check timed out or failed. Run 'python3 $SCRIPT_DIR/inbox.py check' manually if you're expecting messages."
  exit 0
fi

COUNT="$(printf '%s' "$RESULT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    print(d.get('new_messages', 0))
except Exception:
    print(0)
" 2>/dev/null)"

if [ -z "$COUNT" ] || [ "$COUNT" = "0" ]; then
  exit 0
fi

cat <<EOF
WARNING: $COUNT unread Slack message(s) in your agent channel. Read with 'python3 $SCRIPT_DIR/inbox.py check', reply with 'python3 $SCRIPT_DIR/inbox.py reply "..."', and confirm a fresh listener is running. Do not start other work until handled.
EOF

exit 0
