#!/bin/bash
# Cron wrapper — runs the TfL Bakerloo check and logs alerts only when issues found.
# Scheduled to run at 07:00 and 17:00 UTC (= London GMT; adjust for BST if needed).

LOG=/home/user/claude-scenarios/monitoring/tfl_alerts.log
ALL=/home/user/claude-scenarios/monitoring/tfl_all.log
PYTHON=$(which python3 || which python)
SCRIPT=/home/user/claude-scenarios/monitoring/check_tfl.py

TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
OUTPUT=$("$PYTHON" "$SCRIPT" 2>&1)

# Always append to full log
echo "[$TIMESTAMP] $OUTPUT" >> "$ALL"

# Only append to alert log if disruption found
if echo "$OUTPUT" | grep -q "BAKERLOO LINE DISRUPTION DETECTED"; then
    {
        echo ""
        echo "========================================"
        echo "[$TIMESTAMP] *** ALERT ***"
        echo "$OUTPUT"
        echo "========================================"
    } >> "$LOG"
fi
