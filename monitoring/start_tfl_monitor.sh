#!/bin/bash
# Runs the TfL Bakerloo check at 07:00 and 17:00 UTC daily, in the background.
# Writes a PID file so you can stop it with: kill $(cat monitoring/tfl_monitor.pid)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/tfl_alerts.log"
ALL="$SCRIPT_DIR/tfl_all.log"
PID_FILE="$SCRIPT_DIR/tfl_monitor.pid"
CHECK_SCRIPT="$SCRIPT_DIR/check_tfl_cron.sh"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "TfL monitor already running (PID $(cat "$PID_FILE")). Stop it first with:"
    echo "  kill \$(cat monitoring/tfl_monitor.pid)"
    exit 1
fi

# Run times in UTC (HH:MM)
RUN_TIMES=("07:00" "17:00")

nohup bash -c "
    echo \$\$ > '$PID_FILE'
    echo '['\$(date -u '+%Y-%m-%d %H:%M UTC')'] TfL monitor started (runs at 07:00 and 17:00 UTC)' >> '$ALL'

    LAST_RUN_KEY=''

    while true; do
        NOW_HHMM=\$(date -u '+%H:%M')
        TODAY=\$(date -u '+%Y-%m-%d')
        RUN_KEY=\"\${TODAY}_\${NOW_HHMM}\"

        # Check if current time matches a scheduled run time
        for T in 07:00 17:00; do
            if [ \"\$NOW_HHMM\" = \"\$T\" ] && [ \"\$RUN_KEY\" != \"\$LAST_RUN_KEY\" ]; then
                LAST_RUN_KEY=\"\$RUN_KEY\"
                bash '$CHECK_SCRIPT'
                break
            fi
        done

        sleep 30
    done
" >> "$ALL" 2>&1 &

sleep 0.2
PID=$(cat "$PID_FILE")
echo "TfL Bakerloo monitor started (PID $PID)."
echo "  Checks at: 07:00 and 17:00 UTC daily"
echo "  Alerts:    $LOG"
echo "  Full log:  $ALL"
echo "  Stop with: kill \$(cat monitoring/tfl_monitor.pid)"
