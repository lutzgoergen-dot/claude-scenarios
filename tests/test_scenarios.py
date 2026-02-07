"""Tests for scenario engine."""

import datetime as dt

import pytest

from creditport.conventions import IndexFamily
from creditport.curves import DiscountCurve
from creditport.market import IndexMarketData, MarketData
from creditport.portfolio import Portfolio
from creditport.scenarios import ScenarioEngine


@pytest.fixture
def scenario_setup():
    """Create market + portfolio for scenario testing."""
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

    port = Portfolio(ref_date=dt.date(2026, 2, 7))
    port.add("main44 jun55p", notional=10_000_000)

    return market, port


class TestScenarioEngine:
    def test_parallel_shift_length(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        results = engine.parallel_shift(spread_shifts=[-10, 0, 10])
        assert len(results) == 3

    def test_no_shift_zero_pnl(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        results = engine.parallel_shift(spread_shifts=[0])
        assert results[0].pnl == pytest.approx(0.0, abs=1e-6)

    def test_payer_profits_from_widening(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        results = engine.parallel_shift(spread_shifts=[-20, 0, 20])
        # Widening (+20bp) should profit a long payer
        pnl_wide = results[2].pnl
        pnl_tight = results[0].pnl
        assert pnl_wide > pnl_tight

    def test_spread_vol_matrix(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        matrix = engine.spread_vol_matrix(
            spread_shifts=[-10, 0, 10],
            vol_shifts=[-0.05, 0, 0.05],
        )
        assert matrix.shape == (3, 3)

    def test_time_decay(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        results = engine.time_decay(days=[0, 10, 30])
        assert len(results) == 3
        # Option value should decrease over time (theta)
        assert results[2].portfolio_mv < results[0].portfolio_mv

    def test_results_table(self, scenario_setup):
        market, port = scenario_setup
        engine = ScenarioEngine(market, port)
        results = engine.parallel_shift()
        df = engine.results_table(results)
        assert "scenario" in df.columns
        assert "pnl" in df.columns
