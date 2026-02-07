"""Portfolio container: holds positions, prices them, and reports greeks."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from .black import black_price
from .conventions import OptionType, get_convention
from .curves import DiscountCurve, compute_rpv01
from .greeks import Greeks, compute_greeks_numerical
from .instruments import CreditIndex, CreditIndexOption
from .market import MarketData
from .parsing import parse_position


@dataclass
class PositionResult:
    """Pricing result for a single position."""

    label: str
    notional: float
    unit_price: float  # per unit notional
    market_value: float  # unit_price * notional
    greeks: Greeks | None = None


@dataclass
class Portfolio:
    """A portfolio of credit index options and linear index positions.

    Usage:
        port = Portfolio()
        port.add("main44 mar55p", notional=10_000_000)
        port.add("main44 mar60r", notional=-5_000_000)
        port.add("main44 5y", notional=2_000_000)  # delta hedge

        results = port.price(market_data)
    """

    positions: list[CreditIndexOption | CreditIndex] = field(default_factory=list)
    ref_date: dt.date | None = None

    def add(
        self,
        position_str: str,
        notional: float = 0.0,
        ref_date: dt.date | None = None,
    ) -> CreditIndexOption | CreditIndex:
        """Parse and add a position to the portfolio.

        Args:
            position_str: e.g. "main44 mar55p" or "main44 5y"
            notional: Position notional. Positive = long.
            ref_date: Reference date for resolving expiry.

        Returns:
            The created instrument.
        """
        rd = ref_date or self.ref_date
        instrument = parse_position(position_str, notional, rd)
        self.positions.append(instrument)
        return instrument

    def add_instrument(self, instrument: CreditIndexOption | CreditIndex) -> None:
        """Add a pre-built instrument to the portfolio."""
        self.positions.append(instrument)

    def clear(self) -> None:
        """Remove all positions."""
        self.positions.clear()

    def price(self, market: MarketData) -> list[PositionResult]:
        """Price all positions against current market data.

        Returns a list of PositionResult, one per position.
        """
        results = []
        for pos in self.positions:
            result = _price_position(pos, market)
            results.append(result)
        return results

    def greeks_table(self, market: MarketData) -> pd.DataFrame:
        """Compute greeks for all positions, return as DataFrame.

        Columns: label, notional, price, delta, gamma, vega, theta, mv
        """
        results = self.price(market)
        rows = []
        for r in results:
            row = {"label": r.label, "notional": r.notional, "mv": r.market_value}
            if r.greeks:
                row.update({
                    "price_unit": r.unit_price,
                    "delta": r.greeks.delta * r.notional,
                    "gamma": r.greeks.gamma * r.notional,
                    "vega": r.greeks.vega * r.notional,
                    "theta": r.greeks.theta * r.notional,
                })
            else:
                row.update({
                    "price_unit": r.unit_price,
                    "delta": 0.0,
                    "gamma": 0.0,
                    "vega": 0.0,
                    "theta": 0.0,
                })
            rows.append(row)

        df = pd.DataFrame(rows)
        # Add totals row
        if len(df) > 0:
            totals = {
                "label": "TOTAL",
                "notional": df["notional"].sum(),
                "mv": df["mv"].sum(),
                "price_unit": 0.0,
                "delta": df["delta"].sum(),
                "gamma": df["gamma"].sum(),
                "vega": df["vega"].sum(),
                "theta": df["theta"].sum(),
            }
            df = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)

        return df

    def summary(self, market: MarketData) -> str:
        """Pretty-print portfolio summary."""
        df = self.greeks_table(market)
        return df.to_string(index=False, float_format="{:,.2f}".format)


def _price_position(
    pos: CreditIndexOption | CreditIndex,
    market: MarketData,
) -> PositionResult:
    """Price a single position."""
    conv = get_convention(pos.family)
    idx_data = market.get_index(pos.family, pos.series)

    if isinstance(pos, CreditIndex):
        # Linear index: value = (spread - coupon) * RPV01
        rpv01 = compute_rpv01(
            idx_data.spread_bps,
            conv.recovery_rate,
            market.discount_curve,
            market.ref_date,
            pos.tenor_years,
        )
        # Mark-to-market: upfront = (spread - coupon) * RPV01
        spread_dec = idx_data.spread_bps / 10_000
        coupon_dec = conv.fixed_coupon
        unit_price = (spread_dec - coupon_dec) * rpv01

        # Delta for linear = RPV01 / 10000 (per 1bp)
        delta_per_bp = rpv01 / 10_000

        return PositionResult(
            label=pos.label,
            notional=pos.notional,
            unit_price=unit_price,
            market_value=unit_price * pos.notional,
            greeks=Greeks(
                price=unit_price,
                delta=delta_per_bp,
                gamma=0.0,
                vega=0.0,
                theta=0.0,
            ),
        )

    elif isinstance(pos, CreditIndexOption):
        vol = idx_data.get_vol(pos.strike_bps)
        T = pos.time_to_expiry(market.ref_date)

        greeks = compute_greeks_numerical(
            option=pos,
            spread_bps=idx_data.spread_bps,
            vol=vol,
            discount_curve=market.discount_curve,
            ref_date=market.ref_date,
        )

        return PositionResult(
            label=pos.label,
            notional=pos.notional,
            unit_price=greeks.price,
            market_value=greeks.price * pos.notional,
            greeks=greeks,
        )

    else:
        raise TypeError(f"Unknown position type: {type(pos)}")
