"""Phase 0 smoke tests.

These prove the architectural plumbing before any real finance exists:
registry, schema-driven validation, MarketData interface, and the rule that
every model must emit a calculation trace. The dummy product here is a
deliberately trivial "T-year unit cash flow" so the numbers are checkable by
hand.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from efpvl_engine import (
    CalculationStep,
    FieldType,
    InputField,
    MarketData,
    PricingModel,
    Product,
    ProductMeta,
    ValuationResult,
    get_model,
    get_product,
    models_for,
    register_model,
    register_product,
)
from efpvl_engine.core import base as base_mod


@pytest.fixture(autouse=True)
def _clean_registries():
    """Run each test against empty registries, then restore the real ones."""
    saved_products = dict(base_mod._PRODUCTS)
    saved_models = dict(base_mod._MODELS)
    base_mod.clear_registries()
    yield
    base_mod.clear_registries()
    base_mod._PRODUCTS.update(saved_products)
    base_mod._MODELS.update(saved_models)


class FlatCurve(MarketData):
    """Continuously compounded flat curve: DF(t) = exp(-r t)."""

    def __init__(self, rate: float) -> None:
        self.rate = rate

    def discount_factor(self, t_years: float) -> float:
        return math.exp(-self.rate * t_years)

    def describe(self) -> dict[str, Any]:
        return {"type": "flat_curve", "rate": self.rate}


def _make_dummy_product() -> type[Product]:
    @register_product
    class UnitCashFlow(Product):
        product_id = "unit_cash_flow"

        def __init__(self, amount: float, maturity_years: float) -> None:
            self.amount = amount
            self.maturity_years = maturity_years

        @classmethod
        def meta(cls) -> ProductMeta:
            return ProductMeta(
                product_id=cls.product_id,
                display_name="Unit Cash Flow (test)",
                asset_class="Test",
                summary="Single cash flow at maturity; Phase 0 plumbing check.",
                supported_models=("discounting_test",),
            )

        @classmethod
        def input_schema(cls) -> tuple[InputField, ...]:
            return (
                InputField(
                    name="amount",
                    label="Amount",
                    field_type=FieldType.NUMBER,
                    unit="USD",
                    default=100.0,
                    min_value=0.0,
                    max_value=1e9,
                ),
                InputField(
                    name="maturity_years",
                    label="Maturity",
                    field_type=FieldType.NUMBER,
                    unit="years",
                    default=1.0,
                    min_value=0.0,
                    max_value=100.0,
                ),
            )

        @classmethod
        def from_inputs(cls, inputs: dict[str, Any]) -> UnitCashFlow:
            return cls(float(inputs["amount"]), float(inputs["maturity_years"]))

    return UnitCashFlow


def _make_dummy_model() -> type[PricingModel]:
    @register_model
    class DiscountingTest(PricingModel):
        model_id = "discounting_test"
        display_name = "Discounting (test)"

        @classmethod
        def supports(cls, product: Product) -> bool:
            return product.product_id == "unit_cash_flow"

        def price(self, product: Product, market: MarketData) -> ValuationResult:
            df = market.discount_factor(product.maturity_years)
            result = ValuationResult(
                fair_value=product.amount * df,
                currency="USD",
                product_id=product.product_id,
                model_id=self.model_id,
            )
            result.add_step(
                CalculationStep(
                    label=f"Discount factor DF({product.maturity_years}y)",
                    symbol="DF(t)",
                    value=df,
                    formula=r"DF(t) = e^{-rt}",
                    inputs={"t": product.maturity_years},
                    note="Present value of 1 unit paid at maturity.",
                )
            )
            result.add_step(
                CalculationStep(
                    label="Present value",
                    symbol="PV",
                    value=product.amount * df,
                    formula=r"PV = A \cdot DF(t)",
                    inputs={"amount": product.amount, "df": df},
                )
            )
            return result

    return DiscountingTest


# --------------------------------------------------------------------------- #
# Registry                                                                     #
# --------------------------------------------------------------------------- #


def test_registration_and_lookup():
    prod_cls = _make_dummy_product()
    model_cls = _make_dummy_model()
    assert get_product("unit_cash_flow") is prod_cls
    assert get_model("discounting_test") is model_cls


def test_duplicate_registration_rejected():
    _make_dummy_product()
    with pytest.raises(ValueError, match="Duplicate product_id"):
        _make_dummy_product()


def test_unknown_ids_raise():
    with pytest.raises(KeyError):
        get_product("does_not_exist")
    with pytest.raises(KeyError):
        get_model("does_not_exist")


def test_models_for_filters_by_support():
    prod_cls = _make_dummy_product()
    model_cls = _make_dummy_model()
    product = prod_cls(100.0, 1.0)
    assert models_for(product) == [model_cls]


# --------------------------------------------------------------------------- #
# Schema validation                                                            #
# --------------------------------------------------------------------------- #


def test_valid_inputs_pass():
    prod_cls = _make_dummy_product()
    assert prod_cls.validate({"amount": 100, "maturity_years": 2}) == []


def test_out_of_range_and_missing_and_unknown_inputs_fail():
    prod_cls = _make_dummy_product()
    errors = prod_cls.validate({"amount": -5, "banana": 1})
    fields = {e.field for e in errors}
    assert "amount" in fields  # below min
    assert "maturity_years" in fields  # missing required
    assert "banana" in fields  # unknown field


def test_non_numeric_rejected():
    prod_cls = _make_dummy_product()
    errors = prod_cls.validate({"amount": "abc", "maturity_years": 1})
    assert any(e.field == "amount" for e in errors)


# --------------------------------------------------------------------------- #
# Pricing round trip + explainability contract                                 #
# --------------------------------------------------------------------------- #


def test_end_to_end_pricing_matches_hand_calc():
    prod_cls = _make_dummy_product()
    model_cls = _make_dummy_model()
    product = prod_cls.from_inputs({"amount": 100.0, "maturity_years": 2.0})
    market = FlatCurve(rate=0.05)

    result = model_cls().price(product, market)

    expected = 100.0 * math.exp(-0.05 * 2.0)  # 90.4837...
    assert result.fair_value == pytest.approx(expected, rel=1e-12)


def test_models_must_emit_calculation_trace():
    """The explainability contract: a bare number is a broken model."""
    prod_cls = _make_dummy_product()
    model_cls = _make_dummy_model()
    result = model_cls().price(prod_cls(100.0, 1.0), FlatCurve(0.04))

    assert len(result.steps) > 0
    serialized = result.to_dict()
    assert serialized["steps"][0]["label"].startswith("Discount factor")
    assert serialized["fair_value"] == pytest.approx(result.fair_value)
    assert "as_of" in serialized
