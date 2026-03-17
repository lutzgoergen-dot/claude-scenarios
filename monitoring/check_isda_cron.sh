#!/bin/bash
# Wrapper for cron — runs the ISDA check and appends interesting findings to the alert log.

LOG=/home/user/claude-scenarios/monitoring/isda_alerts.log
ALL=/home/user/claude-scenarios/monitoring/isda_all.log
PYTHON=$(which python3 || which python)
SCRIPT=/home/user/claude-scenarios/monitoring/check_isda.py

TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
OUTPUT=$("$PYTHON" "$SCRIPT" 2>&1)

# Always append to the full log
echo "[$TIMESTAMP] $OUTPUT" >> "$ALL"

# Only append to alert log if new submissions found
if echo "$OUTPUT" | grep -q "NEW ISDA DC SUBMISSION"; then
    echo "" >> "$LOG"
    echo "========================================" >> "$LOG"
    echo "[$TIMESTAMP] *** ALERT ***" >> "$LOG"
    echo "$OUTPUT" >> "$LOG"
    echo "========================================" >> "$LOG"
fi
