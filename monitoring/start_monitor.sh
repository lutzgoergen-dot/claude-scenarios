#!/bin/bash
# Runs the ISDA check every 15 minutes in the background.
# Writes a PID file so you can stop it later with: kill $(cat monitoring/monitor.pid)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/isda_alerts.log"
ALL="$SCRIPT_DIR/isda_all.log"
PID_FILE="$SCRIPT_DIR/monitor.pid"
CHECK_SCRIPT="$SCRIPT_DIR/check_isda_cron.sh"
INTERVAL_SECONDS=900  # 15 minutes

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Monitor already running (PID $(cat "$PID_FILE")). Stop it first with:"
    echo "  kill \$(cat monitoring/monitor.pid)"
    exit 1
fi

nohup bash -c "
    echo \$\$ > '$PID_FILE'
    echo '[$(date -u '+%Y-%m-%d %H:%M UTC')] Monitor started (interval: ${INTERVAL_SECONDS}s)' >> '$ALL'
    while true; do
        bash '$CHECK_SCRIPT'
        sleep '$INTERVAL_SECONDS'
    done
" >> "$ALL" 2>&1 &

# Wait briefly for the subshell to write its own PID
sleep 0.2
PID=$(cat "$PID_FILE")
echo "Monitor started (PID $PID). Checking every 15 minutes."
echo "  Alerts:   $LOG"
echo "  Full log: $ALL"
echo "  Stop with: kill \$(cat monitoring/monitor.pid)"
