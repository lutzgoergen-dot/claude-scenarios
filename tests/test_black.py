"""Tests for Black's model pricing."""

import math

import pytest

from creditport.black import (
    black_delta,
    black_gamma,
    black_price,
    black_theta,
    black_vega,
    implied_vol,
)
from creditport.conventions import OptionType


class TestBlackPrice:
    def test_payer_atm(self):
        """ATM payer should have positive value."""
        price = black_price(
            forward_bps=100, strike_bps=100, vol=0.40,
            T=0.25, rpv01=4.5, option_type=OptionType.PAYER,
        )
        assert price > 0

    def test_receiver_atm(self):
        """ATM receiver should have positive value."""
        price = black_price(
            forward_bps=100, strike_bps=100, vol=0.40,
            T=0.25, rpv01=4.5, option_type=OptionType.RECEIVER,
        )
        assert price > 0

    def test_put_call_parity(self):
        """Payer - Receiver = (F - K) * RPV01 (per unit notional)."""
        F, K, vol, T, rpv01 = 100, 90, 0.40, 0.25, 4.5
        payer = black_price(F, K, vol, T, rpv01, OptionType.PAYER)
        receiver = black_price(F, K, vol, T, rpv01, OptionType.RECEIVER)
        forward_value = (F - K) / 10_000 * rpv01
        assert payer - receiver == pytest.approx(forward_value, rel=1e-8)

    def test_deep_itm_payer(self):
        """Deep ITM payer ≈ intrinsic value."""
        price = black_price(
            forward_bps=200, strike_bps=50, vol=0.30,
            T=0.1, rpv01=4.5, option_type=OptionType.PAYER,
        )
        intrinsic = (200 - 50) / 10_000 * 4.5
        assert price == pytest.approx(intrinsic, rel=0.05)

    def test_deep_otm_payer_near_zero(self):
        """Deep OTM payer should be near zero."""
        price = black_price(
            forward_bps=50, strike_bps=200, vol=0.30,
            T=0.1, rpv01=4.5, option_type=OptionType.PAYER,
        )
        assert price < 1e-5

    def test_higher_vol_higher_price(self):
        """Higher vol -> higher option price."""
        price_low = black_price(100, 100, 0.20, 0.25, 4.5, OptionType.PAYER)
        price_high = black_price(100, 100, 0.60, 0.25, 4.5, OptionType.PAYER)
        assert price_high > price_low

    def test_longer_expiry_higher_price(self):
        """Longer time to expiry -> higher option price."""
        price_short = black_price(100, 100, 0.40, 0.1, 4.5, OptionType.PAYER)
        price_long = black_price(100, 100, 0.40, 0.5, 4.5, OptionType.PAYER)
        assert price_long > price_short

    def test_at_expiry_payer(self):
        """At expiry, payer = max(F-K, 0) * RPV01."""
        price = black_price(120, 100, 0.40, 0.0, 4.5, OptionType.PAYER)
        expected = (120 - 100) / 10_000 * 4.5
        assert price == pytest.approx(expected, rel=1e-10)

    def test_at_expiry_receiver_otm(self):
        """At expiry, OTM receiver = 0."""
        price = black_price(120, 100, 0.40, 0.0, 4.5, OptionType.RECEIVER)
        assert price == pytest.approx(0.0, abs=1e-12)

    def test_notional_scaling(self):
        """Price should scale linearly with notional."""
        price_unit = black_price(100, 100, 0.40, 0.25, 4.5, OptionType.PAYER, notional=1.0)
        price_10mm = black_price(100, 100, 0.40, 0.25, 4.5, OptionType.PAYER, notional=10_000_000)
        assert price_10mm == pytest.approx(price_unit * 10_000_000, rel=1e-10)


class TestImpliedVol:
    def test_round_trip(self):
        """implied_vol(black_price(vol)) should return vol."""
        vol = 0.45
        price = black_price(100, 100, vol, 0.25, 4.5, OptionType.PAYER)
        recovered = implied_vol(price, 100, 100, 0.25, 4.5, OptionType.PAYER)
        assert recovered == pytest.approx(vol, rel=1e-6)

    def test_round_trip_otm(self):
        """Round-trip for OTM option."""
        vol = 0.35
        price = black_price(80, 100, vol, 0.5, 4.5, OptionType.PAYER)
        recovered = implied_vol(price, 80, 100, 0.5, 4.5, OptionType.PAYER)
        assert recovered == pytest.approx(vol, rel=1e-4)


class TestGreeks:
    def test_payer_delta_positive(self):
        """Payer delta should be positive (profits from widening)."""
        delta = black_delta(100, 100, 0.40, 0.25, 4.5, OptionType.PAYER)
        assert delta > 0

    def test_receiver_delta_negative(self):
        """Receiver delta should be negative."""
        delta = black_delta(100, 100, 0.40, 0.25, 4.5, OptionType.RECEIVER)
        assert delta < 0

    def test_gamma_positive(self):
        """Gamma should always be positive for long options."""
        gamma = black_gamma(100, 100, 0.40, 0.25, 4.5)
        assert gamma > 0

    def test_vega_positive(self):
        """Vega should always be positive for long options."""
        vega = black_vega(100, 100, 0.40, 0.25, 4.5)
        assert vega > 0

    def test_theta_negative(self):
        """Theta should be negative for long ATM options (time decay)."""
        theta = black_theta(100, 100, 0.40, 0.25, 4.5, OptionType.PAYER)
        assert theta < 0
