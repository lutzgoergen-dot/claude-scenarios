#!/bin/bash
# Runs the TfL Bakerloo check at 07:00 and 17:00 UTC daily, in the background.
# Writes a PID file so you can stop it with: kill $(cat monitoring/tfl_monitor.pid)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/tfl_alerts.log"
ALL="$SCRIPT_DIR/tfl_all.log"
HEARTBEAT="$SCRIPT_DIR/tfl_heartbeat.log"
PID_FILE="$SCRIPT_DIR/tfl_monitor.pid"
CHECK_SCRIPT="$SCRIPT_DIR/check_tfl_cron.sh"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "TfL monitor already running (PID $(cat "$PID_FILE")). Stop it first with:"
    echo "  kill \$(cat monitoring/tfl_monitor.pid)"
    exit 1
fi

# Run times in London time (HH:MM) — handles GMT and BST automatically
nohup bash -c "
    echo \$\$ > '$PID_FILE'
    echo '['\$(TZ=Europe/London date '+%Y-%m-%d %H:%M %Z')'] TfL monitor started (runs at 07:00 and 17:00 London time)' >> '$ALL'

    LAST_RUN_KEY=''
    LAST_HEARTBEAT_KEY=''

    while true; do
        NOW_HHMM=\$(TZ=Europe/London date '+%H:%M')
        TODAY=\$(TZ=Europe/London date '+%Y-%m-%d')
        RUN_KEY=\"\${TODAY}_\${NOW_HHMM}\"

        # Heartbeat every 30 minutes
        NOW_MM=\$(TZ=Europe/London date '+%M')
        HB_KEY=\"\${TODAY}_\${NOW_HHMM}\"
        if ( [ \"\$NOW_MM\" = '00' ] || [ \"\$NOW_MM\" = '30' ] ) && [ \"\$HB_KEY\" != \"\$LAST_HEARTBEAT_KEY\" ]; then
            LAST_HEARTBEAT_KEY=\"\$HB_KEY\"
            echo \"\$(TZ=Europe/London date '+%Y-%m-%d %H:%M %Z') alive\" >> '$HEARTBEAT'
        fi

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
echo "  Checks at: 07:00 and 17:00 London time (GMT/BST)"
echo "  Alerts:    $LOG"
echo "  Full log:  $ALL"
echo "  Stop with: kill \$(cat monitoring/tfl_monitor.pid)"
