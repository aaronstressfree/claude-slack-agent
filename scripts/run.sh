#!/bin/bash
# Run a command and post its result to Slack when done.
# Usage: run.sh "description" command [args...]
#
# Posts a start message, runs the command, posts success/failure.
# Use for long-running tasks that Claude kicks off in the background.

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
DESC="$1"
shift

# Post start
python3 "$SCRIPTS_DIR/alert.py" post "⏳ Starting: $DESC" 2>/dev/null

# Run the command
OUTPUT=$("$@" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  python3 "$SCRIPTS_DIR/alert.py" post "✓ Done: $DESC" 2>/dev/null
else
  python3 "$SCRIPTS_DIR/alert.py" post "⚠️ Failed: $DESC (exit $EXIT_CODE)
\`\`\`
$(echo "$OUTPUT" | tail -5)
\`\`\`" 2>/dev/null
fi

# Output the result for Claude
echo "$OUTPUT"
exit $EXIT_CODE
