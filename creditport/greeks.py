"""Greeks computation via bump-and-reprice and analytical formulas.

Primary method is bump-and-reprice (numerical) since it correctly captures
the spread-dependence of RPV01. Analytical formulas are also available
for comparison.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .black import (
    black_delta,
    black_gamma,
    black_price,
    black_theta,
    black_vega,
)
from .conventions import OptionType, get_convention
from .curves import DiscountCurve, compute_rpv01
from .instruments import CreditIndexOption


@dataclass
class Greeks:
    """Container for option greeks."""

    delta: float  # dV per 1bp spread move (per unit notional)
    gamma: float  # d(delta) per 1bp spread move
    vega: float  # dV per 1 vol point (0.01 absolute)
    theta: float  # dV per calendar day
    price: float  # current option value

    def scaled(self, notional: float) -> Greeks:
        """Scale all greeks by notional."""
        return Greeks(
            delta=self.delta * notional,
            gamma=self.gamma * notional,
            vega=self.vega * notional,
            theta=self.theta * notional,
            price=self.price * notional,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "price": self.price,
            "delta": self.delta,
            "gamma": self.gamma,
            "vega": self.vega,
            "theta": self.theta,
        }


def compute_greeks_numerical(
    option: CreditIndexOption,
    spread_bps: float,
    vol: float,
    discount_curve: DiscountCurve,
    ref_date: dt.date,
    spread_bump: float = 1.0,
    vol_bump: float = 0.01,
    time_bump_days: int = 1,
    maturity_date: dt.date | None = None,
) -> Greeks:
    """Compute greeks via bump-and-reprice.

    This is the preferred method as it correctly captures the
    spread-dependence of RPV01.

    Args:
        option: The option to price.
        spread_bps: Current spread in bps.
        vol: Implied volatility (decimal).
        discount_curve: Risk-free discount curve.
        ref_date: Valuation date.
        spread_bump: Size of spread bump in bps (default 1bp).
        vol_bump: Size of vol bump (default 1 vol point = 0.01).
        time_bump_days: Days for theta calculation.
        maturity_date: Concrete index maturity date. If None, uses
                       option.tenor_years.

    Returns:
        Greeks object with all sensitivities per unit notional.
    """
    conv = get_convention(option.family)
    T = option.time_to_expiry(ref_date)

    def _price(s: float, v: float, t_offset: int = 0) -> float:
        adj_ref = ref_date + dt.timedelta(days=t_offset)
        t = option.time_to_expiry(adj_ref)
        if t <= 0:
            # At expiry intrinsic
            if option.option_type == OptionType.PAYER:
                intr = max(s - option.strike_bps, 0) / 10_000
            else:
                intr = max(option.strike_bps - s, 0) / 10_000
            rpv = compute_rpv01(
                s, conv.recovery_rate, discount_curve, adj_ref,
                maturity_date=maturity_date,
            )
            return intr * rpv

        rpv = compute_rpv01(
            s, conv.recovery_rate, discount_curve, adj_ref,
            maturity_date=maturity_date,
        )
        return black_price(s, option.strike_bps, v, t, rpv, option.option_type)

    # Base price
    price = _price(spread_bps, vol)

    # Delta: central difference
    p_up = _price(spread_bps + spread_bump, vol)
    p_down = _price(spread_bps - spread_bump, vol)
    delta = (p_up - p_down) / (2 * spread_bump)

    # Gamma: second derivative
    gamma = (p_up - 2 * price + p_down) / (spread_bump**2)

    # Vega: central difference on vol (per 1 vol point = 0.01)
    p_vup = _price(spread_bps, vol + vol_bump)
    p_vdown = _price(spread_bps, vol - vol_bump)
    vega = (p_vup - p_vdown) / (2 * vol_bump) * 0.01  # per 1 vol point

    # Theta: forward difference (1 day)
    p_tmrw = _price(spread_bps, vol, time_bump_days)
    theta = (p_tmrw - price) / time_bump_days

    return Greeks(
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        price=price,
    )


def compute_greeks_analytical(
    option: CreditIndexOption,
    spread_bps: float,
    vol: float,
    rpv01: float,
    ref_date: dt.date,
) -> Greeks:
    """Compute greeks using closed-form Black formulas.

    Note: These hold RPV01 constant, so delta does not capture
    the spread-sensitivity of the annuity. Use numerical greeks
    for more accurate risk management.
    """
    T = option.time_to_expiry(ref_date)

    price = black_price(
        spread_bps, option.strike_bps, vol, T, rpv01, option.option_type
    )
    delta = black_delta(
        spread_bps, option.strike_bps, vol, T, rpv01, option.option_type
    )
    gamma = black_gamma(spread_bps, option.strike_bps, vol, T, rpv01)
    vega = black_vega(spread_bps, option.strike_bps, vol, T, rpv01) * 0.01
    theta = black_theta(
        spread_bps, option.strike_bps, vol, T, rpv01, option.option_type
    )

    return Greeks(
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        price=price,
    )
