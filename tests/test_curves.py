"""Tests for discount and credit curve calculations."""

import datetime as dt
import math

import pytest

from creditport.curves import (
    CreditCurve,
    DiscountCurve,
    compute_front_end_protection,
    compute_rpv01,
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
