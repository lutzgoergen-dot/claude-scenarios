"""Discount curves and credit curves for CDS pricing."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

from .dates import imm_schedule, year_fraction


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


def compute_rpv01(
    spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    maturity_years: int = 5,
) -> float:
    """Compute the risky PV01 (annuity) for a CDS index.

    RPV01 = sum over quarterly payment dates of:
        accrual_fraction * discount_factor * survival_probability

    Args:
        spread_bps: Current index spread in basis points.
        recovery_rate: Recovery rate assumption.
        discount_curve: Risk-free discount curve.
        ref_date: Valuation date.
        maturity_years: Tenor of the index (default 5Y).

    Returns:
        RPV01 in annualized terms (multiply by notional to get dollar DV01).
    """
    credit = CreditCurve(spread_bps, recovery_rate)
    schedule = imm_schedule(ref_date, maturity_years)

    rpv01 = 0.0
    prev_date = ref_date
    for pay_date in schedule:
        accrual = year_fraction(prev_date, pay_date, "ACT/360")
        t = (pay_date - ref_date).days / 365.0
        df = discount_curve.df(t)
        surv = credit.survival(t)
        rpv01 += accrual * df * surv
        prev_date = pay_date

    return rpv01


def compute_forward_spread(
    spot_spread_bps: float,
    recovery_rate: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    expiry: dt.date,
    maturity_years: int = 5,
) -> float:
    """Compute the forward spread for a CDS index starting at expiry.

    The forward spread is approximately equal to the spot spread for
    short-dated options. For longer-dated options, we adjust for the
    difference in annuity.

    For simplicity and market convention, we use the approximation:
        F ≈ S (spot spread)

    This is standard for credit index options where the option expiry
    is much shorter than the index tenor.
    """
    # For a more precise calculation, one would compute:
    # F = (RPV01_full - RPV01_front) / RPV01_back * S
    # But the spot ≈ forward approximation is standard for short-dated options
    return spot_spread_bps


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
