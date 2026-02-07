"""Instrument definitions: CreditIndex and CreditIndexOption."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .conventions import IndexConvention, IndexFamily, OptionType, get_convention


@dataclass
class CreditIndex:
    """A linear CDS index position (e.g. 'main44 5y').

    Represents a position in the underlying index — used for delta hedging
    or outright index exposure.
    """

    family: IndexFamily
    series: int
    tenor_years: int = 5
    notional: float = 0.0  # positive = sold protection, negative = bought protection

    @property
    def convention(self) -> IndexConvention:
        return get_convention(self.family)

    @property
    def label(self) -> str:
        return f"{self.family.value}{self.series} {self.tenor_years}y"

    def pv01(self, rpv01: float) -> float:
        """Dollar PV01: change in value per 1bp spread move.

        For a protection seller (long risk), spread widening = loss.
        """
        return self.notional * rpv01 / 10_000


@dataclass
class CreditIndexOption:
    """An option on a CDS index.

    Attributes:
        family: Which index (CDX IG, iTraxx Main, etc.).
        series: Index series number.
        strike_bps: Strike spread in basis points.
        option_type: PAYER or RECEIVER.
        expiry: Option expiry date (3rd Wednesday of expiry month).
        notional: Notional amount (positive = long the option).
        tenor_years: Tenor of the underlying index (typically 5Y).
    """

    family: IndexFamily
    series: int
    strike_bps: float
    option_type: OptionType
    expiry: dt.date
    notional: float = 0.0
    tenor_years: int = 5

    @property
    def convention(self) -> IndexConvention:
        return get_convention(self.family)

    @property
    def label(self) -> str:
        month = self.expiry.strftime("%b").lower()
        otype = "p" if self.option_type == OptionType.PAYER else "r"
        return (
            f"{self.family.value}{self.series} "
            f"{month}{int(self.strike_bps)}{otype}"
        )

    def time_to_expiry(self, ref_date: dt.date) -> float:
        """Time to expiry in years (ACT/365)."""
        return (self.expiry - ref_date).days / 365.0
