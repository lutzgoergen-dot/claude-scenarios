"""Black's model for credit index options pricing.

The standard market model for credit index options applies Black's formula
to credit spreads, using the risky PV01 (annuity) as numeraire.

Payer option  = right to buy protection at strike K  (profits from widening)
Receiver option = right to sell protection at strike K (profits from tightening)

V_payer    = RPV01 * [F * N(d1) - K * N(d2)]
V_receiver = RPV01 * [K * N(-d2) - F * N(-d1)]

where:
    F  = forward spread (≈ spot spread for short-dated options)
    K  = strike spread
    σ  = lognormal implied volatility of the spread
    T  = time to expiry (years)
    d1 = [ln(F/K) + 0.5 * σ² * T] / (σ * √T)
    d2 = d1 - σ * √T
"""

from __future__ import annotations

import math

from scipy.stats import norm

from .conventions import OptionType


def _d1d2(
    forward_bps: float, strike_bps: float, vol: float, T: float
) -> tuple[float, float]:
    """Compute d1 and d2 for Black's formula."""
    if T <= 0 or vol <= 0:
        raise ValueError(f"T ({T}) and vol ({vol}) must be positive")
    if forward_bps <= 0 or strike_bps <= 0:
        raise ValueError("Forward and strike must be positive")

    sqrt_T = math.sqrt(T)
    d1 = (math.log(forward_bps / strike_bps) + 0.5 * vol**2 * T) / (vol * sqrt_T)
    d2 = d1 - vol * sqrt_T
    return d1, d2


def black_price(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
    option_type: OptionType,
    notional: float = 1.0,
) -> float:
    """Price a credit index option using Black's model.

    Args:
        forward_bps: Forward spread in basis points.
        strike_bps: Strike spread in basis points.
        vol: Lognormal implied volatility (e.g. 0.40 for 40%).
        T: Time to expiry in years.
        rpv01: Risky PV01 of the underlying index.
        option_type: PAYER or RECEIVER.
        notional: Notional amount (default 1.0 for unit price).

    Returns:
        Option value (multiply by notional if notional=1).
        Expressed as a fraction of notional.
    """
    if T <= 1e-10:
        # At expiry: intrinsic value
        if option_type == OptionType.PAYER:
            intrinsic = max(forward_bps - strike_bps, 0) / 10_000
        else:
            intrinsic = max(strike_bps - forward_bps, 0) / 10_000
        return intrinsic * rpv01 * notional

    d1, d2 = _d1d2(forward_bps, strike_bps, vol, T)

    # Convert bps to decimal for the multiplication
    F = forward_bps / 10_000
    K = strike_bps / 10_000

    if option_type == OptionType.PAYER:
        price = rpv01 * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price = rpv01 * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    return price * notional


def black_price_with_fep(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
    fep: float,
    option_type: OptionType,
    notional: float = 1.0,
) -> float:
    """Price including front-end protection adjustment.

    For payer options, the FEP adds value (protection during option period).
    The adjusted forward incorporates FEP:
        F_adj = F + FEP / RPV01 (in spread terms)

    Args:
        forward_bps: Forward spread in basis points.
        strike_bps: Strike spread in basis points.
        vol: Lognormal implied volatility.
        T: Time to expiry in years.
        rpv01: Risky PV01 of the underlying index.
        fep: Front-end protection value (as decimal, per unit notional).
        option_type: PAYER or RECEIVER.
        notional: Notional amount.

    Returns:
        FEP-adjusted option value.
    """
    # Adjust forward spread to include FEP
    fep_spread_bps = (fep / rpv01) * 10_000 if rpv01 > 0 else 0
    adjusted_forward = forward_bps + fep_spread_bps

    return black_price(
        adjusted_forward, strike_bps, vol, T, rpv01, option_type, notional
    )


def implied_vol(
    market_price: float,
    forward_bps: float,
    strike_bps: float,
    T: float,
    rpv01: float,
    option_type: OptionType,
    notional: float = 1.0,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Back out implied volatility from a market price using Newton-Raphson.

    Args:
        market_price: Observed option price (same units as black_price output).
        forward_bps: Forward spread in bps.
        strike_bps: Strike spread in bps.
        T: Time to expiry in years.
        rpv01: Risky PV01.
        option_type: PAYER or RECEIVER.
        notional: Notional amount.
        tol: Convergence tolerance.
        max_iter: Maximum iterations.

    Returns:
        Implied volatility as a decimal (e.g. 0.40 for 40%).

    Raises:
        ValueError: If solver does not converge.
    """
    target = market_price / notional

    # Initial guess: 50%
    sigma = 0.50

    for _ in range(max_iter):
        price = black_price(forward_bps, strike_bps, sigma, T, rpv01, option_type)
        vega = black_vega(forward_bps, strike_bps, sigma, T, rpv01)

        if abs(vega) < 1e-15:
            break

        diff = price - target
        if abs(diff) < tol:
            return sigma

        sigma -= diff / vega
        sigma = max(sigma, 0.01)  # floor at 1%

    raise ValueError(
        f"Implied vol did not converge after {max_iter} iterations. "
        f"Last sigma={sigma:.4f}, price diff={diff:.2e}"
    )


def black_delta(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
    option_type: OptionType,
) -> float:
    """Analytical spread-delta (dV/dS) holding RPV01 constant.

    Returns delta per 1bp move, per unit notional.
    """
    if T <= 1e-10:
        if option_type == OptionType.PAYER:
            return rpv01 / 10_000 if forward_bps > strike_bps else 0.0
        else:
            return -rpv01 / 10_000 if strike_bps > forward_bps else 0.0

    d1, _ = _d1d2(forward_bps, strike_bps, vol, T)

    if option_type == OptionType.PAYER:
        return rpv01 * norm.cdf(d1) / 10_000
    else:
        return -rpv01 * norm.cdf(-d1) / 10_000


def black_gamma(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
) -> float:
    """Analytical spread-gamma (d²V/dS²) per unit notional.

    Same for payer and receiver.
    """
    if T <= 1e-10:
        return 0.0

    d1, _ = _d1d2(forward_bps, strike_bps, vol, T)
    F_dec = forward_bps / 10_000

    return rpv01 * norm.pdf(d1) / (F_dec * vol * math.sqrt(T)) / (10_000**2)


def black_vega(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
) -> float:
    """Analytical vega (dV/dσ) per unit notional.

    Same for payer and receiver.
    """
    if T <= 1e-10:
        return 0.0

    d1, _ = _d1d2(forward_bps, strike_bps, vol, T)
    F_dec = forward_bps / 10_000

    return rpv01 * F_dec * math.sqrt(T) * norm.pdf(d1)


def black_theta(
    forward_bps: float,
    strike_bps: float,
    vol: float,
    T: float,
    rpv01: float,
    option_type: OptionType,
) -> float:
    """Analytical theta (dV/dt) per calendar day, per unit notional.

    Negative for long options (time decay).
    """
    if T <= 1e-10:
        return 0.0

    d1, d2 = _d1d2(forward_bps, strike_bps, vol, T)
    F_dec = forward_bps / 10_000

    # Time decay from the vol component
    time_decay = -rpv01 * F_dec * vol * norm.pdf(d1) / (2 * math.sqrt(T))

    # Convert from per-year to per-day
    return time_decay / 365.0
