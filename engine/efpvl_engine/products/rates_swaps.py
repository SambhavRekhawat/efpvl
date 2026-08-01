"""Vanilla Interest Rate Swap and Floating Rate Note.

Both are exercises in the same two ideas: project each floating coupon as
the curve's simple forward for its period, and discount everything with the
same curve. The elegant consequences — a floating leg that telescopes to
N(1 − DF(T)) and a zero-spread FRN worth exactly par at reset — are used as
exact tests in the suite.

Simplifications (documented, standard for an educational single-curve lab):
one curve projects and discounts; both swap legs share a payment frequency;
front stubs are absorbed into the first accrual period.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount
from efpvl_engine.market.schedule import accrual_periods, roll_back_schedule

_FREQ = {"Annual": 1, "Semiannual": 2, "Quarterly": 4}

_COMMON_DATE_FIELDS = (
    InputField(
        name="settlement_date",
        label="Valuation Date",
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
        default=DayCount.ACT_360.value,
    ),
)


class _ScheduledRatesProduct(Product):
    """Shared schedule plumbing for IRS and FRN."""

    def __init__(
        self,
        notional: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        day_count: DayCount,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        self.notional = notional
        self.frequency = frequency
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.day_count = day_count

    def periods(self) -> list[tuple[date, date, float]]:
        pay_dates = roll_back_schedule(
            self.settlement_date, self.maturity_date, self.frequency
        )
        return accrual_periods(self.settlement_date, pay_dates, self.day_count)


@register_product
class InterestRateSwap(_ScheduledRatesProduct):
    product_id = "interest_rate_swap"

    def __init__(
        self,
        notional: float,
        fixed_rate: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        position: str = "Pay fixed",
        day_count: DayCount = DayCount.ACT_360,
    ) -> None:
        super().__init__(notional, frequency, settlement_date, maturity_date, day_count)
        if position not in ("Pay fixed", "Receive fixed"):
            raise ValueError("position must be 'Pay fixed' or 'Receive fixed'")
        self.fixed_rate = fixed_rate
        self.position = position

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Interest Rate Swap",
            asset_class="Rates",
            summary=(
                "Exchange a fixed rate for the floating rate on a notional. "
                "Worth zero when the fixed rate equals the curve's par rate; "
                "value appears as rates drift away from your lock."
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
                tooltip="The rate on the fixed leg. Compare with the par rate output.",
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Pay fixed", "Receive fixed"),
                default="Pay fixed",
                tooltip="Pay fixed = receive floating: gains when rates rise.",
            ),
            InputField(
                name="frequency",
                label="Payment Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQ),
                default="Semiannual",
                tooltip="Applied to both legs in this laboratory.",
            ),
            *_COMMON_DATE_FIELDS,
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> InterestRateSwap:
        return cls(
            notional=float(inputs["notional"]),
            fixed_rate=float(inputs["fixed_rate"]) / 100.0,
            frequency=_FREQ[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            position=str(inputs.get("position", "Pay fixed")),
            day_count=DayCount(inputs.get("day_count", DayCount.ACT_360.value)),
        )


@register_product
class FloatingRateNote(_ScheduledRatesProduct):
    product_id = "floating_rate_note"

    def __init__(
        self,
        notional: float,
        spread_bps: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        day_count: DayCount = DayCount.ACT_360,
    ) -> None:
        super().__init__(notional, frequency, settlement_date, maturity_date, day_count)
        self.spread_bps = spread_bps

    @property
    def spread(self) -> float:
        return self.spread_bps / 10_000.0

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Floating Rate Note",
            asset_class="Rates",
            summary=(
                "A bond whose coupons reset with the market rate plus a spread. "
                "With zero spread it is worth exactly par at reset — the "
                "cleanest identity in rates, and this engine reproduces it "
                "to machine precision."
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
            ),
            InputField(
                name="spread_bps",
                label="Spread",
                field_type=FieldType.NUMBER,
                unit="bp",
                default=50.0,
                min_value=-200.0,
                max_value=1000.0,
                step=1.0,
                tooltip="Margin over the floating index, in basis points.",
            ),
            InputField(
                name="frequency",
                label="Coupon Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQ),
                default="Quarterly",
                tooltip="Quarterly is standard for floaters.",
            ),
            *_COMMON_DATE_FIELDS,
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> FloatingRateNote:
        return cls(
            notional=float(inputs["notional"]),
            spread_bps=float(inputs["spread_bps"]),
            frequency=_FREQ[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            day_count=DayCount(inputs.get("day_count", DayCount.ACT_360.value)),
        )
