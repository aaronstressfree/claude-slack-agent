#!/bin/bash
# Watchdog: every HEALTHCHECK_INTERVAL seconds (default 30s), verify that
# the session's listener is alive. If the PID file is missing or the PID is
# dead, respawn it SILENTLY. Only post a warning after N consecutive respawn
# attempts fail to bring a listener back, which indicates a real problem
# (Python crash, network outage), not a normal harness reap.
#
# Background: the harness reaps long-poll background tasks with exit 144
# every ~2-3 minutes of idle. That is normal. A loud "Listener died" post
# every cycle creates Slack noise that reads as "broken" when nothing is
# actually wrong. The new posture: respawn silently, alert only on a
# genuinely broken listener (3+ consecutive failed respawns).
#
# Run via run_in_background:true. Killed by `agent.sh stop`.

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-}"
INTERVAL="${HEALTHCHECK_INTERVAL:-30}"
FAILURE_THRESHOLD="${HEALTHCHECK_FAILURE_THRESHOLD:-3}"

if [ -z "$SESSION_ID" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: CLAUDE_SESSION_ID not set, healthcheck refusing to start" >&2
  exit 1
fi

STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

PID_FILE="$STATE_DIR/healthcheck.pid"
LISTENER_PID_FILE="$STATE_DIR/listener.pid"
LOGFILE="$STATE_DIR/healthcheck.log"
FAILURE_COUNTER="$STATE_DIR/respawn_failures"

# Session prefix for any user-facing warnings. First 6 chars of session ID.
SESSION_PREFIX="${SESSION_ID:0:6}"

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

# Reset failure counter on startup. Stale value from a previous run could
# misfire the warning on the very first cycle.
echo 0 > "$FAILURE_COUNTER"

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

read_failures() {
  if [ -f "$FAILURE_COUNTER" ]; then
    cat "$FAILURE_COUNTER" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

WARNED=0

while true; do
  sleep "$INTERVAL"

  if is_listener_alive; then
    # Reset counter and warning state. Happy path is silent.
    echo 0 > "$FAILURE_COUNTER"
    WARNED=0
    continue
  fi

  # Listener is down. Respawn silently.
  echo "$(date '+%Y-%m-%d %H:%M:%S') listener missing, respawning silently" >> "$LOGFILE"
  nohup bash "$SCRIPTS_DIR/listener.sh" >> "$STATE_DIR/listener.log" 2>&1 < /dev/null &
  disown 2>/dev/null || true

  # Give the spawn a moment, then check if it actually came up.
  sleep 1
  if is_listener_alive; then
    # Successful silent recovery. Reset counter.
    echo 0 > "$FAILURE_COUNTER"
    WARNED=0
    continue
  fi

  # Respawn failed. Bump the counter.
  failures=$(read_failures)
  failures=$((failures + 1))
  echo "$failures" > "$FAILURE_COUNTER"
  echo "$(date '+%Y-%m-%d %H:%M:%S') respawn attempt failed (consecutive=$failures)" >> "$LOGFILE"

  # Only warn once per outage, after threshold consecutive failures.
  if [ "$failures" -ge "$FAILURE_THRESHOLD" ] && [ "$WARNED" -eq 0 ]; then
    python3 "$SCRIPTS_DIR/alert.py" post ":warning: Listener died ${failures}x in a row, may be genuinely broken. Investigate." >>"$LOGFILE" 2>&1
    WARNED=1
  fi
done
