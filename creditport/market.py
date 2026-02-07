"""Market data container and loaders for CSV/Excel snapshots."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .conventions import IndexFamily
from .curves import DiscountCurve


@dataclass
class IndexMarketData:
    """Market data snapshot for a single index."""

    family: IndexFamily
    series: int
    spread_bps: float  # current index spread
    vol_surface: dict[float, float] = field(default_factory=dict)
    # vol_surface: {strike_bps: implied_vol} for the relevant expiry
    # For simplicity, keyed by strike. Can extend to {(expiry, strike): vol}.

    def get_vol(self, strike_bps: float) -> float:
        """Look up implied vol for a given strike.

        If exact strike not available, interpolates linearly between
        nearest strikes. Falls back to ATM vol if only one point.
        """
        if not self.vol_surface:
            raise ValueError(f"No vol surface data for {self.family.value}{self.series}")

        if strike_bps in self.vol_surface:
            return self.vol_surface[strike_bps]

        # Linear interpolation
        strikes = sorted(self.vol_surface.keys())

        if len(strikes) == 1:
            return self.vol_surface[strikes[0]]

        if strike_bps <= strikes[0]:
            return self.vol_surface[strikes[0]]
        if strike_bps >= strikes[-1]:
            return self.vol_surface[strikes[-1]]

        # Find bracketing strikes
        for i in range(len(strikes) - 1):
            if strikes[i] <= strike_bps <= strikes[i + 1]:
                lo, hi = strikes[i], strikes[i + 1]
                w = (strike_bps - lo) / (hi - lo)
                return (1 - w) * self.vol_surface[lo] + w * self.vol_surface[hi]

        return self.vol_surface[strikes[0]]  # fallback


@dataclass
class MarketData:
    """Complete market data snapshot for pricing.

    Contains index spreads, vol surfaces, and the discount curve.
    """

    ref_date: dt.date
    discount_curve: DiscountCurve
    indices: dict[tuple[IndexFamily, int], IndexMarketData] = field(
        default_factory=dict
    )

    def add_index(self, data: IndexMarketData) -> None:
        """Add or update market data for an index."""
        self.indices[(data.family, data.series)] = data

    def get_index(self, family: IndexFamily, series: int) -> IndexMarketData:
        """Retrieve market data for a specific index."""
        key = (family, series)
        if key not in self.indices:
            raise KeyError(
                f"No market data for {family.value}{series}. "
                f"Available: {[f'{k[0].value}{k[1]}' for k in self.indices]}"
            )
        return self.indices[key]

    def get_spread(self, family: IndexFamily, series: int) -> float:
        """Get current spread for an index."""
        return self.get_index(family, series).spread_bps

    def get_vol(self, family: IndexFamily, series: int, strike_bps: float) -> float:
        """Get implied vol for an index at a given strike."""
        return self.get_index(family, series).get_vol(strike_bps)

    def copy(self) -> MarketData:
        """Deep copy for scenario analysis."""
        import copy
        return copy.deepcopy(self)

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        ref_date: dt.date,
        risk_free_rate: float = 0.03,
    ) -> MarketData:
        """Build MarketData from a DataFrame.

        Expected columns:
            - index: str (e.g. 'main', 'cdxig')
            - series: int
            - spread: float (current spread in bps)
            - strike: float (option strike in bps, optional)
            - vol: float (implied vol as decimal, optional)

        If strike/vol columns are present, builds a vol surface.
        """
        from .conventions import INDEX_ALIASES

        market = cls(
            ref_date=ref_date,
            discount_curve=DiscountCurve(risk_free_rate),
        )

        for (idx_str, series), group in df.groupby(["index", "series"]):
            idx_code = str(idx_str).lower().strip()
            if idx_code not in INDEX_ALIASES:
                raise ValueError(f"Unknown index code in data: '{idx_code}'")

            family = INDEX_ALIASES[idx_code]
            spread = group["spread"].iloc[0]

            vol_surface = {}
            if "strike" in group.columns and "vol" in group.columns:
                for _, row in group.iterrows():
                    if pd.notna(row.get("strike")) and pd.notna(row.get("vol")):
                        vol_surface[float(row["strike"])] = float(row["vol"])

            market.add_index(IndexMarketData(
                family=family,
                series=int(series),
                spread_bps=float(spread),
                vol_surface=vol_surface,
            ))

        return market

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        ref_date: dt.date | None = None,
        risk_free_rate: float = 0.03,
    ) -> MarketData:
        """Load market data from a CSV file."""
        df = pd.read_csv(path)
        if ref_date is None:
            ref_date = dt.date.today()
        return cls.from_dataframe(df, ref_date, risk_free_rate)

    @classmethod
    def from_excel(
        cls,
        path: str | Path,
        sheet_name: str | int = 0,
        ref_date: dt.date | None = None,
        risk_free_rate: float = 0.03,
    ) -> MarketData:
        """Load market data from an Excel file."""
        df = pd.read_excel(path, sheet_name=sheet_name)
        if ref_date is None:
            ref_date = dt.date.today()
        return cls.from_dataframe(df, ref_date, risk_free_rate)
