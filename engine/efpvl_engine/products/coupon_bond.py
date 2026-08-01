"""Fixed-rate Coupon Bond.

Pays face_value * coupon_rate / frequency at each coupon date, plus the face
value at maturity. This product introduces the machinery every later rates
product reuses: coupon schedule generation (rolled back from maturity),
accrued interest, and the clean vs dirty price distinction.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount, add_months, year_fraction

_FREQUENCIES = {"Annual": 1, "Semiannual": 2, "Quarterly": 4}


@register_product
class CouponBond(Product):
    product_id = "coupon_bond"

    def __init__(
        self,
        face_value: float,
        coupon_rate: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        day_count: DayCount = DayCount.THIRTY_360,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        if frequency not in (1, 2, 4):
            raise ValueError("frequency must be 1, 2 or 4 per year")
        if coupon_rate < 0:
            raise ValueError("coupon rate cannot be negative")
        self.face_value = face_value
        self.coupon_rate = coupon_rate  # decimal, e.g. 0.05
        self.frequency = frequency
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.day_count = day_count

    # -- Schedule ------------------------------------------------------- #

    def coupon_dates(self) -> list[date]:
        """All coupon dates strictly after settlement, rolled back from maturity."""
        step = -12 // self.frequency
        dates: list[date] = []
        d = self.maturity_date
        while d > self.settlement_date:
            dates.append(d)
            d = add_months(d, step)
        dates.reverse()
        return dates

    def previous_coupon_date(self) -> date:
        """Last coupon date on/before settlement (start of current accrual period)."""
        first_future = self.coupon_dates()[0]
        return add_months(first_future, -12 // self.frequency)

    def coupon_amount(self) -> float:
        return self.face_value * self.coupon_rate / self.frequency

    def cashflows(self) -> list[tuple[date, float, str]]:
        flows: list[tuple[date, float, str]] = []
        dates = self.coupon_dates()
        for d in dates:
            flows.append((d, self.coupon_amount(), "coupon"))
        flows.append((self.maturity_date, self.face_value, "redemption"))
        return flows

    # -- Accrual -------------------------------------------------------- #

    def accrued_interest(self) -> float:
        """Interest earned since the last coupon, owed to the seller.

        AI = coupon_amount * (accrual fraction of the current period elapsed).
        """
        prev = self.previous_coupon_date()
        nxt = self.coupon_dates()[0]
        accrued = year_fraction(prev, self.settlement_date, self.day_count)
        full = year_fraction(prev, nxt, self.day_count)
        if full <= 0:
            return 0.0
        return self.coupon_amount() * (accrued / full)

    def year_fractions(self) -> list[float]:
        """Time from settlement to each cash-flow date, under the day count."""
        return [
            year_fraction(self.settlement_date, d, self.day_count)
            for d in self.coupon_dates()
        ]

    # ------------------------------------------------------------------ #

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Coupon Bond",
            asset_class="Rates",
            summary=(
                "Fixed periodic coupons plus face value at maturity. Introduces "
                "accrued interest and the clean vs dirty price distinction."
            ),
            supported_models=("discounted_cash_flow",),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="face_value",
                label="Face Value",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=100.0,
                min_value=0.01,
                max_value=1e9,
                tooltip="Amount repaid at maturity; coupons are quoted against it.",
            ),
            InputField(
                name="coupon_rate",
                label="Coupon Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=5.0,
                min_value=0.0,
                max_value=50.0,
                step=0.05,
                tooltip="Annual coupon as a percentage of face value.",
            ),
            InputField(
                name="frequency",
                label="Coupon Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQUENCIES),
                default="Semiannual",
                tooltip="How often coupons are paid. US Treasuries pay semiannually.",
            ),
            InputField(
                name="settlement_date",
                label="Settlement Date",
                field_type=FieldType.DATE,
                default="2026-08-03",
            ),
            InputField(
                name="maturity_date",
                label="Maturity Date",
                field_type=FieldType.DATE,
                default="2031-08-03",
            ),
            InputField(
                name="day_count",
                label="Day Count",
                field_type=FieldType.SELECT,
                choices=tuple(dc.value for dc in DayCount),
                default=DayCount.THIRTY_360.value,
                tooltip="30/360 is standard for US corporate bonds.",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> CouponBond:
        return cls(
            face_value=float(inputs["face_value"]),
            coupon_rate=float(inputs["coupon_rate"]) / 100.0,  # % -> decimal
            frequency=_FREQUENCIES[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            day_count=DayCount(inputs.get("day_count", DayCount.THIRTY_360.value)),
        )
