#!/bin/bash
# DEPRECATED (2026-05-10).
#
# The harness-owned listener has been replaced by a launchd-owned daemon.
# See scripts/daemon.py and LaunchAgents/xyz.aaronstevens.slack-alerts.plist.
#
# This stub exists for back-compat with any caller that still invokes
# listener.sh (older agent.sh logic, manual respawn habits, etc.). It is a
# silent no-op so it doesn't break those callers, but it does NOT spawn a
# polling process.
#
# To install or restart the daemon:
#   bash ~/.claude/skills/0-slack-alerts/install-daemon.sh
#
# To check daemon status:
#   launchctl list | grep slack-alerts
#   tail -f ~/.config/slack-alerts/daemon.log

exit 0
