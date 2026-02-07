"""Date utilities for CDS indices and options."""

import datetime as dt
from functools import lru_cache

# CDS standard payment months (IMM dates: Mar, Jun, Sep, Dec on the 20th)
IMM_MONTHS = [3, 6, 9, 12]
IMM_DAY = 20

MONTH_CODES: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def third_wednesday(year: int, month: int) -> dt.date:
    """Return the third Wednesday of the given month/year."""
    # First day of the month
    first = dt.date(year, month, 1)
    # Find first Wednesday (weekday 2)
    offset = (2 - first.weekday()) % 7
    first_wed = first + dt.timedelta(days=offset)
    # Third Wednesday = first + 14 days
    return first_wed + dt.timedelta(days=14)


def resolve_expiry(month_code: str, ref_date: dt.date | None = None) -> dt.date:
    """Resolve a month code like 'mar' to the 3rd Wednesday expiry.

    If ref_date is given, picks the next occurrence of that month's
    third Wednesday that is on or after ref_date. If ref_date is None,
    uses today.
    """
    if ref_date is None:
        ref_date = dt.date.today()

    month = MONTH_CODES[month_code.lower()]
    # Try current year first
    expiry = third_wednesday(ref_date.year, month)
    if expiry < ref_date:
        expiry = third_wednesday(ref_date.year + 1, month)
    return expiry


def imm_schedule(start: dt.date, tenor_years: int) -> list[dt.date]:
    """Generate a CDS payment schedule (IMM 20ths) from start for tenor_years.

    Returns quarterly payment dates (20th of Mar/Jun/Sep/Dec) from the
    first IMM date on or after start through tenor_years.
    """
    end = dt.date(start.year + tenor_years, start.month, start.day)
    return imm_schedule_between(start, end)


def imm_schedule_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Generate IMM dates (20th of Mar/Jun/Sep/Dec) strictly after start up to end (inclusive).

    Args:
        start: Start date (exclusive — first returned date is after this).
        end: End date (inclusive).

    Returns:
        Sorted list of IMM dates in (start, end].
    """
    dates = []
    year = start.year
    while True:
        for m in IMM_MONTHS:
            d = dt.date(year, m, IMM_DAY)
            if d <= start:
                continue
            if d > end:
                return dates
            dates.append(d)
        year += 1
    return dates


def next_imm_date(after: dt.date) -> dt.date:
    """Return the next IMM date (20th of Mar/Jun/Sep/Dec) strictly after the given date."""
    year = after.year
    for _ in range(2):  # check current year and next
        for m in IMM_MONTHS:
            d = dt.date(year, m, IMM_DAY)
            if d > after:
                return d
        year += 1
    raise ValueError(f"Could not find next IMM date after {after}")


def standard_maturity(roll_date: dt.date, tenor_years: int = 5) -> dt.date:
    """Compute the standard CDS index maturity from a roll date and tenor.

    A 5Y index rolling on March 20, 2025 matures on June 20, 2030
    (the next IMM date after roll_date + tenor).
    """
    target = dt.date(roll_date.year + tenor_years, roll_date.month, roll_date.day)
    return next_imm_date(target - dt.timedelta(days=1))


def year_fraction(d1: dt.date, d2: dt.date, convention: str = "ACT/360") -> float:
    """Year fraction between two dates under a given day count convention."""
    days = (d2 - d1).days
    if convention == "ACT/360":
        return days / 360.0
    elif convention == "ACT/365":
        return days / 365.0
    else:
        raise ValueError(f"Unknown day count convention: {convention}")


def time_to_date(target: dt.date, ref_date: dt.date | None = None) -> float:
    """Time in years (ACT/365) from ref_date to target."""
    if ref_date is None:
        ref_date = dt.date.today()
    return (target - ref_date).days / 365.0
