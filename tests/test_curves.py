"""Tests for discount and credit curve calculations."""

import datetime as dt
import math

import pytest

from creditport.curves import (
    CreditCurve,
    DiscountCurve,
    compute_front_end_protection,
    compute_rpv01,
    compute_rpv01_forward,
    compute_spread_duration,
)


class TestDiscountCurve:
    def test_zero_rate(self):
        curve = DiscountCurve(rate=0.0)
        assert curve.df(1.0) == 1.0
        assert curve.df(5.0) == 1.0

    def test_positive_rate(self):
        curve = DiscountCurve(rate=0.05)
        assert curve.df(0.0) == pytest.approx(1.0)
        assert curve.df(1.0) == pytest.approx(math.exp(-0.05), rel=1e-10)
        assert curve.df(5.0) == pytest.approx(math.exp(-0.25), rel=1e-10)

    def test_df_date(self):
        curve = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        target = dt.date(2027, 1, 1)
        t = 365 / 365.0
        assert curve.df_date(target, ref) == pytest.approx(math.exp(-0.03 * t), rel=1e-6)


class TestCreditCurve:
    def test_hazard_rate(self):
        # 100bps spread, 40% recovery -> lambda = 0.01 / 0.6
        cc = CreditCurve(spread_bps=100, recovery_rate=0.40)
        assert cc.hazard_rate == pytest.approx(0.01 / 0.60, rel=1e-10)

    def test_survival_probability(self):
        cc = CreditCurve(spread_bps=100, recovery_rate=0.40)
        assert cc.survival(0.0) == pytest.approx(1.0)
        lam = 0.01 / 0.60
        assert cc.survival(5.0) == pytest.approx(math.exp(-lam * 5), rel=1e-10)

    def test_higher_spread_lower_survival(self):
        cc_low = CreditCurve(spread_bps=50, recovery_rate=0.40)
        cc_high = CreditCurve(spread_bps=200, recovery_rate=0.40)
        assert cc_high.survival(5.0) < cc_low.survival(5.0)


class TestRPV01:
    def test_rpv01_positive(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        rpv01 = compute_rpv01(100, 0.40, dc, ref, maturity_years=5)
        assert rpv01 > 0
        # RPV01 for IG spread should be roughly 4-5 years
        assert 3.5 < rpv01 < 5.5

    def test_wider_spread_lower_rpv01(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        rpv01_tight = compute_rpv01(50, 0.40, dc, ref)
        rpv01_wide = compute_rpv01(500, 0.40, dc, ref)
        assert rpv01_wide < rpv01_tight

    def test_lower_recovery_higher_rpv01(self):
        """Lower recovery with same spread => lower hazard rate => higher survival => higher RPV01."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        rpv01_high_rec = compute_rpv01(300, 0.40, dc, ref)
        rpv01_low_rec = compute_rpv01(300, 0.20, dc, ref)
        # hazard_rate = spread / (1-R), so lower R -> lower lambda -> higher RPV01
        assert rpv01_low_rec > rpv01_high_rec


    def test_rpv01_with_maturity_date(self):
        """Using maturity_date should give same result as maturity_years for equivalent dates."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        # 5Y from ref = ~2031-01-01, but IMM schedule ends similarly
        rpv01_years = compute_rpv01(100, 0.40, dc, ref, maturity_years=5)
        # Use an explicit maturity close to 5Y: Dec 20 2030 (last IMM date before 5Y)
        rpv01_date = compute_rpv01(100, 0.40, dc, ref, maturity_date=dt.date(2030, 12, 20))
        # Should be close but not identical (different end boundaries)
        assert abs(rpv01_years - rpv01_date) < 0.5

    def test_rpv01_shorter_maturity_lower(self):
        """An index closer to maturity has lower RPV01."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        rpv01_5y = compute_rpv01(100, 0.40, dc, ref, maturity_date=dt.date(2031, 6, 20))
        rpv01_3y = compute_rpv01(100, 0.40, dc, ref, maturity_date=dt.date(2029, 6, 20))
        assert rpv01_3y < rpv01_5y


class TestRPV01Forward:
    def test_forward_rpv01_positive(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 3, 18)
        maturity = dt.date(2031, 6, 20)
        fwd = compute_rpv01_forward(100, 0.40, dc, ref, expiry, maturity)
        assert fwd > 0

    def test_forward_shorter_than_spot(self):
        """Forward annuity (expiry→maturity) < spot annuity (today→maturity)."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 6, 17)
        maturity = dt.date(2031, 6, 20)
        spot = compute_rpv01(100, 0.40, dc, ref, maturity_date=maturity)
        fwd = compute_rpv01_forward(100, 0.40, dc, ref, expiry, maturity)
        assert fwd < spot

    def test_spot_equals_front_plus_forward(self):
        """SpreadDuration decomposes: spot = front + forward."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 6, 17)
        maturity = dt.date(2031, 6, 20)
        # Use compute_spread_duration which does the decomposition correctly
        sd = compute_spread_duration(100, 0.40, dc, ref, maturity, expiry)
        assert sd.spot_rpv01 == pytest.approx(sd.front_rpv01 + sd.forward_rpv01, rel=1e-10)

    def test_expiry_on_imm_exact_decomposition(self):
        """When expiry falls on an IMM date, independent calculations match."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 6, 20)  # IMM date
        maturity = dt.date(2031, 6, 20)
        spot = compute_rpv01(100, 0.40, dc, ref, maturity_date=maturity)
        fwd = compute_rpv01_forward(100, 0.40, dc, ref, expiry, maturity)
        front = compute_rpv01(100, 0.40, dc, ref, maturity_date=expiry)
        assert spot == pytest.approx(front + fwd, rel=1e-10)

    def test_expiry_at_maturity_zero(self):
        """Forward RPV01 is zero if expiry = maturity."""
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        maturity = dt.date(2031, 6, 20)
        fwd = compute_rpv01_forward(100, 0.40, dc, ref, maturity, maturity)
        assert fwd == pytest.approx(0.0, abs=1e-10)


class TestSpreadDuration:
    def test_spread_duration_fields(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        maturity = dt.date(2031, 6, 20)
        expiry = dt.date(2026, 6, 17)
        sd = compute_spread_duration(100, 0.40, dc, ref, maturity, expiry)

        assert sd.spot_rpv01 > 0
        assert sd.forward_rpv01 > 0
        assert sd.forward_rpv01 < sd.spot_rpv01
        assert sd.front_rpv01 > 0
        assert sd.spot_dv01 == pytest.approx(sd.spot_rpv01 / 10_000)
        assert sd.forward_dv01 == pytest.approx(sd.forward_rpv01 / 10_000)
        assert sd.remaining_years > 5.0

    def test_no_expiry_forward_equals_spot(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        maturity = dt.date(2031, 6, 20)
        sd = compute_spread_duration(100, 0.40, dc, ref, maturity)
        assert sd.forward_rpv01 == sd.spot_rpv01
        assert sd.front_rpv01 == 0.0


class TestFrontEndProtection:
    def test_fep_positive(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 3, 18)
        fep = compute_front_end_protection(100, 0.40, dc, ref, expiry)
        assert fep > 0

    def test_fep_zero_at_expiry(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 3, 18)
        expiry = dt.date(2026, 3, 18)
        fep = compute_front_end_protection(100, 0.40, dc, ref, expiry)
        assert fep == 0.0

    def test_wider_spread_higher_fep(self):
        dc = DiscountCurve(rate=0.03)
        ref = dt.date(2026, 1, 1)
        expiry = dt.date(2026, 6, 17)
        fep_tight = compute_front_end_protection(50, 0.40, dc, ref, expiry)
        fep_wide = compute_front_end_protection(500, 0.40, dc, ref, expiry)
        assert fep_wide > fep_tight
