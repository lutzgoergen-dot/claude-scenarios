# creditport — Full Project Specification

This document describes the creditport project in enough detail that you could rebuild it from scratch.

## 1. What This Is

A Python library for pricing and risk-managing **credit index options** — specifically options on CDS indices (CDX and iTraxx families). The target user is a portfolio manager or trader who:

- Has a book of credit index options (payers and receivers at various strikes/expiries)
- Needs to price them accurately using Black's model on credit spreads
- Needs Greeks (delta, gamma, vega, theta) for risk management
- Wants to run scenario analysis (what happens if spreads widen 20bp? if vol drops 5 points?)
- Wants Monte Carlo simulation for forward-looking P&L distribution and VaR
- Needs to compute and apply delta hedges using the underlying index
- Receives dealer quotes in Excel and needs to organize them into usable vol surfaces

The library is designed for use in **Jupyter notebooks** — the library provides clean functions and classes, notebooks provide the exploration layer.

## 2. The Indices

Five credit index families are supported:

| Index | Code | Recovery Rate | Fixed Coupon | Currency |
|-------|------|--------------|-------------|----------|
| CDX Investment Grade | `cdxig` / `ig` | 40% | 100bp | USD |
| CDX High Yield | `cdxhy` / `hy` | 20% | 500bp | USD |
| iTraxx Main (Europe IG) | `main` / `itraxxmain` | 40% | 100bp | EUR |
| iTraxx Crossover | `xover` / `crossover` | 40% | 500bp | EUR |
| iTraxx Senior Financials | `snrfin` / `senfin` | 40% | 100bp | EUR |

Each index has a **series number** (e.g., Series 44) and a **maturity** (typically 5Y from the roll date). The standard maturity is the next IMM date (20th of Mar/Jun/Sep/Dec) on or after the roll date + tenor.

Recovery rate, fixed coupon, and currency are defined per index family. These never change series to series — they are structural conventions of the index.

## 3. Position Notation

Positions are described using a compact string notation:

**Options:** `{index}{series} {month}{strike}{p|r}`
- `main44 mar55p` = iTraxx Main Series 44, March expiry, 55bp strike, payer
- `cdxig43 jun80r` = CDX IG Series 43, June expiry, 80bp strike, receiver
- `xover44 sep350p` = iTraxx Crossover Series 44, September expiry, 350bp strike, payer
- Fractional strikes allowed: `main44 mar55.5p`

**Linear index (for hedging):** `{index}{series} {tenor}y`
- `main44 5y` = iTraxx Main Series 44, 5-year index position

Index codes are case-insensitive. Aliases are supported (e.g., `ig43 jun80r` works the same as `cdxig43 jun80r`).

The expiry is always the **3rd Wednesday** of the specified month. If the ref_date is already past that month's 3rd Wednesday, it rolls to the same month in the next year.

## 4. Pricing Model — Black's Model on Credit Spreads

This is the market standard for credit index options. It's Black-76 adapted for CDS:

### Core Formula

**Payer (right to buy protection = benefits from spread widening):**
```
V = RPV01_fwd × [F × N(d1) − K × N(d2)]
```

**Receiver (right to sell protection = benefits from spread tightening):**
```
V = RPV01_fwd × [K × N(-d2) − F × N(-d1)]
```

Where:
- `F` = forward spread (in basis points)
- `K` = strike (in basis points)
- `σ` = Black volatility (decimal, e.g., 0.40 = 40%)
- `T` = time to expiry in years (ACT/365)
- `d1 = [ln(F/K) + 0.5 × σ² × T] / (σ × √T)`
- `d2 = d1 − σ × √T`
- `N()` = standard normal CDF
- `RPV01_fwd` = forward risky PV01 (the annuity from expiry to maturity, discounted back to today)

### What is RPV01?

RPV01 (risky PV01, also called the "annuity" or "risky annuity") is the present value of receiving 1bp per year on the CDS premium leg, accounting for both discounting and the probability of default.

**Spot RPV01** (ref_date → maturity):
```
RPV01_spot = Σ [accrual_i × D(t_i) × Q(t_i)]
```
summed over quarterly IMM payment dates (20th of Mar/Jun/Sep/Dec) strictly after ref_date and up to maturity.

- `accrual_i` = year fraction from previous payment date to this one (ACT/360)
- `D(t_i)` = risk-free discount factor = `exp(-r × t_i)` where t_i is in years from ref_date
- `Q(t_i)` = survival probability = `exp(-λ × t_i)`

**Forward RPV01** (expiry → maturity):
Same formula but only over IMM dates strictly after expiry and up to maturity. **Crucially, D and Q are still measured from ref_date** — this is a spot PV of a forward annuity.

**Annuity decomposition:**
```
spot_rpv01 = front_rpv01 + forward_rpv01
```
where `front_rpv01` covers ref_date → expiry and `forward_rpv01` covers expiry → maturity.

**Important gotcha:** When expiry falls between IMM dates, you cannot compute `front_rpv01` independently (by calling RPV01 with maturity=expiry) and expect it to match `spot - forward`. The independent calculation misses the mid-period accrual for the coupon period that straddles the expiry. Always use `front = spot - forward` for consistency.

### Credit Curve

Flat hazard rate model:
```
hazard_rate (λ) = spread / (1 - recovery_rate)
```
where spread is in decimal form (60bp = 0.006).

Survival probability: `Q(t) = exp(-λ × t)`

**Key insight:** Lower recovery rate (with the same spread) means a higher (1-R) denominator, which means a *lower* hazard rate, *higher* survival probability, and therefore *higher* RPV01. This is counterintuitive but correct.

### Discount Curve

Flat continuously-compounded rate: `D(t) = exp(-r × t)`

### Forward Spread

Under the flat hazard rate assumption, the forward spread equals the spot spread. This is because the hazard rate is constant, so the "forward" default intensity is the same as the spot intensity.

### Front-End Protection (FEP)

An adjustment for the protection the option buyer gets during the option period:
```
FEP = (1 − R) × Σ [D(t_i) × (Q(t_{i-1}) − Q(t_i))]
```
summed over small time steps during the option period. This compensates the option holder for default risk between now and expiry.

When using FEP-adjusted pricing, the effective forward is adjusted:
```
F_adj = F + FEP / RPV01_fwd
```

### Spread Duration

A `SpreadDuration` container provides all duration measures in one call:
- `spot_rpv01`: Full annuity ref_date → maturity (the index DV01 in annuity terms)
- `forward_rpv01`: Annuity expiry → maturity (the Black model numeraire)
- `front_rpv01`: Annuity ref_date → expiry (= spot − forward, by construction)
- `spot_dv01`: `spot_rpv01 / 10,000` = dollar PV01 per 1bp per unit notional
- `forward_dv01`: `forward_rpv01 / 10,000`
- `remaining_years`: Time from ref_date to maturity

### Implied Volatility

Newton-Raphson solver: given a market price, back out the Black vol that reproduces it. Uses vega (dPrice/dVol) as the derivative for Newton steps.

### Analytical Greeks

Closed-form derivatives of the Black formula:
- **Delta** (dV/dS per 1bp): `RPV01 × N(d1)` for payer, `RPV01 × (N(d1) - 1)` for receiver
- **Gamma** (d²V/dS² per 1bp²): `RPV01 × n(d1) / (F × σ × √T)` (always positive)
- **Vega** (dV/dσ per 1 vol point = 0.01): `RPV01 × F × √T × n(d1) × 0.01` (always positive)
- **Theta** (dV/dt per calendar day): time decay component (typically negative for long options)

These hold RPV01 constant, which is an approximation.

### Numerical Greeks (Bump-and-Reprice)

The preferred method for risk management:
1. Price at base scenario
2. Bump spread up 1bp → reprice (recomputing RPV01 at bumped spread) → delta_up
3. Bump spread down 1bp → reprice → delta_down
4. Delta = (up - down) / 2, Gamma = (up - down - 2×base) / bump²
5. Similarly bump vol and time for vega and theta

This correctly captures that RPV01 itself depends on spread, which analytical Greeks miss. The difference is most pronounced for ITM options.

## 5. Market Data

### Simple Format (CSV/Excel)

For basic use, market data is a flat file:
```csv
index,series,spread,strike,vol,maturity
main,44,60,45,0.52,2031-06-20
main,44,60,50,0.47,2031-06-20
main,44,60,55,0.43,2031-06-20
```

Required columns: `index, series, spread, strike, vol`
Optional: `maturity` (ISO date, e.g. `2031-06-20`)

Multiple rows per index define the vol surface (vol by strike). If `maturity_date` is not provided, calculations fall back to a generic 5Y assumption from ref_date.

### Vol Surface

Stored as `{strike_bps: vol_decimal}`. Interpolation: linear between strikes, flat extrapolation beyond the range. If only one strike is provided, that vol applies to all strikes.

### Dealer Quote Format (Excel)

Real dealer data comes in a richer format with columns:
- Extraction Date, Value Date, Product Type, Ticker, Curve, Strike, Option Type, Expiration Date
- Firm (dealer name)
- Bid/Offer Price Type
- Bid Premium, Offer Premium (cents per 100 notional)
- Bid/Mid/Offer Volatility (percentage — 69.75 = 69.75%, converted to 0.6975 on load)
- Mid Delta, Mid Vega, Mid Theta, Mid Gamma
- Mid Forward Spread, Mid Forward Price
- Mid Reference Spread, Mid Reference Price

**Curve codes** in the Curve column identify the index:
| Code | Index | Mnemonic |
|------|-------|----------|
| ITXEB5{series} | iTraxx Main | B = Broad |
| ITXEX5{series} | iTraxx Crossover | X = Crossover |
| ITXES5{series} | iTraxx Senior Financials | S = Senior |
| CDXIG5{series} | CDX IG | |
| CDXHY5{series} | CDX HY | |

The "5" is the tenor (5Y). Digits after are the series. Examples: `ITXEB544` = Main S44, `CDXIG543` = CDX IG S43.

Custom curve codes can be registered at runtime.

### Quote Processing Pipeline

1. **Load** raw quotes from Excel/CSV → list of `OptionQuote` objects
2. **Build grids** → group by (IndexFamily, series) into `QuoteGrid` objects
3. **Set common reference**: median of all dealer ref spreads becomes `common_ref_spread`; median of all dealer fwd spreads per expiry becomes `common_fwd_spreads`
4. **View grids**: `to_vol_grid()` shows mid vol per dealer at each strike; `to_price_grid()` shows bid/ask/mid per dealer
5. **Extract vol surface**: `composite_vol_surface()` takes mean mid vol across dealers at each strike → `{strike: vol}` dict suitable for pricing
6. **Convert to MarketData**: `quotes_to_market_data()` builds a complete `MarketData` object from dealer quotes

## 6. Portfolio

A portfolio holds a list of `CreditIndexOption` and `CreditIndex` positions, each with a notional.

**Pricing linear index positions:**
```
value = (spread - fixed_coupon) × rpv01 × notional / 10000
```
The index has a fixed coupon (100bp for IG, 500bp for HY). The value reflects whether the index is trading wide or tight of its coupon.

**Pricing options:** Full bump-and-reprice using Black's model.

**Greeks table:** A DataFrame with columns `label, notional, mv, price_unit, delta, gamma, vega, theta` plus a TOTAL row summing the Greeks.

Positive notional = long the instrument. Positive delta on a payer = makes money when spreads widen.

## 7. Scenario Analysis

The scenario engine takes a portfolio + market data and applies shocks:

- **Parallel shift**: shift all index spreads by [-20, -10, 0, +10, +20] bp (or custom)
- **Spread-vol matrix**: 2D grid of spread shifts × vol shifts → P&L at each point
- **Time decay**: roll forward N days with no spread/vol change → theta P&L
- **Custom scenario**: per-index spread shifts (e.g., Main -10bp, Xover +30bp)

Each scenario creates a copy of market data, applies the shocks, reprices the portfolio, and returns the P&L vs base.

## 8. Monte Carlo Simulation

GBM (geometric Brownian motion) on credit spreads:
```
ln(S_{t+dt}) = ln(S_t) + (μ − 0.5σ²) × dt + σ × √dt × Z
```

Where Z ~ N(0,1). This gives lognormal spread paths (spreads stay positive).

Configuration: number of paths, horizon in days, time step, seed for reproducibility, optional drift.

At the horizon, each path's terminal spread is used to reprice the portfolio → P&L distribution.

Results include: mean P&L, std, VaR at 95%/99%, CVaR (expected shortfall), full distribution histogram.

Optional: correlation matrix (Cholesky decomposition) for multi-index simulation, per-index vol overrides.

## 9. Delta Hedging

Computes the notional of the underlying index needed to zero out portfolio delta:
```
hedge_notional = −portfolio_delta / (RPV01 / 10,000)
```

Takes a hedge instrument string (e.g., "main44 5y"), computes the RPV01 of that index, and determines how much notional to trade. Can be applied directly to the portfolio (adds the hedge position).

## 10. Date Conventions

- **IMM dates**: 20th of Mar, Jun, Sep, Dec (CDS standard payment dates)
- **Option expiry**: 3rd Wednesday of the month
- **Year fractions**: ACT/360 for accrual calculations (CDS standard), ACT/365 for time-to-expiry
- **Quarterly payments**: CDS indices pay quarterly on IMM dates
- **Standard maturity**: Next IMM date on or after (roll_date + tenor_years)

## 11. Architecture

### Module Dependency Chain
```
conventions (no deps)        → defines IndexFamily, OptionType, recovery/coupon/currency
dates (no deps)              → IMM schedules, 3rd Wednesday, year fractions
curves (← conventions, dates) → discount/credit curves, RPV01, spread duration, FEP
black (← conventions)         → Black's model pricing, implied vol, analytical greeks
instruments (← conventions)   → CreditIndex, CreditIndexOption dataclasses
parsing (← conventions, dates, instruments) → position string parser
market (← conventions, curves) → MarketData container, vol surface
greeks (← black, conventions, curves, instruments) → numerical + analytical greeks
portfolio (← black, conventions, curves, greeks, instruments, market, parsing) → portfolio pricing
scenarios (← conventions, market, portfolio) → scenario engine
montecarlo (← conventions, market, portfolio) → Monte Carlo simulator
hedging (← conventions, curves, instruments, market, portfolio, parsing) → delta hedge
quotes (← conventions, curves, market) → dealer quote loading
```

### Code Style
- Python 3.10+ (uses `X | Y` union syntax for types, not `Optional[X]`)
- Type hints on all public function signatures
- `@dataclass` for all data containers
- Spreads: **basis points** in all external APIs; converted to decimals internally
- Notional: raw numbers (`10_000_000`), not scaled
- Volatility: decimal form in the library (0.40 = 40%); dealer quotes in percentage are converted on load
- Positive notional = long the instrument

### Testing Approach
- Test files mirror source modules
- Test **economic properties** rather than exact numbers where possible:
  - Put-call parity holds
  - Payer delta is positive, receiver delta is negative
  - Higher vol → higher price
  - RPV01 decreases with wider spreads
  - Payer profits from spread widening
- Use `pytest.approx()` for floating-point comparisons
- Fixtures for reusable market data snapshots

## 12. Dependencies

Runtime: `numpy`, `scipy` (for `norm` CDF/PDF), `pandas`, `openpyxl` (Excel reading), `matplotlib`
Dev: `pytest`, `pytest-cov`, `jupyter`, `ipykernel`

## 13. What's Not Yet Built

- **Historical backtesting**: defining historical strategies and seeing how they'd have performed
- **Vol surface calibration**: fitting a parametric vol surface to dealer quotes (beyond simple composite mid)
- **Re-normalization to common reference**: adjusting all dealer quotes to a single reference spread before comparing. The `common_ref_spread` field exists but the actual re-pricing logic (repricing each dealer's quotes at the common ref) is not yet implemented.
- **Notebook walkthrough for dealer quotes workflow**
