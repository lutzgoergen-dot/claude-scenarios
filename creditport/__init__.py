"""creditport: Credit index options pricing, scenario analysis, and portfolio management.

Quick start:
    from creditport import Portfolio, MarketData, ScenarioEngine, MonteCarlo

    market = MarketData.from_csv("market_data.csv", ref_date=date(2026, 2, 7))

    port = Portfolio()
    port.add("main44 mar55p", notional=10_000_000)
    port.add("main44 5y", notional=2_000_000)

    print(port.summary(market))

    engine = ScenarioEngine(market, port)
    results = engine.parallel_shift()
"""

from .black import black_price, black_price_with_fep, implied_vol
from .conventions import CONVENTIONS, IndexFamily, OptionType, get_convention
from .curves import CreditCurve, DiscountCurve, compute_front_end_protection, compute_rpv01
from .greeks import Greeks, compute_greeks_analytical, compute_greeks_numerical
from .hedging import apply_delta_hedge, compute_delta_hedge
from .instruments import CreditIndex, CreditIndexOption
from .market import IndexMarketData, MarketData
from .montecarlo import MonteCarlo, MonteCarloConfig, MonteCarloResult
from .parsing import parse_position
from .portfolio import Portfolio
from .scenarios import ScenarioEngine, ScenarioResult

__version__ = "0.1.0"

__all__ = [
    # Core pricing
    "black_price",
    "black_price_with_fep",
    "implied_vol",
    # Curves
    "DiscountCurve",
    "CreditCurve",
    "compute_rpv01",
    "compute_front_end_protection",
    # Conventions
    "IndexFamily",
    "OptionType",
    "CONVENTIONS",
    "get_convention",
    # Instruments
    "CreditIndex",
    "CreditIndexOption",
    # Market data
    "MarketData",
    "IndexMarketData",
    # Portfolio
    "Portfolio",
    # Greeks
    "Greeks",
    "compute_greeks_numerical",
    "compute_greeks_analytical",
    # Scenarios
    "ScenarioEngine",
    "ScenarioResult",
    # Monte Carlo
    "MonteCarlo",
    "MonteCarloConfig",
    "MonteCarloResult",
    # Hedging
    "compute_delta_hedge",
    "apply_delta_hedge",
    # Parsing
    "parse_position",
]
