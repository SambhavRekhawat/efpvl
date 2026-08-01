"""Monte Carlo pricing for European options.

Simulate terminal prices under the risk-neutral GBM, average the discounted
payoff. For a European payoff the terminal distribution is known in closed
form, so one exact step suffices — no path discretization error, leaving
*sampling* error as the only error, which the model reports honestly as a
standard error and 95% confidence band.

Deliberately deterministic (fixed seed) so results are reproducible in a
teaching setting; antithetic variates halve the variance for symmetric-ish
payoffs and are traced so learners see variance reduction working.
"""

from __future__ import annotations

import math
import time

import numpy as np

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.european_option import EuropeanOption

_N_PAIRS = 100_000  # 200k effective draws with antithetics
_SEED = 20260801


@register_model
class MonteCarlo(PricingModel):
    model_id = "monte_carlo"
    display_name = "Monte Carlo (GBM)"

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, EuropeanOption)

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, EuropeanOption)
        t0 = time.perf_counter()

        S, K = product.spot, product.strike
        T, sigma = product.time_to_expiry, product.volatility
        r = (
            product.risk_free_rate
            if product.risk_free_rate is not None
            else market.value("risk_free_rate")[0]
        )
        q = (
            product.dividend_yield
            if product.dividend_yield is not None
            else market.value("dividend_yield")[0]
        )

        rng = np.random.default_rng(_SEED)
        z = rng.standard_normal(_N_PAIRS)
        drift = (r - q - 0.5 * sigma**2) * T
        vol_t = sigma * math.sqrt(T)
        s_up = S * np.exp(drift + vol_t * z)
        s_dn = S * np.exp(drift - vol_t * z)  # antithetic partner

        if product.option_type == "Call":
            pay = 0.5 * (np.maximum(s_up - K, 0.0) + np.maximum(s_dn - K, 0.0))
        else:
            pay = 0.5 * (np.maximum(K - s_up, 0.0) + np.maximum(K - s_dn, 0.0))

        df = math.exp(-r * T)
        disc_pay = df * pay
        value = float(disc_pay.mean())
        std_err = float(disc_pay.std(ddof=1) / math.sqrt(_N_PAIRS))
        ci = 1.96 * std_err

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="monte_carlo.european_option",
        )
        result.add_step(
            CalculationStep(
                label="Terminal price simulation",
                symbol="S_T",
                value=float(np.mean(0.5 * (s_up + s_dn))),
                formula=(
                    r"S_T = S \exp\!\big[(r - \delta - \tfrac{1}{2}\sigma^2)T"
                    r" + \sigma\sqrt{T}\,Z\big]"
                ),
                inputs={"pairs": float(_N_PAIRS)},
                note=f"{2 * _N_PAIRS:,} draws as {_N_PAIRS:,} antithetic pairs "
                "(+Z and −Z), exact one-step GBM — no discretization error.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Mean discounted payoff",
                symbol="\\hat{V}",
                value=value,
                formula=r"\hat{V} = e^{-rT}\,\overline{\text{payoff}(S_T)}",
            )
        )
        result.add_step(
            CalculationStep(
                label="Standard error",
                symbol="SE",
                value=std_err,
                formula=r"SE = s / \sqrt{n}",
                note=f"95% confidence band: {value - ci:,.4f} to {value + ci:,.4f}. "
                "Quadrupling the draws halves this — the eternal MC trade-off.",
            )
        )
        result.outputs = {
            "fair_value": value,
            "standard_error": std_err,
            "ci_low_95": value - ci,
            "ci_high_95": value + ci,
            "num_draws": float(2 * _N_PAIRS),
            "intrinsic_value": product.intrinsic_value(),
            "risk_free_rate_used": r,
            "dividend_yield_used": q,
        }
        result.warnings.append(
            f"Monte Carlo estimate — true value lies within ±{ci:.4f} of the "
            "figure above with 95% confidence."
        )
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
