"""
ISDA Determinations Committee monitor.
Checks for new questions submitted to the DC and reports them.

Usage:
    python check_isda.py          # check and report new entries
    python check_isda.py --init   # initialise cache with current state (no alerts)
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

DATA_URL = "https://www.cdsdeterminationscommittees.org/credit-default-swaps-archive/data/"
CACHE_FILE = Path(__file__).parent / "isda_cache.json"

# Field indices in each aaData row
IDX_DATE_SUBMITTED = 0   # e.g. "March 13, 2026' '1773424500"
IDX_COMMITTEE      = 1   # e.g. "emea-europe" or ""
IDX_CATEGORY       = 2   # e.g. "credit-event", "successor"
IDX_ENTITY         = 3   # e.g. "RAIZEN FUELS FINANCE"
IDX_RECORD_ID      = 4   # integer — unique record identifier
IDX_STATUS         = 5   # e.g. "Request Accepted by DC"
IDX_OUTCOME        = 6   # e.g. "Question Decided", "None"


def fetch_data(page_size: int = 100) -> list:
    """Fetch the most recent records from the ISDA DC data endpoint.

    The endpoint uses DataTables server-side processing. We request the first
    `page_size` rows (sorted by date desc by default) — enough to catch any
    new submissions without downloading all 600+ historical records.
    """
    import urllib.parse
    # DataTables legacy params (the site uses aoColumns / sEcho style)
    params = urllib.parse.urlencode({
        "iDisplayStart": 0,
        "iDisplayLength": page_size,
        "sEcho": 1,
    }).encode()
    req = urllib.request.Request(
        DATA_URL,
        data=params,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read().decode())
    return raw.get("aaData", [])


def parse_date(raw_date_field: str) -> str:
    """Extract the human-readable date from field[0], e.g. 'March 13, 2026'."""
    # Format: "March 13, 2026' '1773424500"
    return raw_date_field.split("'")[0].strip()


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {"seen_ids": [], "last_check": None}


def save_cache(seen_ids: list[int]) -> None:
    CACHE_FILE.write_text(json.dumps({
        "seen_ids": seen_ids,
        "last_check": datetime.utcnow().isoformat() + "Z",
        "total_seen": len(seen_ids),
    }, indent=2))


def format_entry(row: list) -> str:
    date      = parse_date(str(row[IDX_DATE_SUBMITTED]))
    entity    = row[IDX_ENTITY]
    category  = row[IDX_CATEGORY].replace("-", " ").title()
    committee = row[IDX_COMMITTEE].replace("-", " ").title() if row[IDX_COMMITTEE] else "Americas"
    status    = row[IDX_STATUS]
    return (
        f"  Entity:    {entity}\n"
        f"  Submitted: {date}\n"
        f"  Category:  {category}\n"
        f"  Committee: {committee}\n"
        f"  Status:    {status}"
    )


def main():
    init_mode = "--init" in sys.argv

    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}] Fetching ISDA DC data...", flush=True)

    try:
        rows = fetch_data()
    except urllib.error.URLError as e:
        print(f"ERROR: Could not fetch data: {e}", file=sys.stderr)
        sys.exit(1)

    current_ids = [int(row[IDX_RECORD_ID]) for row in rows]
    total = len(rows)

    cache = load_cache()
    seen_ids = set(cache.get("seen_ids", []))

    if init_mode or not seen_ids:
        save_cache(current_ids)
        print(f"Cache initialised. {total} existing records stored (no alerts will fire for these).")
        print(f"Most recent submission: {parse_date(str(rows[0][IDX_DATE_SUBMITTED]))} — {rows[0][IDX_ENTITY]}")
        return

    # Find new records (not in cache)
    new_rows = [row for row in rows if int(row[IDX_RECORD_ID]) not in seen_ids]

    if not new_rows:
        last = cache.get("last_check", "unknown")
        print(f"No new submissions. Total records: {total}. (Cache last updated: {last})")
    else:
        print(f"\n{'='*60}")
        print(f"  *** {len(new_rows)} NEW ISDA DC SUBMISSION(S) DETECTED ***")
        print(f"{'='*60}")
        for row in new_rows:
            print(format_entry(row))
            print()
        # Update cache with all current IDs
        save_cache(current_ids)

    return new_rows if not init_mode else []


if __name__ == "__main__":
    main()
