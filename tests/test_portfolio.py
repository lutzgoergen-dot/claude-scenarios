"""Tests for portfolio pricing and greeks."""

import datetime as dt

import pytest

from creditport.conventions import IndexFamily, OptionType
from creditport.curves import DiscountCurve
from creditport.instruments import CreditIndexOption
from creditport.market import IndexMarketData, MarketData
from creditport.portfolio import Portfolio


@pytest.fixture
def sample_market():
    """Create a sample market data snapshot."""
    market = MarketData(
        ref_date=dt.date(2026, 2, 7),
        discount_curve=DiscountCurve(rate=0.03),
    )
    market.add_index(IndexMarketData(
        family=IndexFamily.ITRAXX_MAIN,
        series=44,
        spread_bps=60,
        vol_surface={50: 0.45, 55: 0.42, 60: 0.40, 65: 0.38, 70: 0.36},
    ))
    market.add_index(IndexMarketData(
        family=IndexFamily.CDX_IG,
        series=43,
        spread_bps=55,
        vol_surface={45: 0.50, 50: 0.47, 55: 0.45, 60: 0.43, 65: 0.41},
    ))
    return market


class TestPortfolio:
    def test_add_option(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        pos = port.add("main44 mar55p", notional=10_000_000)
        assert isinstance(pos, CreditIndexOption)
        assert len(port.positions) == 1

    def test_add_index(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        port.add("main44 5y", notional=5_000_000)
        assert len(port.positions) == 1

    def test_price_returns_results(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        port.add("main44 mar55p", notional=10_000_000)
        results = port.price(sample_market)
        assert len(results) == 1
        assert results[0].market_value != 0

    def test_greeks_table_shape(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        port.add("main44 mar55p", notional=10_000_000)
        port.add("main44 mar60r", notional=-5_000_000)
        port.add("main44 5y", notional=2_000_000)

        df = port.greeks_table(sample_market)
        # 3 positions + 1 TOTAL row
        assert len(df) == 4
        assert "delta" in df.columns
        assert "gamma" in df.columns
        assert "vega" in df.columns

    def test_payer_positive_delta(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        port.add("main44 mar55p", notional=10_000_000)
        results = port.price(sample_market)
        assert results[0].greeks.delta > 0  # payer profits from widening

    def test_clear(self, sample_market):
        port = Portfolio(ref_date=dt.date(2026, 2, 7))
        port.add("main44 mar55p", notional=10_000_000)
        port.clear()
        assert len(port.positions) == 0
