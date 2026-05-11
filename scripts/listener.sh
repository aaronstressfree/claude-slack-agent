#!/bin/bash
# Polls for new Slack messages. Exits when a message arrives.
# Outputs the message to stdout so Claude sees it in the task notification.
# Run with run_in_background:true.
#
# Single-listener invariant: at most one listener.sh runs per session at any
# time. If a live listener is already claiming the PID file, this instance
# exits silently (rc 0). This makes back-to-back invocations physically safe.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Session isolation: REQUIRE CLAUDE_SESSION_ID. Listening on a global cursor
# would let multiple sessions race for the same messages.
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -z "$SESSION_ID" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: CLAUDE_SESSION_ID not set, listener refusing to start" >&2
  exit 1
fi
STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

PIDFILE="$STATE_DIR/listener.pid"
LOGFILE="$STATE_DIR/listener.log"

# Single-listener guard: if an existing PID file points to a live listener
# process for this session, exit silently. The existing listener stays.
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    # Verify the live PID is actually a listener.sh, not a recycled PID for
    # some unrelated process. Match on the script path so we cannot collide
    # with another bash invocation.
    if ps -p "$OLD_PID" -o command= 2>/dev/null | grep -q "listener.sh"; then
      echo "$(date '+%Y-%m-%d %H:%M:%S') listener already running (pid $OLD_PID), exiting" >> "$LOGFILE"
      exit 0
    fi
  fi
  # Stale PID file (process died without cleanup). Remove and continue.
  rm -f "$PIDFILE"
fi

# Claim the slot. Atomic-ish: any racing listener will lose this write but
# its kill -0 check above prevents two from running concurrently in practice.
echo $$ > "$PIDFILE"
trap "rm -f '$PIDFILE'" EXIT

ERROR_COUNT=0
MAX_ERROR_BACKOFF=120  # cap at 2 minutes

while true; do
  result=$(python3 "$SCRIPTS_DIR/inbox.py" check 2>>"$LOGFILE")
  exit_code=$?
  if [ $exit_code -ne 0 ]; then
    ERROR_COUNT=$((ERROR_COUNT + 1))
    # Exponential backoff: 10, 20, 40, 80, 120, 120...
    backoff=$((10 * (2 ** (ERROR_COUNT - 1))))
    if [ $backoff -gt $MAX_ERROR_BACKOFF ]; then
      backoff=$MAX_ERROR_BACKOFF
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: inbox.py check failed (exit $exit_code), backoff ${backoff}s (attempt $ERROR_COUNT)" >> "$LOGFILE"
    sleep $backoff
    continue
  fi

  # Success, reset error counter.
  ERROR_COUNT=0

  count=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('new_messages',0))" 2>/dev/null)
  if [ $? -ne 0 ] || [ -z "$count" ]; then
    count="0"
  fi

  if [ "${count:-0}" -gt 0 ] 2>/dev/null; then
    # Auto-ack so Aaron sees we got the message
    python3 "$SCRIPTS_DIR/alert.py" ack 2>>"$LOGFILE"
    # Output to stdout, Claude sees this in the task notification
    echo "$result"
    exit 0
  fi
  sleep 6
done
