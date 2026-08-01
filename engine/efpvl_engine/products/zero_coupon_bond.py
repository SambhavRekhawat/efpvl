"""Zero Coupon Bond.

"Pay me the face value at maturity, nothing in between." Its price is a
single discounted cash flow, which makes it the perfect first product: it
exercises dates, day counts, and the curve with no other moving parts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount, year_fraction


@register_product
class ZeroCouponBond(Product):
    product_id = "zero_coupon_bond"

    def __init__(
        self,
        face_value: float,
        settlement_date: date,
        maturity_date: date,
        day_count: DayCount = DayCount.ACT_365,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        self.face_value = face_value
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.day_count = day_count

    # ------------------------------------------------------------------ #

    def time_to_maturity(self) -> float:
        return year_fraction(self.settlement_date, self.maturity_date, self.day_count)

    def cashflows(self) -> list[tuple[date, float, str]]:
        """[(payment_date, amount, kind)] — one redemption flow."""
        return [(self.maturity_date, self.face_value, "redemption")]

    # ------------------------------------------------------------------ #

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Zero Coupon Bond",
            asset_class="Rates",
            summary=(
                "A single payment of face value at maturity. Price equals the "
                "face value multiplied by one discount factor — the cleanest "
                "illustration of the time value of money."
            ),
            supported_models=("discounted_cash_flow", "vasicek"),
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
                tooltip="Amount repaid at maturity (the notional/par amount).",
            ),
            InputField(
                name="settlement_date",
                label="Settlement Date",
                field_type=FieldType.DATE,
                default="2026-08-03",
                tooltip="Date the trade settles; valuation is as of this date.",
            ),
            InputField(
                name="maturity_date",
                label="Maturity Date",
                field_type=FieldType.DATE,
                default="2031-08-03",
                tooltip="Date the face value is repaid.",
            ),
            InputField(
                name="day_count",
                label="Day Count",
                field_type=FieldType.SELECT,
                choices=tuple(dc.value for dc in DayCount),
                default=DayCount.ACT_365.value,
                tooltip="Convention converting calendar days into year fractions.",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> ZeroCouponBond:
        return cls(
            face_value=float(inputs["face_value"]),
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            day_count=DayCount(inputs.get("day_count", DayCount.ACT_365.value)),
        )
