"""Fixed-for-fixed Currency Swap and Inflation-Linked Bond.

Currency swap: two bonds in a trench coat — a domestic fixed leg discounted
on the curve and a foreign fixed leg discounted at a flat foreign rate, the
foreign PV converted at spot. Initial notional exchanges cancel at inception
(N_d = S · N_f); the final exchange is part of each leg.

Inflation-linked bond: real coupons on a principal that grows with the price
index. Projected here at a user-chosen breakeven inflation rate π, discounted
on the nominal curve — so setting π = 0 must reproduce the plain nominal
coupon bond exactly, which the test suite enforces.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount
from efpvl_engine.market.schedule import accrual_periods, roll_back_schedule

_FREQ = {"Annual": 1, "Semiannual": 2, "Quarterly": 4}


@register_product
class CurrencySwap(Product):
    product_id = "currency_swap"

    def __init__(
        self,
        notional_domestic: float,
        spot_fx: float,
        domestic_rate_leg: float,
        foreign_rate_leg: float,
        foreign_discount_rate: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        position: str = "Receive foreign",
        day_count: DayCount = DayCount.THIRTY_360,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        if spot_fx <= 0:
            raise ValueError("spot FX must be positive")
        if position not in ("Receive foreign", "Receive domestic"):
            raise ValueError("position must be 'Receive foreign' or 'Receive domestic'")
        self.notional_domestic = notional_domestic
        self.spot_fx = spot_fx  # domestic per 1 foreign
        self.domestic_rate_leg = domestic_rate_leg
        self.foreign_rate_leg = foreign_rate_leg
        self.foreign_discount_rate = foreign_discount_rate
        self.frequency = frequency
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.position = position
        self.day_count = day_count

    @property
    def notional_foreign(self) -> float:
        return self.notional_domestic / self.spot_fx

    def periods(self) -> list[tuple[date, date, float]]:
        pay_dates = roll_back_schedule(
            self.settlement_date, self.maturity_date, self.frequency
        )
        return accrual_periods(self.settlement_date, pay_dates, self.day_count)

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Currency Swap",
            asset_class="FX",
            summary=(
                "Exchange fixed interest streams (and final notionals) in two "
                "currencies. Two bonds in a trench coat: value each leg on its "
                "own curve, convert at spot, net."
            ),
            supported_models=("discounted_cash_flow",),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="notional_domestic",
                label="Domestic Notional",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=1_000_000.0,
                min_value=1.0,
                max_value=1e10,
                tooltip="Foreign notional = domestic ÷ spot FX at inception.",
            ),
            InputField(
                name="spot_fx",
                label="Spot FX Rate",
                field_type=FieldType.NUMBER,
                unit="DOM/FOR",
                default=1.09,
                min_value=0.0001,
                max_value=100_000.0,
                step=0.0001,
            ),
            InputField(
                name="domestic_rate_leg",
                label="Domestic Leg Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=4.0,
                min_value=-2.0,
                max_value=25.0,
                step=0.05,
            ),
            InputField(
                name="foreign_rate_leg",
                label="Foreign Leg Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=2.5,
                min_value=-2.0,
                max_value=25.0,
                step=0.05,
            ),
            InputField(
                name="foreign_discount_rate",
                label="Foreign Discount Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=2.5,
                min_value=-2.0,
                max_value=25.0,
                step=0.05,
                tooltip="Flat continuously compounded curve for the foreign leg.",
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Receive foreign", "Receive domestic"),
                default="Receive foreign",
            ),
            InputField(
                name="frequency",
                label="Payment Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQ),
                default="Annual",
            ),
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
                default=DayCount.THIRTY_360.value,
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> CurrencySwap:
        return cls(
            notional_domestic=float(inputs["notional_domestic"]),
            spot_fx=float(inputs["spot_fx"]),
            domestic_rate_leg=float(inputs["domestic_rate_leg"]) / 100.0,
            foreign_rate_leg=float(inputs["foreign_rate_leg"]) / 100.0,
            foreign_discount_rate=float(inputs["foreign_discount_rate"]) / 100.0,
            frequency=_FREQ[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            position=str(inputs.get("position", "Receive foreign")),
            day_count=DayCount(inputs.get("day_count", DayCount.THIRTY_360.value)),
        )


@register_product
class InflationLinkedBond(Product):
    product_id = "inflation_linked_bond"

    def __init__(
        self,
        face_value: float,
        real_coupon_rate: float,
        breakeven_inflation: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        day_count: DayCount = DayCount.THIRTY_360,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        if real_coupon_rate < 0:
            raise ValueError("real coupon cannot be negative")
        self.face_value = face_value
        self.real_coupon_rate = real_coupon_rate
        self.breakeven_inflation = breakeven_inflation
        self.frequency = frequency
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.day_count = day_count

    def periods(self) -> list[tuple[date, date, float]]:
        pay_dates = roll_back_schedule(
            self.settlement_date, self.maturity_date, self.frequency
        )
        return accrual_periods(self.settlement_date, pay_dates, self.day_count)

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Inflation-Linked Bond",
            asset_class="Inflation",
            summary=(
                "Coupons and principal grow with the price index (TIPS-style). "
                "Projected at a breakeven inflation rate and discounted on the "
                "nominal curve; at zero breakeven it IS the nominal bond."
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
                tooltip="Initial principal; the index ratio scales it upward.",
            ),
            InputField(
                name="real_coupon_rate",
                label="Real Coupon Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=1.5,
                min_value=0.0,
                max_value=25.0,
                step=0.05,
                tooltip="Coupon on the inflation-adjusted principal. TIPS "
                "real coupons are low — inflation carries the rest.",
            ),
            InputField(
                name="breakeven_inflation",
                label="Breakeven Inflation",
                field_type=FieldType.PERCENT,
                unit="%",
                default=2.3,
                min_value=-5.0,
                max_value=25.0,
                step=0.05,
                tooltip="Assumed annual index growth used to project cash flows.",
            ),
            InputField(
                name="frequency",
                label="Coupon Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQ),
                default="Semiannual",
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
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> InflationLinkedBond:
        return cls(
            face_value=float(inputs["face_value"]),
            real_coupon_rate=float(inputs["real_coupon_rate"]) / 100.0,
            breakeven_inflation=float(inputs["breakeven_inflation"]) / 100.0,
            frequency=_FREQ[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            day_count=DayCount(inputs.get("day_count", DayCount.THIRTY_360.value)),
        )
