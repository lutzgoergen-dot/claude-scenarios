"""Scenario engine: parallel shifts, custom shocks, and P&L analysis."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

from .conventions import IndexFamily
from .market import MarketData
from .portfolio import Portfolio


@dataclass
class ScenarioResult:
    """Result of a single scenario."""

    name: str
    spread_shift_bps: float
    vol_shift: float
    time_shift_days: int
    portfolio_mv: float
    pnl: float
    position_details: pd.DataFrame


@dataclass
class ScenarioEngine:
    """Run scenarios on a portfolio against market data.

    Usage:
        engine = ScenarioEngine(market, portfolio)
        results = engine.parallel_shift(spread_shifts=[-20, -10, 0, 10, 20])
        results_df = engine.results_table(results)
    """

    market: MarketData
    portfolio: Portfolio

    def parallel_shift(
        self,
        spread_shifts: Sequence[float] = (-20, -10, -5, 0, 5, 10, 20),
        vol_shift: float = 0.0,
        time_shift_days: int = 0,
    ) -> list[ScenarioResult]:
        """Apply parallel spread shifts across all indices.

        Args:
            spread_shifts: List of spread shifts in bps.
            vol_shift: Absolute vol shift (e.g. 0.05 = +5 vol points).
            time_shift_days: Days forward for theta.

        Returns:
            List of ScenarioResult, one per shift.
        """
        results = []
        for shift in spread_shifts:
            result = self._run_scenario(
                name=f"{shift:+.0f}bp",
                spread_shift=shift,
                vol_shift=vol_shift,
                time_shift_days=time_shift_days,
            )
            results.append(result)
        return results

    def spread_vol_matrix(
        self,
        spread_shifts: Sequence[float] = (-20, -10, -5, 0, 5, 10, 20),
        vol_shifts: Sequence[float] = (-0.10, -0.05, 0, 0.05, 0.10),
    ) -> pd.DataFrame:
        """2D scenario matrix: spread shifts x vol shifts.

        Returns a DataFrame with spread shifts as rows, vol shifts as columns,
        and portfolio P&L as values.
        """
        base_mv = self._base_mv()
        rows = []
        for s_shift in spread_shifts:
            row = {"spread_shift": s_shift}
            for v_shift in vol_shifts:
                result = self._run_scenario(
                    name=f"s{s_shift:+.0f}_v{v_shift:+.2f}",
                    spread_shift=s_shift,
                    vol_shift=v_shift,
                )
                row[f"vol{v_shift:+.2f}"] = result.pnl
            rows.append(row)

        return pd.DataFrame(rows).set_index("spread_shift")

    def time_decay(
        self,
        days: Sequence[int] = (0, 1, 5, 10, 20, 30),
    ) -> list[ScenarioResult]:
        """Time decay scenarios: roll forward by N days, no spread/vol change."""
        results = []
        for d in days:
            result = self._run_scenario(
                name=f"T+{d}d",
                spread_shift=0,
                vol_shift=0,
                time_shift_days=d,
            )
            results.append(result)
        return results

    def custom_scenario(
        self,
        name: str,
        index_shifts: dict[tuple[IndexFamily, int], float] | None = None,
        vol_shift: float = 0.0,
        time_shift_days: int = 0,
    ) -> ScenarioResult:
        """Run a custom scenario with per-index spread shifts.

        Args:
            name: Scenario label.
            index_shifts: {(family, series): shift_bps} for each index.
            vol_shift: Absolute vol shift.
            time_shift_days: Days forward.
        """
        shocked = self.market.copy()

        if index_shifts:
            for (family, series), shift in index_shifts.items():
                if (family, series) in shocked.indices:
                    shocked.indices[(family, series)].spread_bps += shift

        if vol_shift != 0:
            for idx_data in shocked.indices.values():
                idx_data.vol_surface = {
                    k: max(v + vol_shift, 0.01)
                    for k, v in idx_data.vol_surface.items()
                }

        if time_shift_days != 0:
            shocked.ref_date = shocked.ref_date + dt.timedelta(days=time_shift_days)

        base_mv = self._base_mv()
        details = self.portfolio.greeks_table(shocked)
        scenario_mv = details[details["label"] != "TOTAL"]["mv"].sum()

        return ScenarioResult(
            name=name,
            spread_shift_bps=0,  # custom
            vol_shift=vol_shift,
            time_shift_days=time_shift_days,
            portfolio_mv=scenario_mv,
            pnl=scenario_mv - base_mv,
            position_details=details,
        )

    def results_table(self, results: list[ScenarioResult]) -> pd.DataFrame:
        """Convert scenario results to a summary DataFrame."""
        rows = [
            {
                "scenario": r.name,
                "spread_shift": r.spread_shift_bps,
                "vol_shift": r.vol_shift,
                "time_shift": r.time_shift_days,
                "portfolio_mv": r.portfolio_mv,
                "pnl": r.pnl,
            }
            for r in results
        ]
        return pd.DataFrame(rows)

    def _run_scenario(
        self,
        name: str,
        spread_shift: float,
        vol_shift: float,
        time_shift_days: int = 0,
    ) -> ScenarioResult:
        """Run a single scenario with parallel shifts."""
        shocked = self.market.copy()

        # Shift all spreads
        if spread_shift != 0:
            for idx_data in shocked.indices.values():
                idx_data.spread_bps = max(idx_data.spread_bps + spread_shift, 0.5)

        # Shift all vols
        if vol_shift != 0:
            for idx_data in shocked.indices.values():
                idx_data.vol_surface = {
                    k: max(v + vol_shift, 0.01)
                    for k, v in idx_data.vol_surface.items()
                }

        # Shift time
        if time_shift_days != 0:
            shocked.ref_date = shocked.ref_date + dt.timedelta(days=time_shift_days)

        base_mv = self._base_mv()
        details = self.portfolio.greeks_table(shocked)
        scenario_mv = details[details["label"] != "TOTAL"]["mv"].sum()

        return ScenarioResult(
            name=name,
            spread_shift_bps=spread_shift,
            vol_shift=vol_shift,
            time_shift_days=time_shift_days,
            portfolio_mv=scenario_mv,
            pnl=scenario_mv - base_mv,
            position_details=details,
        )

    def _base_mv(self) -> float:
        """Compute base (unshocked) portfolio market value."""
        details = self.portfolio.greeks_table(self.market)
        return details[details["label"] != "TOTAL"]["mv"].sum()
