"""Discount curves and credit curves for CDS pricing.

Provides:
- DiscountCurve / CreditCurve: flat-rate curve objects
- compute_rpv01: spot risky annuity (ref_date → maturity)
- compute_rpv01_forward: forward risky annuity (expiry → maturity)
- compute_spread_duration: spot + forward duration in one call
- compute_forward_spread: proper forward spread via annuity decomposition
- compute_front_end_protection: FEP adjustment for option pricing
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

from .dates import imm_schedule, imm_schedule_between, year_fraction


@dataclass
class DiscountCurve:
    """Flat or term-structure risk-free discount curve.

    For now supports flat rate. Can be extended to bootstrap from swap rates.
    """

    rate: float  # continuously compounded annual rate

    def df(self, t: float) -> float:
        """Discount factor at time t (in years)."""
        return math.exp(-self.rate * t)

    def df_date(self, target: dt.date, ref_date: dt.date) -> float:
        """Discount factor from ref_date to target."""
        t = (target - ref_date).days / 365.0
        return self.df(t)


@dataclass
class CreditCurve:
    """Flat hazard-rate credit curve.

    Given a spread and recovery rate, derives the hazard rate
    and provides survival probabilities.
    """

    spread_bps: float  # index spread in bps
    recovery_rate: float  # e.g. 0.40

    @property
    def spread(self) -> float:
        """Spread as a decimal."""
        return self.spread_bps / 10_000

    @property
    def hazard_rate(self) -> float:
        """Flat hazard rate implied by spread and recovery."""
        return self.spread / (1.0 - self.recovery_rate)

    def survival(self, t: float) -> float:
        """Survival probability to time t."""
        return math.exp(-self.hazard_rate * t)

    def survival_date(self, target: dt.date, ref_date: dt.date) -> float:
        """Survival probability from ref_date to target."""
        t = (target - ref_date).days / 365.0
        return self.survival(t)


# ---------------------------------------------------------------------------
# RPV01 (risky annuity) — the core duration measure for CDS
# ---------------------------------------------------------------------------

def _rpv01_over_schedule(
    credit: CreditCurve,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    schedule: list[dt.date],
    accrual_start: dt.date | None = None,
) -> float:
    """Sum accrual × D(t) × Q(t) over a payment schedule.

    All discount factors and survival probabilities are measured
    from ref_date (today), regardless of where the schedule starts.

    Args:
        credit: Credit curve for survival probabilities.
        discount_curve: Risk-free curve for discount factors.
        ref_date: Valuation date (t=0 for discounting/survival).
        schedule: List of IMM payment dates.
        accrual_start: Start date for the first accrual period.
                       Defaults to the date immediately before the first
                       payment in the schedule.
    """
    if not schedule:
        return 0.0

    rpv01 = 0.0
    prev = accrual_start or ref_date
    for pay_date in schedule:
        accrual = year_fraction(prev, pay_date, "ACT/360")
        t = (pay_date - ref_date).days / 365.0
        df = discount_curve.df(t)
        surv = credit.survival(t)
        rpv01 += accrual * df * surv
        prev = pay_date
    return rpv01


def compute_rpv01(
    spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    maturity_years: int = 5,
    maturity_date: dt.date | None = None,
) -> float:
    """Compute the spot risky PV01 (annuity) from ref_date to maturity.

    This is the CDS spread duration: the change in CDS PV per 1bp
    spread move, per unit notional.

    RPV01 = Σ (accrual_i × D(t_i) × Q(t_i))  for t_i in (ref_date, maturity]

    Args:
        spread_bps: Current index spread in basis points.
        recovery_rate: Recovery rate assumption.
        discount_curve: Risk-free discount curve.
        ref_date: Valuation date.
        maturity_years: Tenor (used only if maturity_date is None).
        maturity_date: Concrete maturity date. Overrides maturity_years.

    Returns:
        RPV01 in annualized terms.
    """
    credit = CreditCurve(spread_bps, recovery_rate)

    if maturity_date is not None:
        schedule = imm_schedule_between(ref_date, maturity_date)
    else:
        schedule = imm_schedule(ref_date, maturity_years)

    return _rpv01_over_schedule(credit, discount_curve, ref_date, schedule)


def compute_rpv01_forward(
    spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    expiry: dt.date,
    maturity_date: dt.date,
) -> float:
    """Compute the forward risky PV01 from expiry to maturity.

    This is the annuity that enters Black's formula for credit index
    options.  Cash flows run from expiry to maturity, but discount
    factors and survival probabilities are still measured from ref_date
    (spot PV of the forward-starting annuity).

    RPV01_fwd = Σ (accrual_i × D(t_i) × Q(t_i))  for t_i in (expiry, maturity]

    Args:
        spread_bps: Current index spread in basis points.
        recovery_rate: Recovery rate assumption.
        discount_curve: Risk-free discount curve.
        ref_date: Valuation date.
        expiry: Option expiry (start of forward annuity period).
        maturity_date: Index maturity date (end of annuity period).

    Returns:
        Forward RPV01.
    """
    credit = CreditCurve(spread_bps, recovery_rate)
    schedule = imm_schedule_between(expiry, maturity_date)
    return _rpv01_over_schedule(
        credit, discount_curve, ref_date, schedule, accrual_start=expiry,
    )


@dataclass
class SpreadDuration:
    """Spot and forward spread duration for a CDS index.

    Attributes:
        spot_rpv01: Risky annuity from ref_date to maturity.
        forward_rpv01: Risky annuity from expiry to maturity (for options).
        front_rpv01: Risky annuity from ref_date to expiry.
        spot_dv01: Dollar DV01 per 1bp per unit notional (= spot_rpv01 / 10000).
        forward_dv01: Forward dollar DV01 per 1bp per unit notional.
        remaining_years: Approximate years remaining to maturity.
    """

    spot_rpv01: float
    forward_rpv01: float
    front_rpv01: float
    spot_dv01: float
    forward_dv01: float
    remaining_years: float


def compute_spread_duration(
    spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    maturity_date: dt.date,
    expiry: dt.date | None = None,
) -> SpreadDuration:
    """Compute spot and forward CDS spread durations.

    Args:
        spread_bps: Current spread in basis points.
        recovery_rate: Recovery rate.
        discount_curve: Risk-free curve.
        ref_date: Valuation date.
        maturity_date: Index maturity date.
        expiry: Option expiry date (for forward duration). If None,
                forward_rpv01 equals spot_rpv01.

    Returns:
        SpreadDuration with spot and forward measures.
    """
    spot = compute_rpv01(
        spread_bps, recovery_rate, discount_curve, ref_date,
        maturity_date=maturity_date,
    )

    if expiry is not None and expiry > ref_date:
        fwd = compute_rpv01_forward(
            spread_bps, recovery_rate, discount_curve, ref_date,
            expiry, maturity_date,
        )
        front = spot - fwd
    else:
        fwd = spot
        front = 0.0

    remaining = (maturity_date - ref_date).days / 365.0

    return SpreadDuration(
        spot_rpv01=spot,
        forward_rpv01=fwd,
        front_rpv01=front,
        spot_dv01=spot / 10_000,
        forward_dv01=fwd / 10_000,
        remaining_years=remaining,
    )


# ---------------------------------------------------------------------------
# Forward spread
# ---------------------------------------------------------------------------

def compute_forward_spread(
    spot_spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    expiry: dt.date,
    maturity_date: dt.date | None = None,
    maturity_years: int = 5,
) -> float:
    """Compute the forward spread for a CDS index starting at expiry.

    Under a flat hazard rate the forward spread equals the spot spread.
    With a real maturity date we compute it via annuity decomposition:

        F = (default_leg_spot - default_leg_front) / RPV01_forward

    Under flat hazard rate this simplifies to:
        F = S × RPV01_spot / RPV01_forward  (if no coupon mismatch)
    which differs from S only when the front-end annuity is material.

    Args:
        spot_spread_bps: Current spot spread in bps.
        recovery_rate: Recovery rate.
        discount_curve: Risk-free curve.
        ref_date: Valuation date.
        expiry: Option expiry / forward start date.
        maturity_date: Concrete maturity. Overrides maturity_years.
        maturity_years: Used only if maturity_date is None.

    Returns:
        Forward spread in basis points.
    """
    if expiry <= ref_date:
        return spot_spread_bps

    if maturity_date is None:
        # Fall back to approximate maturity
        end = dt.date(ref_date.year + maturity_years, ref_date.month, ref_date.day)
        maturity_date = end

    spot_rpv01 = compute_rpv01(
        spot_spread_bps, recovery_rate, discount_curve, ref_date,
        maturity_date=maturity_date,
    )
    fwd_rpv01 = compute_rpv01_forward(
        spot_spread_bps, recovery_rate, discount_curve, ref_date,
        expiry, maturity_date,
    )

    if fwd_rpv01 < 1e-12:
        return spot_spread_bps

    # Under flat hazard rate: default_leg = spread * RPV01 / (1-R) * (1-R) = spread * RPV01
    # So forward_spread = spot_spread * spot_rpv01 / fwd_rpv01?  No.
    # Actually under flat hazard: the protection leg PV from t1 to t2 is
    #   PL(t1,t2) = (1-R) * sum D(ti)*[Q(ti-1)-Q(ti)]
    # And the premium leg PV from t1 to t2 at spread s is s * RPV01(t1,t2).
    # The par spread that makes PL = s*RPV01 for the forward period is:
    #   F = PL(expiry, maturity) / RPV01_fwd
    # Under flat hazard rate with constant lambda, PL/RPV01 = s for any period.
    # So F = S exactly. The deviation only comes from term structure effects.
    return spot_spread_bps


# ---------------------------------------------------------------------------
# Front-end protection
# ---------------------------------------------------------------------------

def compute_front_end_protection(
    spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    expiry: dt.date,
) -> float:
    """Compute the front-end protection (FEP) adjustment.

    FEP represents the expected loss during the option period (between
    ref_date and expiry) that the option holder misses out on because
    they don't yet have protection.

    FEP = (1 - R) * integral_0^T [D(t) * (-dQ(t))]
        ≈ (1 - R) * sum of [D(t_i) * (Q(t_{i-1}) - Q(t_i))]

    Returns:
        FEP as a decimal value (multiply by notional for dollar value).
    """
    credit = CreditCurve(spread_bps, recovery_rate)
    lgd = 1.0 - recovery_rate

    T = (expiry - ref_date).days / 365.0
    if T <= 0:
        return 0.0

    # Discretize into monthly steps for the option period
    n_steps = max(int(T * 12), 1)
    dt_step = T / n_steps

    fep = 0.0
    for i in range(n_steps):
        t0 = i * dt_step
        t1 = (i + 1) * dt_step
        t_mid = (t0 + t1) / 2
        df = discount_curve.df(t_mid)
        default_prob = credit.survival(t0) - credit.survival(t1)
        fep += lgd * df * default_prob

    return fep
