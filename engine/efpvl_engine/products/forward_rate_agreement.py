"""Forward Rate Agreement.

A bet on one future interest rate: fix a rate K today for the period
[T1, T2]; settle the difference against the rate that actually sets. Under
no-arbitrage the curve already implies that future rate — the simple forward
f = (DF(T1)/DF(T2) − 1)/τ — so the FRA's value is just the discounted
difference between what you locked and what the curve says.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount, year_fraction


@register_product
class ForwardRateAgreement(Product):
    product_id = "forward_rate_agreement"

    def __init__(
        self,
        notional: float,
        fixed_rate: float,
        settlement_date: date,
        start_date: date,
        end_date: date,
        position: str = "Pay fixed",
        day_count: DayCount = DayCount.ACT_360,
    ) -> None:
        if not settlement_date < start_date < end_date:
            raise ValueError("require settlement < start < end")
        if position not in ("Pay fixed", "Receive fixed"):
            raise ValueError("position must be 'Pay fixed' or 'Receive fixed'")
        self.notional = notional
        self.fixed_rate = fixed_rate  # decimal
        self.settlement_date = settlement_date
        self.start_date = start_date
        self.end_date = end_date
        self.position = position
        self.day_count = day_count

    def times(self) -> tuple[float, float, float]:
        """(t1, t2, tau): curve times to start/end and the accrual fraction."""
        t1 = year_fraction(self.settlement_date, self.start_date, self.day_count)
        t2 = year_fraction(self.settlement_date, self.end_date, self.day_count)
        tau = year_fraction(self.start_date, self.end_date, self.day_count)
        return t1, t2, tau

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Forward Rate Agreement",
            asset_class="Rates",
            summary=(
                "Lock an interest rate today for a future period. Value is the "
                "discounted gap between your locked rate and the curve's "
                "implied forward."
            ),
            supported_models=("discounted_cash_flow",),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="notional",
                label="Notional",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=1_000_000.0,
                min_value=1.0,
                max_value=1e10,
                tooltip="Reference amount interest is computed on; never exchanged.",
            ),
            InputField(
                name="fixed_rate",
                label="Fixed Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=4.0,
                min_value=-2.0,
                max_value=25.0,
                step=0.01,
                tooltip="The rate you lock today for the future period.",
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Pay fixed", "Receive fixed"),
                default="Pay fixed",
                tooltip="Pay fixed profits if rates set higher than your lock.",
            ),
            InputField(
                name="settlement_date",
                label="Valuation Date",
                field_type=FieldType.DATE,
                default="2026-08-03",
            ),
            InputField(
                name="start_date",
                label="Period Start",
                field_type=FieldType.DATE,
                default="2027-02-03",
                tooltip="When the underlying rate period begins (e.g. 6×12 FRA).",
            ),
            InputField(
                name="end_date",
                label="Period End",
                field_type=FieldType.DATE,
                default="2027-08-03",
            ),
            InputField(
                name="day_count",
                label="Day Count",
                field_type=FieldType.SELECT,
                choices=tuple(dc.value for dc in DayCount),
                default=DayCount.ACT_360.value,
                tooltip="ACT/360 is the money-market standard.",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> ForwardRateAgreement:
        return cls(
            notional=float(inputs["notional"]),
            fixed_rate=float(inputs["fixed_rate"]) / 100.0,
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            start_date=date.fromisoformat(str(inputs["start_date"])),
            end_date=date.fromisoformat(str(inputs["end_date"])),
            position=str(inputs.get("position", "Pay fixed")),
            day_count=DayCount(inputs.get("day_count", DayCount.ACT_360.value)),
        )
