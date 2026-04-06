#!/bin/bash
# Polls for new Slack messages. Acks immediately, then exits to notify Claude.
# Run with run_in_background:true. Restart after handling each message.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Write PID to session-scoped file so agent.sh can kill us reliably
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -n "$SESSION_ID" ]; then
  STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
else
  STATE_DIR="$HOME/.config/slack-alerts"
fi
mkdir -p "$STATE_DIR"
echo $$ > "$STATE_DIR/listener.pid"
trap 'rm -f "$STATE_DIR/listener.pid"' EXIT

LOGFILE="$STATE_DIR/listener.log"

while true; do
  result=$(python3 "$SCRIPTS_DIR/inbox.py" check --advance 2>>"$LOGFILE")
  if [ $? -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: inbox.py check failed (exit $?)" >> "$LOGFILE"
    sleep 5
    continue
  fi

  count=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('new_messages',0))" 2>>"$LOGFILE" || echo "0")
  if [ $? -ne 0 ] || [ -z "$count" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: failed to parse message count" >> "$LOGFILE"
    count="0"
  fi

  if [ "${count:-0}" -gt 0 ] 2>>"$LOGFILE"; then
    python3 "$SCRIPTS_DIR/alert.py" ack 2>>"$LOGFILE"
    echo "$result"
    exit 0
  fi
  sleep 5
done
