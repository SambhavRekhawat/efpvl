"""Payment schedule generation shared by rates products.

Dates are rolled back from maturity in equal month steps (the market's
standard convention), keeping the maturity date exact. The first accrual
period starts at settlement (a simplification: short front stubs are
absorbed there rather than modeled separately — documented, and fine for
an educational curve-consistent pricer).
"""

from __future__ import annotations

from datetime import date

from efpvl_engine.market.daycount import DayCount, add_months, year_fraction


def roll_back_schedule(settlement: date, maturity: date, frequency: int) -> list[date]:
    """Payment dates strictly after settlement, rolled back from maturity."""
    if frequency not in (1, 2, 4, 12):
        raise ValueError("frequency must be 1, 2, 4 or 12 per year")
    step = -12 // frequency
    dates: list[date] = []
    d = maturity
    while d > settlement:
        dates.append(d)
        d = add_months(d, step)
    dates.reverse()
    return dates


def accrual_periods(
    settlement: date, pay_dates: list[date], day_count: DayCount
) -> list[tuple[date, date, float]]:
    """[(period_start, period_end, tau)] with the first period cut at settlement."""
    periods: list[tuple[date, date, float]] = []
    start = settlement
    for end in pay_dates:
        periods.append((start, end, year_fraction(start, end, day_count)))
        start = end
    return periods
