"""
Background monitoring daemon.

Schedule:
  ISDA DC      — every 15 minutes
  TfL Bakerloo — 07:00 and 17:00 London time

Notification behaviour:
  2026-04-09 (tomorrow)   ISDA: confirm every 4th check (~hourly); TfL: confirm both slots
  2026-04-10+ (day after) Both monitors silent unless an alert fires

Run in background:
    nohup python agents/monitor_daemon.py >> monitoring/daemon.log 2>&1 &
    echo $! > monitoring/daemon.pid

Stop:
    kill $(cat monitoring/daemon.pid)
"""

import asyncio
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LONDON_TZ = ZoneInfo("Europe/London")
REPO_ROOT = Path(__file__).parent.parent
MONITORING_DIR = REPO_ROOT / "monitoring"

ISDA_INTERVAL_SECONDS = 900        # 15 minutes
TFL_CHECK_TIMES = {"07:00", "17:00"}

# Dates relative to when this daemon was configured
_CONFIGURED = date(2026, 4, 8)
VERBOSE_DATE  = _CONFIGURED + timedelta(days=1)   # 2026-04-09: confirmations on
SILENT_FROM   = _CONFIGURED + timedelta(days=2)   # 2026-04-10+: alerts only

ISDA_CONFIRM_EVERY_N = 4           # Every 4th check ≈ 1 hour


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


def today_london() -> date:
    return datetime.now(LONDON_TZ).date()


def stamp() -> str:
    return datetime.now(LONDON_TZ).strftime("%Y-%m-%d %H:%M %Z")


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
    daily_count = 0
    last_count_date: date | None = None

    while True:
        today = today_london()

        # Reset count at midnight
        if today != last_count_date:
            daily_count = 0
            last_count_date = today

        alert, output = run_check("check_isda.py")
        daily_count += 1

        if alert:
            notify("ISDA DC", output, "*** ALERT — new submission ***")
        elif today == VERBOSE_DATE and daily_count % ISDA_CONFIRM_EVERY_N == 0:
            notify("ISDA DC", output, f"hourly confirmation (check {daily_count} today) — no new submissions")
        # else: silent

        await asyncio.sleep(ISDA_INTERVAL_SECONDS)


async def tfl_loop() -> None:
    """Check TfL Bakerloo at 07:00 and 17:00 London time."""
    last_run_key = ""

    while True:
        now = datetime.now(LONDON_TZ)
        today = now.date()
        hhmm = now.strftime("%H:%M")
        run_key = f"{today}_{hhmm}"

        if hhmm in TFL_CHECK_TIMES and run_key != last_run_key:
            last_run_key = run_key
            alert, output = run_check("check_tfl.py")

            if alert:
                slot = "morning" if hhmm == "07:00" else "afternoon"
                notify("TfL Bakerloo", output, f"*** ALERT — disruption detected ({slot} check) ***")
            elif today == VERBOSE_DATE:
                slot = "morning" if hhmm == "07:00" else "afternoon"
                notify("TfL Bakerloo", output, f"{slot} check confirmed — good service")
            # else (2026-04-10+): silent unless alert

        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"[{stamp()}] Monitoring daemon started.")
    print(f"  ISDA DC      — every 15 min")
    print(f"    {VERBOSE_DATE}: hourly confirmation (every {ISDA_CONFIRM_EVERY_N}th check)")
    print(f"    {SILENT_FROM}+: alerts only")
    print(f"  TfL Bakerloo — 07:00 & 17:00 London time")
    print(f"    {VERBOSE_DATE}: both checks confirmed")
    print(f"    {SILENT_FROM}+: alerts only")
    sys.stdout.flush()

    await asyncio.gather(isda_loop(), tfl_loop())


if __name__ == "__main__":
    asyncio.run(main())
