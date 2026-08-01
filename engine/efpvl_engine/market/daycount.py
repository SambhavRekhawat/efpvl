"""Day count conventions.

Fixed income never counts days the naive way. A convention maps a pair of
dates to a *year fraction* used for accrual and discounting. Phase 1 ships
the three workhorses:

* **ACT/360**  — money markets (deposits, FRAs, USD LIBOR/SOFR legs).
* **ACT/365F** — GBP markets, many curves.
* **30/360 US** — US corporate/agency bonds; pretends every month has 30 days.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum


class DayCount(StrEnum):
    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    THIRTY_360 = "30/360"


def year_fraction(start: date, end: date, convention: DayCount) -> float:
    """Year fraction between two dates under the given convention.

    Args:
        start: Period start (inclusive).
        end: Period end (exclusive by market convention).
        convention: Day count rule.

    Returns:
        Accrual fraction in years; negative if ``end < start``.
    """
    if convention is DayCount.ACT_360:
        return (end - start).days / 360.0
    if convention is DayCount.ACT_365:
        return (end - start).days / 365.0
    if convention is DayCount.THIRTY_360:
        return _thirty_360_us(start, end)
    raise ValueError(f"Unsupported day count: {convention}")


def _thirty_360_us(start: date, end: date) -> float:
    """30/360 US (Bond Basis) per the standard adjustment rules."""
    d1, d2 = start.day, end.day
    if d1 == 31:
        d1 = 30
    if d2 == 31 and d1 == 30:
        d2 = 30
    days = 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)
    return days / 360.0


def add_months(d: date, months: int) -> date:
    """Calendar-aware month shift, clamping to month-end (Jan 31 + 1m = Feb 28)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days
