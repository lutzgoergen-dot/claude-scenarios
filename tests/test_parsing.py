"""Tests for position string parsing."""

import datetime as dt

import pytest

from creditport.conventions import IndexFamily, OptionType
from creditport.instruments import CreditIndex, CreditIndexOption
from creditport.parsing import parse_position


class TestOptionParsing:
    def test_main_payer(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("main44 mar55p", notional=10_000_000, ref_date=ref)
        assert isinstance(pos, CreditIndexOption)
        assert pos.family == IndexFamily.ITRAXX_MAIN
        assert pos.series == 44
        assert pos.strike_bps == 55
        assert pos.option_type == OptionType.PAYER
        assert pos.notional == 10_000_000
        assert pos.expiry.month == 3
        assert pos.expiry.weekday() == 2  # Wednesday

    def test_main_receiver(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("main44 mar60r", ref_date=ref)
        assert isinstance(pos, CreditIndexOption)
        assert pos.option_type == OptionType.RECEIVER
        assert pos.strike_bps == 60

    def test_cdxig(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("cdxig43 jun80p", ref_date=ref)
        assert pos.family == IndexFamily.CDX_IG
        assert pos.series == 43
        assert pos.strike_bps == 80
        assert pos.expiry.month == 6

    def test_cdxhy(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("cdxhy20 mar300p", ref_date=ref)
        assert pos.family == IndexFamily.CDX_HY
        assert pos.series == 20
        assert pos.strike_bps == 300

    def test_xover(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("xover44 sep350p", ref_date=ref)
        assert pos.family == IndexFamily.ITRAXX_XOVER
        assert pos.series == 44
        assert pos.strike_bps == 350
        assert pos.expiry.month == 9

    def test_snrfin(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("snrfin44 mar70p", ref_date=ref)
        assert pos.family == IndexFamily.ITRAXX_SNRFIN
        assert pos.strike_bps == 70

    def test_fractional_strike(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("main44 mar55.5p", ref_date=ref)
        assert pos.strike_bps == 55.5

    def test_case_insensitive(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("MAIN44 MAR55P", ref_date=ref)
        assert pos.family == IndexFamily.ITRAXX_MAIN


class TestLinearParsing:
    def test_main_5y(self):
        pos = parse_position("main44 5y", notional=5_000_000)
        assert isinstance(pos, CreditIndex)
        assert pos.family == IndexFamily.ITRAXX_MAIN
        assert pos.series == 44
        assert pos.tenor_years == 5
        assert pos.notional == 5_000_000

    def test_cdxig_5y(self):
        pos = parse_position("cdxig43 5y")
        assert isinstance(pos, CreditIndex)
        assert pos.family == IndexFamily.CDX_IG
        assert pos.series == 43

    def test_10y_tenor(self):
        pos = parse_position("main44 10y")
        assert isinstance(pos, CreditIndex)
        assert pos.tenor_years == 10


class TestInvalidInput:
    def test_unknown_index(self):
        with pytest.raises(ValueError, match="Unknown index code"):
            parse_position("foo44 mar55p")

    def test_garbage_string(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_position("not a position")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_position("")


class TestThirdWednesday:
    def test_expiry_is_third_wednesday(self):
        ref = dt.date(2026, 1, 1)
        pos = parse_position("main44 mar55p", ref_date=ref)
        # 3rd Wednesday of March 2026
        assert pos.expiry == dt.date(2026, 3, 18)

    def test_past_month_rolls_to_next_year(self):
        ref = dt.date(2026, 4, 1)  # After March
        pos = parse_position("main44 mar55p", ref_date=ref)
        # Should get March 2027
        assert pos.expiry.year == 2027
        assert pos.expiry.month == 3
