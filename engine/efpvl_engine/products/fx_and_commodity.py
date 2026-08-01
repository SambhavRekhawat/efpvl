"""FX Forward, Commodity Futures, and the Cost of Carry model that prices both.

Both products are the same argument wearing different clothes: the fair
forward price is spot grossed up by the net cost of carrying the asset to
delivery. For FX the carry is the interest differential (covered interest
parity); for a commodity it is financing plus storage minus the convenience
yield of holding the physical. Value of an existing contract is then just
the discounted gap between today's fair forward and the price you locked.
"""

from __future__ import annotations

import math
import time
from typing import Any

from efpvl_engine.core.base import (
    MarketData,
    PricingModel,
    Product,
    register_model,
    register_product,
)
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta

# --------------------------------------------------------------------------- #
# Products                                                                     #
# --------------------------------------------------------------------------- #


@register_product
class FXForward(Product):
    product_id = "fx_forward"

    def __init__(
        self,
        notional_foreign: float,
        spot_fx: float,
        contract_rate: float,
        foreign_rate: float,
        time_to_delivery: float,
        position: str = "Buy foreign",
        domestic_rate: float | None = None,
    ) -> None:
        if spot_fx <= 0 or contract_rate <= 0:
            raise ValueError("FX rates must be positive")
        if time_to_delivery <= 0:
            raise ValueError("time to delivery must be positive")
        if position not in ("Buy foreign", "Sell foreign"):
            raise ValueError("position must be 'Buy foreign' or 'Sell foreign'")
        self.notional_foreign = notional_foreign
        self.spot_fx = spot_fx  # domestic per 1 foreign (e.g. EURUSD)
        self.contract_rate = contract_rate
        self.foreign_rate = foreign_rate
        self.time_to_delivery = time_to_delivery
        self.position = position
        self.domestic_rate = domestic_rate  # None -> curve zero rate at T

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="FX Forward",
            asset_class="FX",
            summary=(
                "Lock an exchange rate for a future date. Covered interest "
                "parity sets the fair forward from the two currencies' rates; "
                "value is the discounted gap to your locked rate."
            ),
            supported_models=("cost_of_carry",),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="notional_foreign",
                label="Foreign Notional",
                field_type=FieldType.NUMBER,
                unit="FOR",
                default=1_000_000.0,
                min_value=1.0,
                max_value=1e10,
                tooltip="Amount of foreign currency to be exchanged.",
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
                tooltip="Domestic per 1 foreign. Snapshot EURUSD: 1.09.",
            ),
            InputField(
                name="contract_rate",
                label="Contract Forward Rate",
                field_type=FieldType.NUMBER,
                unit="DOM/FOR",
                default=1.09,
                min_value=0.0001,
                max_value=100_000.0,
                step=0.0001,
                tooltip="The rate locked in your forward contract.",
            ),
            InputField(
                name="foreign_rate",
                label="Foreign Interest Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=2.5,
                min_value=-5.0,
                max_value=25.0,
                step=0.05,
                tooltip="Continuously compounded deposit rate of the foreign currency.",
            ),
            InputField(
                name="domestic_rate",
                label="Domestic Interest Rate",
                field_type=FieldType.PERCENT,
                unit="%",
                default=None,
                min_value=-5.0,
                max_value=25.0,
                required=False,
                tooltip="Leave blank to read the domestic zero curve at delivery.",
            ),
            InputField(
                name="time_to_delivery",
                label="Time to Delivery",
                field_type=FieldType.NUMBER,
                unit="years",
                default=1.0,
                min_value=1 / 365,
                max_value=30.0,
                step=0.25,
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Buy foreign", "Sell foreign"),
                default="Buy foreign",
                tooltip="Buy foreign profits when the forward rate rises.",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> FXForward:
        dom = inputs.get("domestic_rate")
        return cls(
            notional_foreign=float(inputs["notional_foreign"]),
            spot_fx=float(inputs["spot_fx"]),
            contract_rate=float(inputs["contract_rate"]),
            foreign_rate=float(inputs["foreign_rate"]) / 100.0,
            time_to_delivery=float(inputs["time_to_delivery"]),
            position=str(inputs.get("position", "Buy foreign")),
            domestic_rate=None if dom in (None, "") else float(dom) / 100.0,
        )


@register_product
class CommodityFutures(Product):
    product_id = "commodity_futures"

    def __init__(
        self,
        contracts_units: float,
        spot_price: float,
        contract_price: float,
        storage_cost: float,
        convenience_yield: float,
        time_to_delivery: float,
        position: str = "Long",
        risk_free_rate: float | None = None,
    ) -> None:
        if spot_price <= 0 or contract_price <= 0:
            raise ValueError("prices must be positive")
        if time_to_delivery <= 0:
            raise ValueError("time to delivery must be positive")
        if position not in ("Long", "Short"):
            raise ValueError("position must be 'Long' or 'Short'")
        self.contracts_units = contracts_units
        self.spot_price = spot_price
        self.contract_price = contract_price
        self.storage_cost = storage_cost  # decimal, per year, proportional
        self.convenience_yield = convenience_yield
        self.time_to_delivery = time_to_delivery
        self.position = position
        self.risk_free_rate = risk_free_rate

    @classmethod
    def meta(cls) -> ProductMeta:
        return ProductMeta(
            product_id=cls.product_id,
            display_name="Commodity Futures",
            asset_class="Commodity",
            summary=(
                "Agree today on a price for future delivery. Fair futures = "
                "spot grossed up by financing and storage, net of the "
                "convenience of holding the physical barrel."
            ),
            supported_models=("cost_of_carry",),
        )

    @classmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        return (
            InputField(
                name="contracts_units",
                label="Quantity",
                field_type=FieldType.NUMBER,
                unit="units",
                default=1000.0,
                min_value=1.0,
                max_value=1e9,
                tooltip="Units of the commodity (e.g. barrels).",
            ),
            InputField(
                name="spot_price",
                label="Spot Price",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=78.4,
                min_value=0.01,
                max_value=1e6,
                step=0.1,
                tooltip="Snapshot WTI spot: 78.40.",
            ),
            InputField(
                name="contract_price",
                label="Contract Futures Price",
                field_type=FieldType.NUMBER,
                unit="USD",
                default=80.0,
                min_value=0.01,
                max_value=1e6,
                step=0.1,
            ),
            InputField(
                name="storage_cost",
                label="Storage Cost",
                field_type=FieldType.PERCENT,
                unit="%/yr",
                default=2.0,
                min_value=0.0,
                max_value=50.0,
                step=0.1,
                tooltip="Proportional cost of storing the physical, per year.",
            ),
            InputField(
                name="convenience_yield",
                label="Convenience Yield",
                field_type=FieldType.PERCENT,
                unit="%/yr",
                default=1.5,
                min_value=0.0,
                max_value=50.0,
                step=0.1,
                tooltip=(
                    "The implicit benefit of holding the physical commodity "
                    "(never running dry). High when inventories are tight — "
                    "the source of backwardation."
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
                tooltip="Leave blank to read the zero curve at delivery.",
            ),
            InputField(
                name="time_to_delivery",
                label="Time to Delivery",
                field_type=FieldType.NUMBER,
                unit="years",
                default=0.5,
                min_value=1 / 365,
                max_value=10.0,
                step=0.25,
            ),
            InputField(
                name="position",
                label="Position",
                field_type=FieldType.SELECT,
                choices=("Long", "Short"),
                default="Long",
            ),
        )

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> CommodityFutures:
        r = inputs.get("risk_free_rate")
        return cls(
            contracts_units=float(inputs["contracts_units"]),
            spot_price=float(inputs["spot_price"]),
            contract_price=float(inputs["contract_price"]),
            storage_cost=float(inputs["storage_cost"]) / 100.0,
            convenience_yield=float(inputs["convenience_yield"]) / 100.0,
            time_to_delivery=float(inputs["time_to_delivery"]),
            position=str(inputs.get("position", "Long")),
            risk_free_rate=None if r in (None, "") else float(r) / 100.0,
        )


# --------------------------------------------------------------------------- #
# Model                                                                        #
# --------------------------------------------------------------------------- #


@register_model
class CostOfCarry(PricingModel):
    model_id = "cost_of_carry"
    display_name = "Cost of Carry / Interest Parity"

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, (FXForward, CommodityFutures))

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        t0 = time.perf_counter()
        if isinstance(product, FXForward):
            result = self._price_fx(product, market)
        elif isinstance(product, CommodityFutures):
            result = self._price_commodity(product, market)
        else:  # pragma: no cover
            raise TypeError("cost_of_carry prices FX forwards and futures")
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result

    # -- FX ------------------------------------------------------------- #

    @staticmethod
    def _domestic_rate(product, market: MarketData) -> float:
        if getattr(product, "risk_free_rate", None) is not None:
            return product.risk_free_rate
        if getattr(product, "domestic_rate", None) is not None:
            return product.domestic_rate
        if hasattr(market, "curve"):
            t = product.time_to_delivery
            return market.curve.zero_rate(t)
        return market.value("risk_free_rate")[0]  # pragma: no cover

    def _price_fx(self, fx: FXForward, market: MarketData) -> ValuationResult:
        T = fx.time_to_delivery
        r_d = self._domestic_rate(fx, market)
        r_f = fx.foreign_rate
        fwd = fx.spot_fx * math.exp((r_d - r_f) * T)
        df_d = market.discount_factor(T)
        sign = 1.0 if fx.position == "Buy foreign" else -1.0
        value = sign * fx.notional_foreign * (fwd - fx.contract_rate) * df_d
        fwd_points = (fwd - fx.spot_fx) * 10_000.0

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=fx.product_id,
            model_id=self.model_id,
            explanation_key="cost_of_carry.fx_forward",
        )
        result.add_step(
            CalculationStep(
                label="Fair forward (covered interest parity)",
                symbol="F",
                value=fwd,
                formula=r"F = S \, e^{(r_d - r_f)T}",
                inputs={"S": fx.spot_fx, "r_d": r_d, "r_f": r_f, "T": T},
                note="Any other forward lets you borrow one currency, lend "
                "the other, and lock a riskless profit — so this one holds.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Forward points",
                symbol="F - S",
                value=fwd_points,
                note="Quoted in pips (1e-4). Sign follows the rate "
                "differential: higher domestic rates ⇒ forward above spot.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"Value ({fx.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm N_f (F - K) \, DF_d(T)",
                inputs={"K": fx.contract_rate},
            )
        )
        result.outputs = {
            "fair_forward": fwd,
            "forward_points_pips": fwd_points,
            "rate_differential": r_d - r_f,
            "domestic_rate_used": r_d,
        }
        return result

    # -- Commodity -------------------------------------------------------- #

    def _price_commodity(
        self, fut: CommodityFutures, market: MarketData
    ) -> ValuationResult:
        T = fut.time_to_delivery
        r = self._domestic_rate(fut, market)
        carry = r + fut.storage_cost - fut.convenience_yield
        fwd = fut.spot_price * math.exp(carry * T)
        df = market.discount_factor(T)
        sign = 1.0 if fut.position == "Long" else -1.0
        value = sign * fut.contracts_units * (fwd - fut.contract_price) * df

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=fut.product_id,
            model_id=self.model_id,
            explanation_key="cost_of_carry.commodity_futures",
        )
        result.add_step(
            CalculationStep(
                label="Net cost of carry",
                symbol="c",
                value=carry,
                formula=r"c = r + u - y",
                inputs={"r": r, "u": fut.storage_cost, "y": fut.convenience_yield},
                note="Financing plus storage, minus the convenience of "
                "holding the physical. Negative carry ⇒ backwardation.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Fair futures price",
                symbol="F",
                value=fwd,
                formula=r"F = S \, e^{(r + u - y)T}",
                inputs={"S": fut.spot_price, "T": T},
            )
        )
        result.add_step(
            CalculationStep(
                label=f"Value ({fut.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm Q (F - K) \, DF(T)",
                inputs={"K": fut.contract_price},
            )
        )
        result.outputs = {
            "fair_futures_price": fwd,
            "net_carry": carry,
            "basis": fwd - fut.spot_price,
            "risk_free_rate_used": r,
        }
        return result

    # -- Risk ------------------------------------------------------------- #

    def risk_measures(self, product: Product, market: MarketData) -> dict[str, float]:
        h_frac = 1e-5
        base = self.price(product, market).fair_value

        if isinstance(product, FXForward):
            # Analytic FX delta: dV/dS = ±N e^{-r_f T} (curve-consistent form)
            bumped = FXForward(
                product.notional_foreign,
                product.spot_fx * (1 + h_frac),
                product.contract_rate,
                product.foreign_rate,
                product.time_to_delivery,
                product.position,
                product.domestic_rate,
            )
            dS = product.spot_fx * h_frac
            fx_delta = (self.price(bumped, market).fair_value - base) / dS
            return {"fx_delta": fx_delta, "npv": base}

        if isinstance(product, CommodityFutures):
            bumped = CommodityFutures(
                product.contracts_units,
                product.spot_price * (1 + h_frac),
                product.contract_price,
                product.storage_cost,
                product.convenience_yield,
                product.time_to_delivery,
                product.position,
                product.risk_free_rate,
            )
            dS = product.spot_price * h_frac
            spot_delta = (self.price(bumped, market).fair_value - base) / dS
            return {"spot_delta": spot_delta, "npv": base}

        raise NotImplementedError  # pragma: no cover
