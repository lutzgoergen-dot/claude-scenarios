"""Parse position strings into instrument objects.

Position notation:
    Options:  "{index}{series} {month}{strike}{p|r}"
              e.g. "main44 mar55p" = iTraxx Main S44, March expiry, 55bp strike, payer
    Index:    "{index}{series} {tenor}y"
              e.g. "main44 5y" = iTraxx Main S44, 5Y linear position

Supported index codes:
    cdxig, ig        -> CDX NA IG
    cdxhy, hy        -> CDX NA HY
    main, itraxxmain -> iTraxx Main
    xover, crossover -> iTraxx Crossover
    snrfin           -> iTraxx Senior Financials
"""

from __future__ import annotations

import datetime as dt
import re

from .conventions import INDEX_ALIASES, IndexFamily, OptionType
from .dates import resolve_expiry
from .instruments import CreditIndex, CreditIndexOption

# Regex for option positions: e.g. "main44 mar55p", "cdxig43 jun80.5r"
_OPTION_RE = re.compile(
    r"^(?P<index>[a-z]+)(?P<series>\d+)\s+"
    r"(?P<month>[a-z]{3})(?P<strike>[\d.]+)(?P<type>[pr])$",
    re.IGNORECASE,
)

# Regex for linear index positions: e.g. "main44 5y", "cdxig43 5y"
_INDEX_RE = re.compile(
    r"^(?P<index>[a-z]+)(?P<series>\d+)\s+"
    r"(?P<tenor>\d+)y$",
    re.IGNORECASE,
)


def parse_position(
    position_str: str,
    notional: float = 0.0,
    ref_date: dt.date | None = None,
) -> CreditIndexOption | CreditIndex:
    """Parse a position string into an instrument.

    Args:
        position_str: e.g. "main44 mar55p" or "main44 5y"
        notional: Position notional (positive = long).
        ref_date: Reference date for resolving expiry month to a date.

    Returns:
        CreditIndexOption or CreditIndex.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    s = position_str.strip()

    # Try option first
    m = _OPTION_RE.match(s)
    if m:
        index_code = m.group("index").lower()
        series = int(m.group("series"))
        month_code = m.group("month").lower()
        strike = float(m.group("strike"))
        opt_type = OptionType.PAYER if m.group("type").lower() == "p" else OptionType.RECEIVER

        family = _resolve_family(index_code)
        expiry = resolve_expiry(month_code, ref_date)

        return CreditIndexOption(
            family=family,
            series=series,
            strike_bps=strike,
            option_type=opt_type,
            expiry=expiry,
            notional=notional,
        )

    # Try linear index
    m = _INDEX_RE.match(s)
    if m:
        index_code = m.group("index").lower()
        series = int(m.group("series"))
        tenor = int(m.group("tenor"))

        family = _resolve_family(index_code)

        return CreditIndex(
            family=family,
            series=series,
            tenor_years=tenor,
            notional=notional,
        )

    raise ValueError(
        f"Cannot parse position string: '{position_str}'. "
        f"Expected format: 'main44 mar55p' (option) or 'main44 5y' (index)"
    )


def _resolve_family(code: str) -> IndexFamily:
    """Resolve an index code string to an IndexFamily enum."""
    code = code.lower()
    if code in INDEX_ALIASES:
        return INDEX_ALIASES[code]
    raise ValueError(
        f"Unknown index code: '{code}'. "
        f"Known codes: {', '.join(sorted(INDEX_ALIASES.keys()))}"
    )
