# CLAUDE.md — creditport

## What This Project Is

A Python library for **credit index options** pricing, portfolio management, scenario analysis, and Monte Carlo simulation. Covers CDX IG, CDX HY, iTraxx Main, iTraxx Crossover, and iTraxx Senior Financials.

Built for interactive use in Jupyter notebooks — the library (`creditport/`) provides clean functions and classes, notebooks provide the exploration layer.

## Repository Layout

```
creditport/              # Core library (the package)
├── __init__.py          # Public API — all exports
├── conventions.py       # Index definitions: recovery rates, coupons, currencies
├── dates.py             # 3rd Wednesday expiry, IMM schedules, year fractions
├── curves.py            # Discount curve, credit curve, RPV01, front-end protection
├── black.py             # Black's model: pricing, implied vol, analytical greeks
├── instruments.py       # CreditIndex and CreditIndexOption dataclasses
├── parsing.py           # Position string parser ("main44 mar55p" → instrument)
├── market.py            # MarketData container, CSV/Excel loaders, vol surface
├── portfolio.py         # Portfolio: holds positions, prices them, greeks table
├── greeks.py            # Numerical (bump-and-reprice) and analytical greeks
├── scenarios.py         # Scenario engine: parallel shifts, 2D matrices, time decay
├── montecarlo.py        # Monte Carlo: GBM spread paths, P&L distribution, VaR
└── hedging.py           # Delta hedge computation and application

tests/                   # pytest test suite
├── test_black.py        # Black model: put-call parity, boundary cases, greeks signs
├── test_curves.py       # Discount/credit curves, RPV01, front-end protection
├── test_parsing.py      # Position string parsing, all index codes, edge cases
├── test_portfolio.py    # Portfolio pricing, greeks table structure
└── test_scenarios.py    # Scenario engine: parallel shifts, time decay

notebooks/
└── demo.ipynb           # Full walkthrough: load data → price → hedge → scenarios → MC

data/examples/
└── sample_market.csv    # Example market data snapshot

pyproject.toml           # Build config, dependencies, pytest settings
requirements.txt         # Flat dependency list
```

## Key Design Decisions

### Pricing Model
- **Black's model on credit spreads** (Black-76 adapted for CDS). This is the market standard for credit index options.
- RPV01 (risky PV01 / annuity) serves as the forward measure numeraire.
- Flat hazard rate assumption for credit curve construction.
- Front-end protection adjustment available via `black_price_with_fep()`.

### Recovery Rates and Coupons
Defined in `conventions.py`:
| Index | Recovery | Fixed Coupon | Currency |
|-------|----------|-------------|----------|
| CDX IG | 40% | 100bp | USD |
| CDX HY | 20% | 500bp | USD |
| iTraxx Main | 40% | 100bp | EUR |
| iTraxx Crossover | 40% | 500bp | EUR |
| iTraxx SeniorFin | 40% | 100bp | EUR |

### Position Notation
Options: `{index}{series} {month}{strike}{p|r}`
- `main44 mar55p` → iTraxx Main S44, March expiry (3rd Wed), 55bp strike, payer
- `cdxig43 jun80r` → CDX IG S43, June expiry, 80bp strike, receiver

Linear: `{index}{series} {tenor}y`
- `main44 5y` → iTraxx Main S44, 5Y index position (for delta hedging)

Index codes: `main`, `cdxig`, `cdxhy`, `xover`, `snrfin` (plus aliases like `ig`, `hy`, `crossover`)

### Greeks
Two methods available:
1. **Numerical (bump-and-reprice)** — preferred for risk management. Correctly captures RPV01's spread-sensitivity. Used by `portfolio.greeks_table()`.
2. **Analytical (closed-form Black)** — holds RPV01 constant. Faster, useful for cross-checking.

### Market Data
`MarketData` holds a snapshot: ref_date, discount curve, and per-index data (spread + vol surface). Load from CSV/Excel or build programmatically. Vol surface is keyed by strike with linear interpolation.

Expected CSV columns: `index, series, spread, strike, vol`

## Development Workflow

### Setup
```bash
pip install -e ".[dev]"
```

### Running Tests
```bash
pytest                    # all tests
pytest tests/test_black.py  # single module
pytest -v                 # verbose
pytest -k "parity"        # filter by name
```

### Adding a New Feature
1. Add the implementation to the appropriate module in `creditport/`.
2. Export it from `creditport/__init__.py` if it's part of the public API.
3. Add tests in `tests/`.
4. Run `pytest` to verify.

### Code Style
- Python 3.10+ (uses `X | Y` union syntax, not `Optional[X]`).
- Type hints on all public function signatures.
- Dataclasses for data containers (`@dataclass`).
- Spreads are always in **basis points** in external APIs; converted to decimals internally where needed.
- Notional is always a raw number (e.g. `10_000_000`), not scaled.
- Positive notional = long the instrument.

## Architecture Notes

### Module Dependencies (import order)
```
conventions (no internal deps)
    ↓
dates (no internal deps)
    ↓
curves (← conventions, dates)
    ↓
black (← conventions)
    ↓
instruments (← conventions)
    ↓
parsing (← conventions, dates, instruments)
    ↓
market (← conventions, curves)
    ↓
greeks (← black, conventions, curves, instruments)
    ↓
portfolio (← black, conventions, curves, greeks, instruments, market, parsing)
    ↓
scenarios (← conventions, market, portfolio)
    ↓
montecarlo (← conventions, market, portfolio)
    ↓
hedging (← conventions, curves, instruments, market, portfolio, parsing)
```

### Key Formulas

**RPV01:**
`RPV01 = Σ (accrual_i × D(t_i) × Q(t_i))` over quarterly IMM dates

**Black's model (payer):**
`V = RPV01 × [F × N(d1) − K × N(d2)]`
where `d1 = [ln(F/K) + ½σ²T] / (σ√T)`, `d2 = d1 − σ√T`

**Front-end protection:**
`FEP = (1−R) × Σ [D(t_i) × (Q(t_{i-1}) − Q(t_i))]` over the option period

**Delta hedge notional:**
`hedge_notional = −portfolio_delta / (RPV01 / 10000)`

## Common Tasks

### Price a single option
```python
from creditport import black_price, OptionType, compute_rpv01, DiscountCurve
import datetime as dt

rpv01 = compute_rpv01(60, 0.40, DiscountCurve(0.03), dt.date(2026, 2, 7))
price = black_price(60, 55, 0.43, 0.3, rpv01, OptionType.PAYER, notional=10e6)
```

### Build and price a portfolio
```python
from creditport import Portfolio, MarketData

market = MarketData.from_csv("data/examples/sample_market.csv", ref_date=...)
port = Portfolio(ref_date=...)
port.add("main44 jun55p", notional=10_000_000)
port.add("main44 jun70p", notional=-10_000_000)
print(port.summary(market))
```

### Run scenarios
```python
from creditport import ScenarioEngine

engine = ScenarioEngine(market, port)
results = engine.parallel_shift(spread_shifts=[-20, -10, 0, 10, 20])
matrix = engine.spread_vol_matrix()  # 2D spread × vol grid
```

### Delta hedge
```python
from creditport import apply_delta_hedge

hedge = apply_delta_hedge(port, market, "main44 5y")
print(f"Hedge notional: {hedge.hedge_notional:,.0f}")
```

### Monte Carlo
```python
from creditport import MonteCarlo, MonteCarloConfig

mc = MonteCarlo(market, port, MonteCarloConfig(n_paths=10000, horizon_days=90, seed=42))
result = mc.run()
print(result.summary())
```

## Gotchas and Edge Cases

- **Spreads must be positive.** The Black model uses `ln(F/K)`, so zero/negative spreads will raise errors.
- **Expiry resolution** is relative to `ref_date`. If `ref_date` is after a month's 3rd Wednesday, the expiry rolls to the next year's same month. Always set `ref_date` on the Portfolio or pass it to `parse_position`.
- **Vol surface interpolation** is linear between strikes, flat extrapolation beyond the range. If only one strike is provided, that vol is used for all strikes.
- **Monte Carlo is path-by-path repricing** — accurate but computationally expensive for large portfolios. Use `seed` for reproducibility.
- **RPV01 depends on spread** — this is why numerical (bump-and-reprice) greeks differ from analytical greeks, especially for ITM options.

## Testing Conventions

- Test files mirror source modules: `test_black.py` tests `black.py`.
- Tests verify economic properties (put-call parity, monotonicity, sign of greeks) rather than exact numerical values where possible.
- Use `pytest.approx()` for floating point comparisons.
- The `sample_market` fixture in `test_portfolio.py` and `test_scenarios.py` provides a reusable market snapshot.

## Dependencies

Runtime: `numpy`, `scipy`, `pandas`, `openpyxl`, `matplotlib`
Dev: `pytest`, `pytest-cov`, `jupyter`, `ipykernel`
