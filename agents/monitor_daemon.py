"""
Background monitoring daemon.

Runs the ISDA DC check every 15 minutes and the TfL Bakerloo check at
07:00 and 17:00 London time. For the first WARMUP_CHECKS runs of each
monitor, always prints a confirmation so you know it's working. After
that, only prints if something changed.

Run in background:
    nohup python agents/monitor_daemon.py >> monitoring/daemon.log 2>&1 &
    echo $! > monitoring/daemon.pid

Stop:
    kill $(cat monitoring/daemon.pid)
"""

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LONDON_TZ = ZoneInfo("Europe/London")
REPO_ROOT = Path(__file__).parent.parent
MONITORING_DIR = REPO_ROOT / "monitoring"

ISDA_INTERVAL_SECONDS = 900   # 15 minutes
TFL_CHECK_TIMES = {"07:00", "17:00"}  # London time (handles GMT/BST automatically)
WARMUP_CHECKS = 3             # Always report the first N runs of each monitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_check(script_name: str) -> tuple[bool, str]:
    """Run a monitoring script. Returns (alert_found, output)."""
    result = subprocess.run(
        [sys.executable, str(MONITORING_DIR / script_name)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = (result.stdout + result.stderr).strip()
    alert = (
        "NEW ISDA DC SUBMISSION" in output
        or "BAKERLOO LINE DISRUPTION DETECTED" in output
    )
    return alert, output


def now_london() -> datetime:
    return datetime.now(LONDON_TZ)


def stamp() -> str:
    return now_london().strftime("%Y-%m-%d %H:%M %Z")


def notify(label: str, output: str, reason: str) -> None:
    print(f"\n{'='*60}")
    print(f"  [{stamp()}] {label} — {reason}")
    print(f"{'='*60}")
    print(output)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Per-monitor loops
# ---------------------------------------------------------------------------

async def isda_loop() -> None:
    """Check ISDA DC every 15 minutes."""
    run_count = 0
    while True:
        alert, output = run_check("check_isda.py")
        run_count += 1

        if alert:
            notify("ISDA DC", output, "*** ALERT — new submission ***")
        elif run_count <= WARMUP_CHECKS:
            notify("ISDA DC", output, f"warmup check {run_count}/{WARMUP_CHECKS} — all clear")
        # else: silent; nothing new

        await asyncio.sleep(ISDA_INTERVAL_SECONDS)


async def tfl_loop() -> None:
    """Check TfL Bakerloo at 07:00 and 17:00 London time."""
    run_count = 0
    last_run_key = ""

    while True:
        now = now_london()
        hhmm = now.strftime("%H:%M")
        run_key = f"{now.date()}_{hhmm}"

        if hhmm in TFL_CHECK_TIMES and run_key != last_run_key:
            last_run_key = run_key
            alert, output = run_check("check_tfl.py")
            run_count += 1

            if alert:
                notify("TfL Bakerloo", output, "*** ALERT — disruption detected ***")
            elif run_count <= WARMUP_CHECKS:
                notify("TfL Bakerloo", output, f"warmup check {run_count}/{WARMUP_CHECKS} — good service")
            # else: silent; good service assumed

        await asyncio.sleep(30)  # poll every 30s to catch the scheduled minute


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"[{stamp()}] Monitoring daemon started.")
    print(f"  ISDA DC      — every 15 min  (first {WARMUP_CHECKS} checks always reported)")
    print(f"  TfL Bakerloo — 07:00 & 17:00 London time (first {WARMUP_CHECKS} checks always reported)")
    print(f"  After warmup — silent unless something changes.")
    sys.stdout.flush()

    await asyncio.gather(isda_loop(), tfl_loop())


if __name__ == "__main__":
    asyncio.run(main())
