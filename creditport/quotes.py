"""Load and organize dealer quote data from Excel/CSV snapshots.

Handles the standard dealer quote format with columns:
    Extraction Date, Value Date, Product Type, Ticker, Curve, Strike,
    Option Type, Expiration Date, Firm, Bid/Offer Price Type,
    Bid/Offer Premium, Bid/Mid/Offer Volatility, Mid Delta/Vega/Theta/Gamma,
    Mid Forward Spread, Mid Forward Price, Mid Reference Spread, Mid Reference Price

Quote conventions:
    - Premiums: cents per 100 notional
    - Volatilities: percentage (69.75 = 69.75% = 0.6975 decimal)
    - Spreads: basis points
    - Prices: per 100 notional (par = 100)

Curve code mapping:
    ITXEB5{series}  → iTraxx Main        (B = Broad)
    ITXEX5{series}  → iTraxx Crossover   (X = Crossover)
    ITXES5{series}  → iTraxx Senior Fin  (S = Senior)
    CDXIG5{series}  → CDX IG
    CDXHY5{series}  → CDX HY

    The "5" is the tenor indicator (5Y). Series follows directly:
    e.g. ITXEB544 = Main S44, CDXIG543 = CDX IG S43
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .conventions import INDEX_ALIASES, IndexFamily, OptionType

# ---------------------------------------------------------------------------
# Curve code → IndexFamily mapping
# ---------------------------------------------------------------------------

# Regex patterns for known curve codes. Add new patterns as indices are added.
_CURVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^ITXEB5(\d+)$", re.IGNORECASE), "main"),      # B = Broad (Main)
    (re.compile(r"^ITXEX5(\d+)$", re.IGNORECASE), "xover"),     # X = Crossover
    (re.compile(r"^ITXES5(\d+)$", re.IGNORECASE), "snrfin"),    # S = Senior Financials
    (re.compile(r"^CDXIG5?(\d+)$", re.IGNORECASE), "cdxig"),
    (re.compile(r"^CDXHY5?(\d+)$", re.IGNORECASE), "cdxhy"),
]

# Allow direct registration of curve codes
CURVE_CODE_MAP: dict[str, tuple[IndexFamily, int]] = {}


def register_curve_code(code: str, family: IndexFamily, series: int) -> None:
    """Register a curve code to a specific index family and series."""
    CURVE_CODE_MAP[code.upper()] = (family, series)


def _parse_curve_code(code: str) -> tuple[IndexFamily, int]:
    """Parse a curve code like 'ITXES544' into (IndexFamily, series)."""
    code_upper = code.upper().strip()

    # Check direct registrations first
    if code_upper in CURVE_CODE_MAP:
        return CURVE_CODE_MAP[code_upper]

    # Try regex patterns
    for pattern, alias in _CURVE_PATTERNS:
        m = pattern.match(code_upper)
        if m:
            series = int(m.group(1))
            family = INDEX_ALIASES[alias]
            return family, series

    raise ValueError(
        f"Unknown curve code: '{code}'. "
        f"Register it with register_curve_code() or add a pattern to _CURVE_PATTERNS."
    )


# ---------------------------------------------------------------------------
# Single quote record
# ---------------------------------------------------------------------------

@dataclass
class OptionQuote:
    """A single dealer quote for a credit index option."""

    family: IndexFamily
    series: int
    strike_bps: float
    option_type: OptionType
    expiry: dt.date
    firm: str

    # Premiums in cents per 100 notional
    bid_premium: float | None = None
    offer_premium: float | None = None

    # Volatilities as decimals (0.6975 = 69.75%)
    bid_vol: float | None = None
    mid_vol: float | None = None
    offer_vol: float | None = None

    # Market greeks
    mid_delta: float | None = None
    mid_vega: float | None = None
    mid_theta: float | None = None
    mid_gamma: float | None = None

    # Reference levels
    mid_forward_spread: float | None = None
    mid_forward_price: float | None = None
    mid_ref_spread: float | None = None
    mid_ref_price: float | None = None

    # Raw data
    ticker: str = ""
    curve: str = ""

    @property
    def mid_premium(self) -> float | None:
        if self.bid_premium is not None and self.offer_premium is not None:
            return (self.bid_premium + self.offer_premium) / 2
        return self.bid_premium or self.offer_premium

    @property
    def label(self) -> str:
        otype = "P" if self.option_type == OptionType.PAYER else "R"
        return f"{self.family.value}{self.series} {self.expiry:%b}{self.strike_bps:.0f}{otype}"


# ---------------------------------------------------------------------------
# Quote grid: organizes quotes by option × dealer
# ---------------------------------------------------------------------------

@dataclass
class QuoteGrid:
    """Organized grid of dealer quotes for an index.

    Groups quotes by (expiry, strike, option_type) and shows
    bid/ask/mid per dealer in both price and vol space.
    """

    family: IndexFamily
    series: int
    quotes: list[OptionQuote] = field(default_factory=list)

    # Common reference levels (set during normalization)
    common_ref_spread: float | None = None
    common_fwd_spreads: dict[dt.date, float] = field(default_factory=dict)

    def add(self, quote: OptionQuote) -> None:
        self.quotes.append(quote)

    @property
    def firms(self) -> list[str]:
        return sorted(set(q.firm for q in self.quotes))

    @property
    def expiries(self) -> list[dt.date]:
        return sorted(set(q.expiry for q in self.quotes))

    @property
    def strikes(self) -> list[float]:
        return sorted(set(q.strike_bps for q in self.quotes))

    def filter(
        self,
        expiry: dt.date | None = None,
        strike: float | None = None,
        option_type: OptionType | None = None,
        firm: str | None = None,
    ) -> list[OptionQuote]:
        """Filter quotes by any combination of criteria."""
        result = self.quotes
        if expiry is not None:
            result = [q for q in result if q.expiry == expiry]
        if strike is not None:
            result = [q for q in result if q.strike_bps == strike]
        if option_type is not None:
            result = [q for q in result if q.option_type == option_type]
        if firm is not None:
            result = [q for q in result if q.firm == firm]
        return result

    def to_vol_grid(self, expiry: dt.date | None = None) -> pd.DataFrame:
        """Build a vol grid: rows=strikes, columns=dealer mids.

        Shows mid vol per dealer for each strike, plus composite mid.
        """
        quotes = self.quotes if expiry is None else [q for q in self.quotes if q.expiry == expiry]
        if not quotes:
            return pd.DataFrame()

        rows = []
        # Group by (strike, option_type)
        keys = sorted(set((q.strike_bps, q.option_type) for q in quotes))
        firms = self.firms

        for strike, otype in keys:
            row: dict[str, object] = {
                "strike": strike,
                "type": "P" if otype == OptionType.PAYER else "R",
            }
            vols = []
            for firm in firms:
                firm_quotes = [
                    q for q in quotes
                    if q.strike_bps == strike and q.option_type == otype and q.firm == firm
                ]
                if firm_quotes and firm_quotes[0].mid_vol is not None:
                    vol = firm_quotes[0].mid_vol
                    row[f"{firm}_vol"] = vol
                    vols.append(vol)
                else:
                    row[f"{firm}_vol"] = None

            row["composite_vol"] = np.mean(vols) if vols else None
            rows.append(row)

        return pd.DataFrame(rows)

    def to_price_grid(self, expiry: dt.date | None = None) -> pd.DataFrame:
        """Build a price grid: rows=strikes, columns=dealer bid/ask/mid.

        Shows bid/ask/mid premium per dealer for each strike.
        """
        quotes = self.quotes if expiry is None else [q for q in self.quotes if q.expiry == expiry]
        if not quotes:
            return pd.DataFrame()

        rows = []
        keys = sorted(set((q.strike_bps, q.option_type) for q in quotes))
        firms = self.firms

        for strike, otype in keys:
            row: dict[str, object] = {
                "strike": strike,
                "type": "P" if otype == OptionType.PAYER else "R",
            }
            mids = []
            for firm in firms:
                firm_quotes = [
                    q for q in quotes
                    if q.strike_bps == strike and q.option_type == otype and q.firm == firm
                ]
                if firm_quotes:
                    fq = firm_quotes[0]
                    row[f"{firm}_bid"] = fq.bid_premium
                    row[f"{firm}_ask"] = fq.offer_premium
                    mid = fq.mid_premium
                    row[f"{firm}_mid"] = mid
                    if mid is not None:
                        mids.append(mid)
                else:
                    row[f"{firm}_bid"] = None
                    row[f"{firm}_ask"] = None
                    row[f"{firm}_mid"] = None

            row["composite_mid"] = np.mean(mids) if mids else None
            rows.append(row)

        return pd.DataFrame(rows)

    def composite_vol_surface(
        self,
        expiry: dt.date,
        option_type: OptionType | None = None,
    ) -> dict[float, float]:
        """Extract a composite vol surface for a single expiry.

        Takes the mean mid vol across dealers at each strike.
        If option_type is None, uses payer vols where available.

        Returns:
            {strike_bps: vol_decimal} suitable for IndexMarketData.vol_surface.
        """
        quotes = [q for q in self.quotes if q.expiry == expiry]
        if option_type is not None:
            quotes = [q for q in quotes if q.option_type == option_type]

        surface: dict[float, list[float]] = {}
        for q in quotes:
            if q.mid_vol is not None:
                surface.setdefault(q.strike_bps, []).append(q.mid_vol)

        return {k: float(np.mean(v)) for k, v in sorted(surface.items())}


# ---------------------------------------------------------------------------
# Loader: parse the raw Excel/CSV into OptionQuotes and QuoteGrids
# ---------------------------------------------------------------------------

def _parse_option_type(s: str) -> OptionType:
    s = s.strip().upper()
    if s in ("PAY", "PAYER"):
        return OptionType.PAYER
    elif s in ("REC", "RECEIVER"):
        return OptionType.RECEIVER
    raise ValueError(f"Unknown option type: '{s}'")


def _parse_date(val) -> dt.date | None:
    """Parse a date from various formats."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, dt.date):
        return val
    if isinstance(val, dt.datetime):
        return val.date()
    if hasattr(val, "date"):  # pandas Timestamp
        return val.date()
    if isinstance(val, str):
        val = val.strip()
        # Try DD/MM/YYYY format
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M"):
            try:
                return dt.datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


def _safe_float(val) -> float | None:
    """Convert to float, returning None for NaN/empty."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (ValueError, TypeError):
        return None


def load_dealer_quotes(
    path: str | Path,
    sheet_name: str | int = 0,
) -> list[OptionQuote]:
    """Load dealer quotes from an Excel or CSV file.

    Reads the standard dealer format and returns a list of OptionQuote objects.

    Args:
        path: Path to Excel (.xlsx/.xls) or CSV file.
        sheet_name: Excel sheet name or index (ignored for CSV).

    Returns:
        List of parsed OptionQuote objects.
    """
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet_name)
    else:
        df = pd.read_csv(path)

    # Normalize column names: strip whitespace, handle common variations
    df.columns = [c.strip() for c in df.columns]

    # Column name mapping (handle slight variations)
    col_map = _find_columns(df.columns.tolist())

    quotes = []
    for _, row in df.iterrows():
        try:
            curve = str(row[col_map["curve"]]).strip()
            family, series = _parse_curve_code(curve)
            strike = float(row[col_map["strike"]])
            otype = _parse_option_type(str(row[col_map["option_type"]]))
            expiry = _parse_date(row[col_map["expiration_date"]])
            firm = str(row[col_map["firm"]]).strip()

            if expiry is None:
                continue

            quote = OptionQuote(
                family=family,
                series=series,
                strike_bps=strike,
                option_type=otype,
                expiry=expiry,
                firm=firm,
                bid_premium=_safe_float(row.get(col_map.get("bid_premium", ""))),
                offer_premium=_safe_float(row.get(col_map.get("offer_premium", ""))),
                bid_vol=_pct_to_dec(_safe_float(row.get(col_map.get("bid_vol", "")))),
                mid_vol=_pct_to_dec(_safe_float(row.get(col_map.get("mid_vol", "")))),
                offer_vol=_pct_to_dec(_safe_float(row.get(col_map.get("offer_vol", "")))),
                mid_delta=_safe_float(row.get(col_map.get("mid_delta", ""))),
                mid_vega=_safe_float(row.get(col_map.get("mid_vega", ""))),
                mid_theta=_safe_float(row.get(col_map.get("mid_theta", ""))),
                mid_gamma=_safe_float(row.get(col_map.get("mid_gamma", ""))),
                mid_forward_spread=_safe_float(row.get(col_map.get("mid_fwd_spread", ""))),
                mid_forward_price=_safe_float(row.get(col_map.get("mid_fwd_price", ""))),
                mid_ref_spread=_safe_float(row.get(col_map.get("mid_ref_spread", ""))),
                mid_ref_price=_safe_float(row.get(col_map.get("mid_ref_price", ""))),
                ticker=str(row.get(col_map.get("ticker", ""), "")),
                curve=curve,
            )
            quotes.append(quote)
        except (ValueError, KeyError):
            continue  # skip unparseable rows

    return quotes


def _pct_to_dec(val: float | None) -> float | None:
    """Convert percentage to decimal (69.75 → 0.6975). Returns None for 0 or None."""
    if val is None or val == 0:
        return None
    return val / 100.0


def _find_columns(columns: list[str]) -> dict[str, str]:
    """Map logical column names to actual DataFrame column names.

    Handles slight naming variations across data providers.
    """
    mapping: dict[str, str] = {}
    lower_cols = {c.lower(): c for c in columns}

    searches = {
        "curve": ["curve"],
        "strike": ["strike"],
        "option_type": ["option type", "optiontype", "option_type"],
        "expiration_date": ["expiration date", "expirationdate", "expiry", "expiration_date"],
        "firm": ["firm", "dealer", "source"],
        "ticker": ["ticker"],
        "bid_premium": ["bid premium", "bidpremium", "bid_premium"],
        "offer_premium": ["offer premium", "offerpremium", "offer_premium", "ask premium"],
        "bid_vol": ["bid volatility", "bidvolatility", "bid_volatility"],
        "mid_vol": ["mid volatility", "midvolatility", "mid_volatility"],
        "offer_vol": ["offer volatility", "offervolatility", "offer_volatility"],
        "mid_delta": ["mid delta", "middelta", "mid_delta"],
        "mid_vega": ["mid vega", "midvega", "mid_vega"],
        "mid_theta": ["mid theta", "midtheta", "mid_theta"],
        "mid_gamma": ["mid gamma", "midgamma", "mid_gamma"],
        "mid_fwd_spread": ["mid forward spread", "midforwardspread", "mid_forward_spread"],
        "mid_fwd_price": ["mid forward price", "midforwardprice", "mid_forward_price"],
        "mid_ref_spread": ["mid reference spread", "midreferencespread", "mid_reference_spread"],
        "mid_ref_price": ["mid reference price", "midreferenceprice", "mid_reference_price"],
    }

    for key, candidates in searches.items():
        for candidate in candidates:
            if candidate in lower_cols:
                mapping[key] = lower_cols[candidate]
                break

    required = {"curve", "strike", "option_type", "expiration_date", "firm"}
    missing = required - set(mapping.keys())
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Available columns: {columns}"
        )

    return mapping


# ---------------------------------------------------------------------------
# Build grids from quotes
# ---------------------------------------------------------------------------

def build_quote_grids(quotes: list[OptionQuote]) -> dict[tuple[IndexFamily, int], QuoteGrid]:
    """Organize quotes into per-index QuoteGrids."""
    grids: dict[tuple[IndexFamily, int], QuoteGrid] = {}
    for q in quotes:
        key = (q.family, q.series)
        if key not in grids:
            grids[key] = QuoteGrid(family=q.family, series=q.series)
        grids[key].add(q)

    # Set common reference spread per grid (median of all ref spreads)
    for grid in grids.values():
        ref_spreads = [q.mid_ref_spread for q in grid.quotes if q.mid_ref_spread is not None]
        if ref_spreads:
            grid.common_ref_spread = float(np.median(ref_spreads))

        # Common forward spread per expiry
        for expiry in grid.expiries:
            fwd_spreads = [
                q.mid_forward_spread
                for q in grid.quotes
                if q.expiry == expiry and q.mid_forward_spread is not None
            ]
            if fwd_spreads:
                grid.common_fwd_spreads[expiry] = float(np.median(fwd_spreads))

    return grids


def quotes_to_market_data(
    quotes: list[OptionQuote],
    ref_date: dt.date,
    risk_free_rate: float = 0.03,
    expiry: dt.date | None = None,
    maturity_date: dt.date | None = None,
) -> "MarketData":
    """Convert dealer quotes into a MarketData object for pricing.

    Extracts composite mid vol surfaces from the quotes.

    Args:
        quotes: List of OptionQuote from load_dealer_quotes().
        ref_date: Valuation date.
        risk_free_rate: Risk-free rate for the discount curve.
        expiry: If set, use vols from this expiry only. If None,
                uses the nearest expiry.
        maturity_date: Index maturity date override. If None, not set.

    Returns:
        MarketData ready for pricing.
    """
    from .curves import DiscountCurve
    from .market import IndexMarketData, MarketData

    grids = build_quote_grids(quotes)

    market = MarketData(
        ref_date=ref_date,
        discount_curve=DiscountCurve(risk_free_rate),
    )

    for (family, series), grid in grids.items():
        # Pick expiry for vol surface
        target_expiry = expiry
        if target_expiry is None and grid.expiries:
            # Use nearest future expiry
            future = [e for e in grid.expiries if e >= ref_date]
            target_expiry = min(future) if future else grid.expiries[0]

        # Build composite vol surface
        vol_surface = {}
        if target_expiry:
            vol_surface = grid.composite_vol_surface(target_expiry)

        # Reference spread
        spread = grid.common_ref_spread or 0.0

        market.add_index(IndexMarketData(
            family=family,
            series=series,
            spread_bps=spread,
            vol_surface=vol_surface,
            maturity_date=maturity_date,
        ))

    return market
