"""European Call / Put option.

The right — not the obligation — to buy (call) or sell (put) the underlying
at the strike on the expiry date. Phase 1 values it with Black–Scholes;
binomial trees and Monte Carlo join in Phase 5 so the Model Comparison page
can show convergence to the closed form.
"""

from __future__ import annotations

from typing import Any

from efpvl_engine.core.base import Product, register_product
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta


@register_product
class EuropeanOption(Product):
    product_id = "european_option"

    def __init__(
        self,
        option_type: str,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
    ) -> None:
        if option_type not in ("Call", "Put"):
            raise ValueError("option_type must be 'Call' or 'Put'")
        if spot <= 0 or strike <= 0:
            raise ValueError("spot and strike must be positive")
        if time_to_expiry <= 0:
            raise ValueError("time to expiry must be positive")
        if volatility <= 0:
            raise ValueError("volatility must be positive")
        self.option_type = option_type
        self.spot = spot
        self.strike = strike
        self.time_to_expiry = time_to_expiry
        self.volatility = volatility  # decimal, e.g. 0.20
        # None -> pull from the market snapshot at pricing time
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield

    def intrinsic_value(self) -> float:
        """Exercise value if expiry were now: max(S-K, 0) or max(K-S, 0)."""
        if self.option_type == "Call":
            return max(self.spot - self.strike, 0.0)
        return max(self.strike - self.spot, 0.0)

    # ------------------------------------------------------------------ #

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="European Option (Call / Put)",
            asset_class="Equity",
            summary=(
                "The right to buy (call) or sell (put) at the strike on expiry. "
                "Valued with Black–Scholes; decomposes into intrinsic and time value."
            ),
            supported_models=(
                "black_scholes",
                "binomial_tree",
                "monte_carlo",
                "heston",
                "merton_jump_diffusion",
                "sabr",
            ),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="option_type",
                label="Option Type",
                field_type=FieldType.SELECT,
                choices=("Call", "Put"),
                default="Call",
            ),
            InputField(
                name="spot",
                label="Spot Price",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=100.0,
                min_value=0.01,
                max_value=1e7,
                tooltip="Current price of the underlying asset.",
            ),
            InputField(
                name="strike",
                label="Strike Price",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=100.0,
                min_value=0.01,
                max_value=1e7,
                tooltip="Agreed exercise price.",
            ),
            InputField(
                name="time_to_expiry",
                label="Time to Expiry",
                field_type=FieldType.NUMBER,
                unit="years",
                default=1.0,
                min_value=1 / 365,
                max_value=30.0,
                step=0.25,
                tooltip="Years until expiry; 0.5 = six months.",
            ),
            InputField(
                name="volatility",
                label="Volatility",
                field_type=FieldType.PERCENT,
                unit="%",
                default=20.0,
                min_value=0.1,
                max_value=300.0,
                step=0.5,
                tooltip=(
                    "Annualized volatility of the underlying's returns — the "
                    "only Black–Scholes input that is not directly observable."
                ),
            ),
            InputField(
                name="risk_free_rate",
                label="Risk-Free Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=None,
                min_value=-5.0,
                max_value=25.0,
                required=False,
                tooltip="Leave blank to use the market snapshot rate.",
            ),
            InputField(
                name="dividend_yield",
                label="Dividend Yield",
                field_type=FieldType.PERCENT,
                unit="%",
                default=None,
                min_value=0.0,
                max_value=25.0,
                required=False,
                tooltip="Leave blank to use the market snapshot yield.",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> EuropeanOption:
        def _opt_pct(key: str) -> float | None:
            v = inputs.get(key)
            return None if v in (None, "") else float(v) / 100.0

        return cls(
            option_type=str(inputs["option_type"]),
            spot=float(inputs["spot"]),
            strike=float(inputs["strike"]),
            time_to_expiry=float(inputs["time_to_expiry"]),
            volatility=float(inputs["volatility"]) / 100.0,
            risk_free_rate=_opt_pct("risk_free_rate"),
            dividend_yield=_opt_pct("dividend_yield"),
        )
