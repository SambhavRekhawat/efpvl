"""Credit Default Swap.

Insurance on a borrower: the protection buyer pays a running premium
(spread) and, if the reference entity defaults, receives the loss
(1 − recovery) on the notional. Valued with a reduced-form (hazard rate)
model: default arrives as a Poisson event with intensity λ, giving survival
probabilities Q(t) = e^{−λt} that weight both legs.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.daycount import DayCount
from efpvl_engine.market.schedule import accrual_periods, roll_back_schedule

_FREQ = {"Quarterly": 4, "Semiannual": 2, "Annual": 1}


@register_product
class CreditDefaultSwap(Product):
    product_id = "credit_default_swap"

    def __init__(
        self,
        notional: float,
        contract_spread_bps: float,
        market_spread_bps: float,
        recovery_rate: float,
        frequency: int,
        settlement_date: date,
        maturity_date: date,
        position: str = "Buy protection",
        day_count: DayCount = DayCount.ACT_360,
    ) -> None:
        if maturity_date <= settlement_date:
            raise ValueError("maturity must be after settlement")
        if not 0.0 <= recovery_rate < 1.0:
            raise ValueError("recovery rate must be in [0, 1)")
        if market_spread_bps <= 0:
            raise ValueError("market spread must be positive")
        if position not in ("Buy protection", "Sell protection"):
            raise ValueError("position must be 'Buy protection' or 'Sell protection'")
        self.notional = notional
        self.contract_spread_bps = contract_spread_bps
        self.market_spread_bps = market_spread_bps
        self.recovery_rate = recovery_rate
        self.frequency = frequency
        self.settlement_date = settlement_date
        self.maturity_date = maturity_date
        self.position = position
        self.day_count = day_count

    @property
    def contract_spread(self) -> float:
        return self.contract_spread_bps / 10_000.0

    @property
    def market_spread(self) -> float:
        return self.market_spread_bps / 10_000.0

    def periods(self) -> list[tuple[date, date, float]]:
        pay_dates = roll_back_schedule(
            self.settlement_date, self.maturity_date, self.frequency
        )
        return accrual_periods(self.settlement_date, pay_dates, self.day_count)

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Credit Default Swap",
            asset_class="Credit",
            summary=(
                "Default insurance: pay a running spread, receive the loss if "
                "the borrower fails. Priced with survival probabilities from a "
                "hazard rate implied by the market spread."
            ),
            supported_models=("hazard_rate",),
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
                name="contract_spread_bps",
                label="Contract Spread",
                field_type=FieldType.NUMBER,
                unit="bp",
                default=100.0,
                min_value=0.0,
                max_value=5000.0,
                step=1.0,
                tooltip="The premium you locked in the contract, per year.",
            ),
            InputField(
                name="market_spread_bps",
                label="Market Spread",
                field_type=FieldType.NUMBER,
                unit="bp",
                default=95.0,
                min_value=1.0,
                max_value=5000.0,
                step=1.0,
                tooltip=(
                    "Where the market quotes this credit today; drives the "
                    "implied hazard rate. Snapshot IG 5y: 95bp."
                ),
            ),
            InputField(
                name="recovery_rate",
                label="Recovery Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=40.0,
                min_value=0.0,
                max_value=95.0,
                step=1.0,
                tooltip="Fraction of notional recovered in default; 40% is standard.",
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Buy protection", "Sell protection"),
                default="Buy protection",
                tooltip="Buying protection = short the credit.",
            ),
            InputField(
                name="frequency",
                label="Premium Frequency",
                field_type=FieldType.SELECT,
                choices=tuple(_FREQ),
                default="Quarterly",
                tooltip="Quarterly is the CDS market standard.",
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
                tooltip="5y is the most liquid CDS tenor.",
            ),
            InputField(
                name="day_count",
                label="Day Count",
                field_type=FieldType.SELECT,
                choices=tuple(dc.value for dc in DayCount),
                default=DayCount.ACT_360.value,
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> CreditDefaultSwap:
        return cls(
            notional=float(inputs["notional"]),
            contract_spread_bps=float(inputs["contract_spread_bps"]),
            market_spread_bps=float(inputs["market_spread_bps"]),
            recovery_rate=float(inputs["recovery_rate"]) / 100.0,
            frequency=_FREQ[str(inputs["frequency"])],
            settlement_date=date.fromisoformat(str(inputs["settlement_date"])),
            maturity_date=date.fromisoformat(str(inputs["maturity_date"])),
            position=str(inputs.get("position", "Buy protection")),
            day_count=DayCount(inputs.get("day_count", DayCount.ACT_360.value)),
        )
