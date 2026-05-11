#!/bin/bash
# Watchdog: every HEALTHCHECK_INTERVAL seconds (default 300, i.e. 5 minutes),
# verify that the session's listener is alive. If the PID file is missing or
# the PID is dead, post a single warning to the thread and restart listener.sh.
#
# This is silent in the happy path. No idle pings, no presence pongs. Aaron
# already has heartbeat.sh for "what I'm doing now" status updates; this
# script is purely a failure-recovery layer beneath that.
#
# Run via run_in_background:true. Killed by `agent.sh stop`.

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-}"
INTERVAL="${HEALTHCHECK_INTERVAL:-300}"

if [ -z "$SESSION_ID" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: CLAUDE_SESSION_ID not set, healthcheck refusing to start" >&2
  exit 1
fi

STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

PID_FILE="$STATE_DIR/healthcheck.pid"
LISTENER_PID_FILE="$STATE_DIR/listener.pid"
LOGFILE="$STATE_DIR/healthcheck.log"

# Single-instance guard. If a previous healthcheck is still alive, exit cleanly.
if [ -f "$PID_FILE" ]; then
  prev_pid=$(cat "$PID_FILE" 2>/dev/null)
  if [ -n "$prev_pid" ] && kill -0 "$prev_pid" 2>/dev/null; then
    if ps -p "$prev_pid" -o command= 2>/dev/null | grep -q "healthcheck.sh"; then
      echo "$(date '+%Y-%m-%d %H:%M:%S') healthcheck already running (pid $prev_pid), exiting" >> "$LOGFILE"
      exit 0
    fi
  fi
  rm -f "$PID_FILE"
fi
echo $$ > "$PID_FILE"
trap "rm -f '$PID_FILE'" EXIT

is_listener_alive() {
  if [ ! -f "$LISTENER_PID_FILE" ]; then
    return 1
  fi
  local pid
  pid=$(cat "$LISTENER_PID_FILE" 2>/dev/null)
  if [ -z "$pid" ]; then
    return 1
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  if ! ps -p "$pid" -o command= 2>/dev/null | grep -q "listener.sh"; then
    return 1
  fi
  return 0
}

# State machine: only post a warning when we transition healthy -> dead.
# Once we've reported a dead listener and restarted it, suppress further
# warnings until the listener comes back alive (avoids spam during a
# persistent outage).
LAST_STATE="alive"

while true; do
  sleep "$INTERVAL"
  if is_listener_alive; then
    if [ "$LAST_STATE" = "dead" ]; then
      echo "$(date '+%Y-%m-%d %H:%M:%S') listener recovered" >> "$LOGFILE"
    fi
    LAST_STATE="alive"
    continue
  fi

  # Listener is down. Restart it. Only warn on the first detection so we
  # don't flood the thread if the restart itself keeps failing.
  if [ "$LAST_STATE" = "alive" ]; then
    python3 "$SCRIPTS_DIR/alert.py" post ":warning: Listener died, restarting now." >>"$LOGFILE" 2>&1
    LAST_STATE="dead"
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S') listener missing, respawning" >> "$LOGFILE"
  nohup bash "$SCRIPTS_DIR/listener.sh" >> "$STATE_DIR/listener.log" 2>&1 < /dev/null &
  disown 2>/dev/null || true
done
