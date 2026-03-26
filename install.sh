#!/bin/bash
# Claude Slack Agent installer
# Downloads and installs the skill into ~/.claude/skills/slack-agent/

set -e

REPO="aaronstressfree/claude-slack-agent"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
DEST="$HOME/.claude/skills/slack-agent"

echo ""
echo "  Installing Claude Slack Agent..."
echo ""

# Create the skill directory
mkdir -p "${DEST}/scripts"

# Download top-level files
for file in SKILL.md INSTALL.md; do
  curl -sL "${BASE_URL}/${file}" -o "${DEST}/${file}"
done

# Download scripts
for file in agent.sh alert.py config.py inbox.py listener.sh run.sh; do
  curl -sL "${BASE_URL}/scripts/${file}" -o "${DEST}/scripts/${file}"
done

# Make scripts executable
chmod +x "${DEST}/scripts/"*

echo "  Done!"
echo ""
echo "  Next step: open Claude Code and say:"
echo ""
echo "    set up slack agent"
echo ""
echo "  Claude will walk you through the rest."
echo ""
