"""
TfL Bakerloo line status monitor.
Checks the TfL API for disruptions on the Bakerloo line and reports them.

Usage:
    python check_tfl.py          # check and report — prints alert if issues found
    python check_tfl.py --quiet  # only output if there's a problem (for cron)

TfL status severity codes (10 = Good Service, anything lower = disruption):
    10  Good Service
     9  Minor Delays
     8  Reduced Service
     7  Bus Service
     6  Suspended
     5  Part Suspended
     4  Planned Closure
     3  Part Closure
     2  Severe Delays
     1  Special Service
     0  Closed
    -1  Not Running
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

LONDON_TZ = ZoneInfo("Europe/London")

API_URL = "https://api.tfl.gov.uk/Line/bakerloo/Status"
LINE_NAME = "Bakerloo"
GOOD_SERVICE_SEVERITY = 10


def fetch_status() -> list[dict]:
    """Fetch current Bakerloo line status from TfL API."""
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def parse_statuses(data: list[dict]) -> list[dict]:
    """Extract status entries from the API response."""
    statuses = []
    for line in data:
        for status in line.get("lineStatuses", []):
            statuses.append({
                "severity": status.get("statusSeverity", -1),
                "description": status.get("statusSeverityDescription", "Unknown"),
                "reason": status.get("reason", ""),
            })
    return statuses


def has_disruption(statuses: list[dict]) -> bool:
    return any(s["severity"] != GOOD_SERVICE_SEVERITY for s in statuses)


def format_status(statuses: list[dict]) -> str:
    lines = []
    for s in statuses:
        lines.append(f"  Status:  {s['description']} (severity {s['severity']})")
        if s["reason"]:
            # Wrap long reason text
            reason = s["reason"].strip()
            lines.append(f"  Reason:  {reason}")
    return "\n".join(lines)


def main():
    quiet = "--quiet" in sys.argv
    now = datetime.now(LONDON_TZ)
    tz_label = now.strftime("%Z")  # GMT or BST
    timestamp = now.strftime(f"%Y-%m-%d %H:%M {tz_label}")

    try:
        data = fetch_status()
    except urllib.error.URLError as e:
        print(f"ERROR: Could not fetch TfL status: {e}", file=sys.stderr)
        sys.exit(1)

    statuses = parse_statuses(data)

    if not statuses:
        print(f"[{timestamp}] WARNING: No status data returned from TfL API")
        sys.exit(0)

    if has_disruption(statuses):
        print(f"\n{'='*60}")
        print(f"  *** BAKERLOO LINE DISRUPTION DETECTED ***")
        print(f"{'='*60}")
        print(format_status(statuses))
        print(f"  Checked:  {timestamp}")
        print(f"{'='*60}\n")
    else:
        if not quiet:
            desc = statuses[0]["description"]
            print(f"[{timestamp}] Bakerloo: {desc} — no action needed.")


if __name__ == "__main__":
    main()
