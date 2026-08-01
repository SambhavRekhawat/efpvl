"""Vasicek short-rate model (1977) for zero coupon bonds.

The first mean-reverting interest rate model: dr = a(b − r)dt + σ dW. Rates
are pulled toward a long-run level b at speed a, and the zero coupon bond
has the famous affine closed form P(T) = A(T) e^{−B(T) r₀}.

Calibration in this laboratory (documented, visible in every trace):
r₀ is read from the short end of the market curve and b from its 10y point;
a and σ are fixed classroom constants. The model's price therefore *differs*
from the market-curve DCF price by construction — and that gap is the
teaching point on the Model Comparison page: a parametric model's view of
discounting versus the curve's direct quotation.
"""

from __future__ import annotations

import math
import time

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond


@register_model
class Vasicek(PricingModel):
    model_id = "vasicek"
    display_name = "Vasicek Short Rate"

    # Classroom calibration — class attributes so tests can override.
    MEAN_REVERSION_A = 0.15  # speed of pull toward the long-run level
    SIGMA_R = 0.01  # absolute rate volatility (100bp/yr)

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, ZeroCouponBond)

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, ZeroCouponBond)
        t0 = time.perf_counter()

        T = product.time_to_maturity()
        a, sigma = self.MEAN_REVERSION_A, self.SIGMA_R
        r0 = market.curve.zero_rate(1.0 / 12.0)  # short end of the curve
        b = market.curve.zero_rate(10.0)  # long-run anchor

        B = (1.0 - math.exp(-a * T)) / a
        ln_a_term = (B - T) * (a * a * b - 0.5 * sigma * sigma) / (a * a)
        ln_a_term -= sigma * sigma * B * B / (4.0 * a)
        A = math.exp(ln_a_term)
        p_zero = A * math.exp(-B * r0)
        value = product.face_value * p_zero

        model_yield = -math.log(p_zero) / T
        market_df = market.discount_factor(T)

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="vasicek.zero_coupon_bond",
        )
        result.add_step(
            CalculationStep(
                label="Calibrated short rate",
                symbol="r_0",
                value=r0,
                note="Read from the 1-month point of the market curve.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Long-run mean level",
                symbol="b",
                value=b,
                note=f"The 10y curve point; mean reversion speed a = {a}, "
                f"rate vol sigma = {sigma:.2%}/yr (fixed classroom values).",
            )
        )
        result.add_step(
            CalculationStep(
                label="Duration factor",
                symbol="B(T)",
                value=B,
                formula=r"B(T) = \frac{1 - e^{-aT}}{a}",
                note="How long the bond effectively feels today's rate; "
                "approaches 1/a for long maturities — mean reversion caps "
                "long-bond rate risk.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Level factor",
                symbol="A(T)",
                value=A,
                formula=(
                    r"\ln A = (B - T)\frac{a^2 b - \sigma^2/2}{a^2}"
                    r" - \frac{\sigma^2 B^2}{4a}"
                ),
            )
        )
        result.add_step(
            CalculationStep(
                label="Model discount factor",
                symbol="P(T)",
                value=p_zero,
                formula=r"P(T) = A(T)\, e^{-B(T) r_0}",
                note=f"Compare with the market curve's DF(T) = {market_df:.6f}: "
                "the gap is the model's parametric opinion vs the curve's "
                "direct quotation.",
            )
        )
        result.outputs = {
            "model_discount_factor": p_zero,
            "market_discount_factor": market_df,
            "model_implied_yield": model_yield,
            "short_rate_r0": r0,
            "long_run_mean_b": b,
            "mean_reversion_a": a,
            "rate_volatility": sigma,
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
