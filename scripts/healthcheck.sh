#!/bin/bash
# DEPRECATED (2026-05-10).
#
# The harness-owned listener no longer exists, so a watchdog for it is moot.
# launchd's KeepAlive on xyz.aaronstevens.slack-alerts handles daemon
# restarts automatically.
#
# This stub exists for back-compat with any caller that still invokes
# healthcheck.sh. It is a silent no-op.

exit 0
