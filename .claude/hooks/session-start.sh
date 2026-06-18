#!/bin/bash
# SessionStart hook: ensures the ISDA DC monitor is running.
# Restarts it automatically if the machine was rebooted or the process died.

MONITOR_DIR="$CLAUDE_PROJECT_DIR/monitoring"
PID_FILE="$MONITOR_DIR/monitor.pid"
START_SCRIPT="$MONITOR_DIR/start_monitor.sh"

check_monitor() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "ISDA monitor running (PID $PID) — checking every 15 minutes." >&2
            return 0
        fi
    fi
    return 1
}

if check_monitor; then
    exit 0
fi

# Process is dead — restart it
echo "" >&2
echo "⚠️  ISDA monitor was not running (machine may have restarted). Restarting..." >&2
bash "$START_SCRIPT" >&2
echo "ISDA monitor restarted. Check monitoring/isda_alerts.log for any missed alerts." >&2
