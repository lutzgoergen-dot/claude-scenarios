"""Monte Carlo simulation for credit index spread paths and portfolio P&L."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .conventions import IndexFamily
from .market import MarketData
from .portfolio import Portfolio


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation."""

    n_paths: int = 10_000
    horizon_days: int = 90
    dt_days: int = 1  # time step in days
    seed: int | None = None
    # Spread dynamics: geometric Brownian motion (lognormal spreads)
    # dS/S = mu*dt + sigma*dW
    # mu = 0 (risk-neutral) by default; can set drift for real-world measure
    drift: float = 0.0  # annualized drift of spread


@dataclass
class MonteCarloResult:
    """Results from a Monte Carlo simulation."""

    config: MonteCarloConfig
    # spread_paths: {(family, series): array of shape (n_paths, n_steps+1)}
    spread_paths: dict[tuple[IndexFamily, int], np.ndarray]
    # pnl_paths: array of shape (n_paths,) — terminal P&L per path
    pnl_paths: np.ndarray
    time_grid: np.ndarray  # in days from start

    @property
    def mean_pnl(self) -> float:
        return float(np.mean(self.pnl_paths))

    @property
    def std_pnl(self) -> float:
        return float(np.std(self.pnl_paths))

    @property
    def var_95(self) -> float:
        """5th percentile P&L (95% VaR)."""
        return float(np.percentile(self.pnl_paths, 5))

    @property
    def var_99(self) -> float:
        """1st percentile P&L (99% VaR)."""
        return float(np.percentile(self.pnl_paths, 1))

    @property
    def cvar_95(self) -> float:
        """Conditional VaR (Expected Shortfall) at 95%."""
        threshold = np.percentile(self.pnl_paths, 5)
        tail = self.pnl_paths[self.pnl_paths <= threshold]
        return float(np.mean(tail)) if len(tail) > 0 else threshold

    def percentile(self, q: float) -> float:
        """P&L at a given percentile."""
        return float(np.percentile(self.pnl_paths, q))

    def pnl_distribution(self, bins: int = 50) -> pd.DataFrame:
        """P&L distribution as a DataFrame for plotting."""
        counts, edges = np.histogram(self.pnl_paths, bins=bins)
        centers = (edges[:-1] + edges[1:]) / 2
        return pd.DataFrame({"pnl": centers, "count": counts, "freq": counts / len(self.pnl_paths)})

    def summary(self) -> dict[str, float]:
        return {
            "mean_pnl": self.mean_pnl,
            "std_pnl": self.std_pnl,
            "median_pnl": float(np.median(self.pnl_paths)),
            "var_95": self.var_95,
            "var_99": self.var_99,
            "cvar_95": self.cvar_95,
            "min_pnl": float(np.min(self.pnl_paths)),
            "max_pnl": float(np.max(self.pnl_paths)),
            "n_paths": len(self.pnl_paths),
        }

    def summary_df(self) -> pd.DataFrame:
        s = self.summary()
        return pd.DataFrame([s])


class MonteCarlo:
    """Monte Carlo simulator for credit index portfolios.

    Simulates spread paths using geometric Brownian motion (lognormal spreads),
    then re-prices the portfolio at the horizon to compute the P&L distribution.

    Usage:
        mc = MonteCarlo(market, portfolio, config=MonteCarloConfig(n_paths=10000))
        result = mc.run()
        print(result.summary())
    """

    def __init__(
        self,
        market: MarketData,
        portfolio: Portfolio,
        config: MonteCarloConfig | None = None,
    ):
        self.market = market
        self.portfolio = portfolio
        self.config = config or MonteCarloConfig()

    def run(
        self,
        vol_overrides: dict[tuple[IndexFamily, int], float] | None = None,
        correlation_matrix: np.ndarray | None = None,
    ) -> MonteCarloResult:
        """Run the Monte Carlo simulation.

        Args:
            vol_overrides: Override simulation vol per index {(family, series): vol}.
                          If None, uses ATM implied vol from market data.
            correlation_matrix: Correlation matrix between indices. If None,
                              assumes independent (identity matrix).

        Returns:
            MonteCarloResult with spread paths and P&L distribution.
        """
        cfg = self.config
        rng = np.random.default_rng(cfg.seed)

        n_steps = cfg.horizon_days // cfg.dt_days
        dt_years = cfg.dt_days / 365.0

        # Identify unique indices in the portfolio
        index_keys = []
        for pos in self.portfolio.positions:
            key = (pos.family, pos.series)
            if key not in index_keys:
                index_keys.append(key)

        n_indices = len(index_keys)

        # Get initial spreads and vols for each index
        initial_spreads = []
        sim_vols = []
        for key in index_keys:
            idx_data = self.market.get_index(*key)
            initial_spreads.append(idx_data.spread_bps)

            if vol_overrides and key in vol_overrides:
                sim_vols.append(vol_overrides[key])
            else:
                # Use ATM vol (vol at current spread)
                sim_vols.append(idx_data.get_vol(idx_data.spread_bps))

        initial_spreads = np.array(initial_spreads)
        sim_vols = np.array(sim_vols)

        # Generate correlated random numbers
        if correlation_matrix is not None:
            L = np.linalg.cholesky(correlation_matrix)
            Z = rng.standard_normal((cfg.n_paths, n_steps, n_indices))
            Z = Z @ L.T
        else:
            Z = rng.standard_normal((cfg.n_paths, n_steps, n_indices))

        # Simulate GBM paths for each index
        # ln(S_{t+dt}) = ln(S_t) + (mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z
        spread_paths = {}
        all_paths = np.zeros((cfg.n_paths, n_steps + 1, n_indices))
        all_paths[:, 0, :] = initial_spreads

        for step in range(n_steps):
            for j in range(n_indices):
                log_drift = (cfg.drift - 0.5 * sim_vols[j] ** 2) * dt_years
                log_diffusion = sim_vols[j] * np.sqrt(dt_years) * Z[:, step, j]
                all_paths[:, step + 1, j] = all_paths[:, step, j] * np.exp(
                    log_drift + log_diffusion
                )

        # Store paths per index
        for j, key in enumerate(index_keys):
            spread_paths[key] = all_paths[:, :, j]

        # Time grid
        time_grid = np.arange(0, n_steps + 1) * cfg.dt_days

        # Compute terminal P&L for each path
        base_results = self.portfolio.price(self.market)
        base_mv = sum(r.market_value for r in base_results)

        pnl_paths = np.zeros(cfg.n_paths)
        for path_idx in range(cfg.n_paths):
            # Create shocked market with terminal spreads
            shocked = self.market.copy()
            shocked.ref_date = shocked.ref_date + dt.timedelta(days=cfg.horizon_days)

            for j, key in enumerate(index_keys):
                terminal_spread = all_paths[path_idx, -1, j]
                if key in shocked.indices:
                    shocked.indices[key].spread_bps = float(terminal_spread)

            path_results = self.portfolio.price(shocked)
            path_mv = sum(r.market_value for r in path_results)
            pnl_paths[path_idx] = path_mv - base_mv

        return MonteCarloResult(
            config=cfg,
            spread_paths=spread_paths,
            pnl_paths=pnl_paths,
            time_grid=time_grid,
        )
