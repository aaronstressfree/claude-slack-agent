#!/bin/bash
# Polls for new Slack messages. Acks immediately, then exits to notify Claude.
# Run with run_in_background:true. Restart after handling each message.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

while true; do
  result=$(python3 "$SCRIPTS_DIR/inbox.py" check 2>/dev/null)
  count=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('new_messages',0))" 2>/dev/null)
  if [ "$count" -gt 0 ]; then
    python3 "$SCRIPTS_DIR/alert.py" ack 2>/dev/null
    echo "$result"
    exit 0
  fi
  sleep 5
done
