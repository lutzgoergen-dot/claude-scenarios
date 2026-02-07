"""Index conventions: recovery rates, fixed coupons, currencies, and identifiers."""

from dataclasses import dataclass
from enum import Enum


class IndexFamily(Enum):
    CDX_IG = "cdxig"
    CDX_HY = "cdxhy"
    ITRAXX_MAIN = "main"
    ITRAXX_XOVER = "xover"
    ITRAXX_SNRFIN = "snrfin"


class OptionType(Enum):
    PAYER = "payer"
    RECEIVER = "receiver"


@dataclass(frozen=True)
class IndexConvention:
    family: IndexFamily
    recovery_rate: float
    fixed_coupon_bps: float  # running coupon in bps
    currency: str
    day_count: str  # ACT/360 is standard for CDS
    payment_frequency: int  # quarterly = 4
    name: str

    @property
    def fixed_coupon(self) -> float:
        """Fixed coupon as a decimal (e.g. 0.01 for 100bps)."""
        return self.fixed_coupon_bps / 10_000


CONVENTIONS: dict[IndexFamily, IndexConvention] = {
    IndexFamily.CDX_IG: IndexConvention(
        family=IndexFamily.CDX_IG,
        recovery_rate=0.40,
        fixed_coupon_bps=100,
        currency="USD",
        day_count="ACT/360",
        payment_frequency=4,
        name="CDX NA IG",
    ),
    IndexFamily.CDX_HY: IndexConvention(
        family=IndexFamily.CDX_HY,
        recovery_rate=0.20,
        fixed_coupon_bps=500,
        currency="USD",
        day_count="ACT/360",
        payment_frequency=4,
        name="CDX NA HY",
    ),
    IndexFamily.ITRAXX_MAIN: IndexConvention(
        family=IndexFamily.ITRAXX_MAIN,
        recovery_rate=0.40,
        fixed_coupon_bps=100,
        currency="EUR",
        day_count="ACT/360",
        payment_frequency=4,
        name="iTraxx Europe Main",
    ),
    IndexFamily.ITRAXX_XOVER: IndexConvention(
        family=IndexFamily.ITRAXX_XOVER,
        recovery_rate=0.40,
        fixed_coupon_bps=500,
        currency="EUR",
        day_count="ACT/360",
        payment_frequency=4,
        name="iTraxx Europe Crossover",
    ),
    IndexFamily.ITRAXX_SNRFIN: IndexConvention(
        family=IndexFamily.ITRAXX_SNRFIN,
        recovery_rate=0.40,
        fixed_coupon_bps=100,
        currency="EUR",
        day_count="ACT/360",
        payment_frequency=4,
        name="iTraxx Europe Senior Financials",
    ),
}

# Aliases for parsing position strings
INDEX_ALIASES: dict[str, IndexFamily] = {
    "cdxig": IndexFamily.CDX_IG,
    "ig": IndexFamily.CDX_IG,
    "cdxhy": IndexFamily.CDX_HY,
    "hy": IndexFamily.CDX_HY,
    "main": IndexFamily.ITRAXX_MAIN,
    "itraxxmain": IndexFamily.ITRAXX_MAIN,
    "xover": IndexFamily.ITRAXX_XOVER,
    "itraxxxover": IndexFamily.ITRAXX_XOVER,
    "crossover": IndexFamily.ITRAXX_XOVER,
    "snrfin": IndexFamily.ITRAXX_SNRFIN,
    "itraxxsnrfin": IndexFamily.ITRAXX_SNRFIN,
    "senfin": IndexFamily.ITRAXX_SNRFIN,
    "senfin": IndexFamily.ITRAXX_SNRFIN,
}


def get_convention(family: IndexFamily) -> IndexConvention:
    """Look up the convention for an index family."""
    return CONVENTIONS[family]
