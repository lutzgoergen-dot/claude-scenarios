"""Tests for dealer quote loading and grid building."""

import datetime as dt
from io import StringIO

import pandas as pd
import pytest

from creditport.conventions import IndexFamily, OptionType
from creditport.quotes import (
    OptionQuote,
    QuoteGrid,
    _parse_curve_code,
    build_quote_grids,
    load_dealer_quotes,
    quotes_to_market_data,
)


class TestCurveCodeParsing:
    def test_itraxx_main(self):
        family, series = _parse_curve_code("ITXES544")
        assert family == IndexFamily.ITRAXX_MAIN
        assert series == 44

    def test_itraxx_xover(self):
        family, series = _parse_curve_code("ITXEX544")
        assert family == IndexFamily.ITRAXX_XOVER
        assert series == 44

    def test_itraxx_snrfin(self):
        family, series = _parse_curve_code("ITXEF544")
        assert family == IndexFamily.ITRAXX_SNRFIN
        assert series == 44

    def test_cdx_ig(self):
        family, series = _parse_curve_code("CDXIG43")
        assert family == IndexFamily.CDX_IG
        assert series == 43

    def test_cdx_hy(self):
        family, series = _parse_curve_code("CDXHY20")
        assert family == IndexFamily.CDX_HY
        assert series == 20

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown curve code"):
            _parse_curve_code("FOOBAR99")


class TestOptionQuote:
    def test_mid_premium(self):
        q = OptionQuote(
            family=IndexFamily.ITRAXX_MAIN, series=44,
            strike_bps=55, option_type=OptionType.PAYER,
            expiry=dt.date(2026, 6, 17), firm="CITI",
            bid_premium=10.0, offer_premium=14.0,
        )
        assert q.mid_premium == 12.0

    def test_label(self):
        q = OptionQuote(
            family=IndexFamily.ITRAXX_MAIN, series=44,
            strike_bps=55, option_type=OptionType.PAYER,
            expiry=dt.date(2026, 6, 17), firm="CITI",
        )
        assert "55" in q.label
        assert "P" in q.label


class TestQuoteGrid:
    def _make_quotes(self):
        return [
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=55, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                bid_premium=10.0, offer_premium=14.0,
                mid_vol=0.43, mid_ref_spread=53.0,
                mid_forward_spread=56.5,
            ),
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=60, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                bid_premium=6.0, offer_premium=9.0,
                mid_vol=0.40, mid_ref_spread=53.0,
                mid_forward_spread=56.5,
            ),
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=55, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="GS",
                bid_premium=11.0, offer_premium=13.0,
                mid_vol=0.44, mid_ref_spread=53.0,
                mid_forward_spread=56.5,
            ),
        ]

    def test_grid_basics(self):
        grid = QuoteGrid(family=IndexFamily.ITRAXX_MAIN, series=44)
        for q in self._make_quotes():
            grid.add(q)
        assert len(grid.firms) == 2
        assert len(grid.strikes) == 2

    def test_vol_grid(self):
        grid = QuoteGrid(family=IndexFamily.ITRAXX_MAIN, series=44)
        for q in self._make_quotes():
            grid.add(q)
        df = grid.to_vol_grid(expiry=dt.date(2026, 6, 17))
        assert len(df) > 0
        assert "composite_vol" in df.columns

    def test_price_grid(self):
        grid = QuoteGrid(family=IndexFamily.ITRAXX_MAIN, series=44)
        for q in self._make_quotes():
            grid.add(q)
        df = grid.to_price_grid(expiry=dt.date(2026, 6, 17))
        assert len(df) > 0
        assert "composite_mid" in df.columns

    def test_composite_vol_surface(self):
        grid = QuoteGrid(family=IndexFamily.ITRAXX_MAIN, series=44)
        for q in self._make_quotes():
            grid.add(q)
        surface = grid.composite_vol_surface(dt.date(2026, 6, 17))
        assert 55 in surface
        assert 60 in surface
        # K=55 has two quotes (CITI=0.43, GS=0.44), composite ≈ 0.435
        assert surface[55] == pytest.approx(0.435, rel=1e-6)


class TestBuildGrids:
    def test_groups_by_index(self):
        quotes = [
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=55, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_ref_spread=53.0,
            ),
            OptionQuote(
                family=IndexFamily.CDX_IG, series=43,
                strike_bps=50, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_ref_spread=48.0,
            ),
        ]
        grids = build_quote_grids(quotes)
        assert len(grids) == 2
        assert (IndexFamily.ITRAXX_MAIN, 44) in grids
        assert (IndexFamily.CDX_IG, 43) in grids

    def test_common_ref_spread(self):
        quotes = [
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=55, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_ref_spread=53.0,
            ),
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=60, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_ref_spread=53.0,
            ),
        ]
        grids = build_quote_grids(quotes)
        grid = grids[(IndexFamily.ITRAXX_MAIN, 44)]
        assert grid.common_ref_spread == 53.0


class TestQuotesToMarketData:
    def test_builds_market_data(self):
        quotes = [
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=55, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_vol=0.43, mid_ref_spread=53.0,
            ),
            OptionQuote(
                family=IndexFamily.ITRAXX_MAIN, series=44,
                strike_bps=60, option_type=OptionType.PAYER,
                expiry=dt.date(2026, 6, 17), firm="CITI",
                mid_vol=0.40, mid_ref_spread=53.0,
            ),
        ]
        market = quotes_to_market_data(
            quotes, ref_date=dt.date(2026, 2, 12), risk_free_rate=0.03,
        )
        idx = market.get_index(IndexFamily.ITRAXX_MAIN, 44)
        assert idx.spread_bps == 53.0
        assert 55 in idx.vol_surface
        assert 60 in idx.vol_surface
        assert idx.vol_surface[55] == pytest.approx(0.43)
