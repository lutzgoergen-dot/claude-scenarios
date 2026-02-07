"""Delta hedging for credit index option portfolios."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from .conventions import IndexFamily, get_convention
from .curves import compute_rpv01
from .instruments import CreditIndex, CreditIndexOption
from .market import MarketData
from .portfolio import Portfolio


@dataclass
class HedgeResult:
    """Result of a delta hedge calculation."""

    hedge_instrument: CreditIndex
    hedge_notional: float  # notional to trade (positive = sell protection)
    portfolio_delta_before: float
    portfolio_delta_after: float
    residual_delta: float


def compute_delta_hedge(
    portfolio: Portfolio,
    market: MarketData,
    hedge_index: str = None,
    family: IndexFamily = None,
    series: int = None,
    tenor_years: int = 5,
) -> HedgeResult:
    """Compute the index notional needed to delta-hedge the portfolio.

    The hedge offsets the portfolio's spread delta using a linear
    index position.

    Args:
        portfolio: The portfolio to hedge.
        market: Current market data.
        hedge_index: Position string for hedge instrument (e.g. "main44 5y").
                    Alternative to family/series/tenor.
        family: Index family for hedge (if not using hedge_index string).
        series: Series number for hedge.
        tenor_years: Tenor of hedge instrument.

    Returns:
        HedgeResult with the required hedge notional and residual risk.
    """
    from .parsing import parse_position

    # Determine hedge instrument
    if hedge_index:
        instrument = parse_position(hedge_index)
        if not isinstance(instrument, CreditIndex):
            raise ValueError(f"Hedge instrument must be a linear index, got: {hedge_index}")
        family = instrument.family
        series = instrument.series
        tenor_years = instrument.tenor_years
    elif family is None or series is None:
        raise ValueError("Must provide either hedge_index or family+series")

    # Compute portfolio greeks
    greeks_df = portfolio.greeks_table(market)
    # Exclude TOTAL row
    positions_df = greeks_df[greeks_df["label"] != "TOTAL"]
    total_delta = positions_df["delta"].sum()

    # Compute hedge instrument delta per unit notional
    conv = get_convention(family)
    idx_data = market.get_index(family, series)
    rpv01 = compute_rpv01(
        idx_data.spread_bps,
        conv.recovery_rate,
        market.discount_curve,
        market.ref_date,
        tenor_years,
        maturity_date=idx_data.maturity_date,
    )
    hedge_delta_per_unit = rpv01 / 10_000  # delta per 1bp per unit notional

    # Notional to offset portfolio delta
    # portfolio_delta + hedge_notional * hedge_delta_per_unit = 0
    if abs(hedge_delta_per_unit) < 1e-15:
        raise ValueError("Hedge instrument has zero delta — cannot hedge")

    hedge_notional = -total_delta / hedge_delta_per_unit

    hedge_instrument = CreditIndex(
        family=family,
        series=series,
        tenor_years=tenor_years,
        notional=hedge_notional,
    )

    return HedgeResult(
        hedge_instrument=hedge_instrument,
        hedge_notional=hedge_notional,
        portfolio_delta_before=total_delta,
        portfolio_delta_after=total_delta + hedge_notional * hedge_delta_per_unit,
        residual_delta=total_delta + hedge_notional * hedge_delta_per_unit,
    )


def apply_delta_hedge(
    portfolio: Portfolio,
    market: MarketData,
    hedge_index: str,
) -> HedgeResult:
    """Compute and apply a delta hedge to the portfolio.

    Adds the hedge position directly to the portfolio.

    Args:
        portfolio: Portfolio to hedge (will be modified).
        market: Current market data.
        hedge_index: Position string for hedge (e.g. "main44 5y").

    Returns:
        HedgeResult with hedge details.
    """
    result = compute_delta_hedge(portfolio, market, hedge_index=hedge_index)
    portfolio.add_instrument(result.hedge_instrument)
    return result
