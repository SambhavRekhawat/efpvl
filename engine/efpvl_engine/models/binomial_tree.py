"""Cox–Ross–Rubinstein binomial tree for European options.

The tree discretizes the lognormal world into up/down moves calibrated so
the discrete model converges to Black–Scholes as steps grow. Included here
for two teaching reasons: it makes risk-neutral pricing *visible* (a real
probability q you can point at), and its convergence to the closed form is
the Model Comparison page's first honest story. It also lays the machinery
that American exercise and callables will need in later phases.
"""

from __future__ import annotations

import math
import time

import numpy as np

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.european_option import EuropeanOption

_STEPS = 500  # fixed for determinism; exposed as an output, not an input


@register_model
class BinomialTree(PricingModel):
    model_id = "binomial_tree"
    display_name = "Binomial Tree (CRR)"

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

        n = _STEPS
        dt = T / n
        u = math.exp(sigma * math.sqrt(dt))
        d = 1.0 / u
        disc = math.exp(-r * dt)
        p_up = (math.exp((r - q) * dt) - d) / (u - d)
        if not 0.0 < p_up < 1.0:
            raise ValueError(
                "Risk-neutral probability outside (0,1) — inputs imply "
                "arbitrage at this step size."
            )

        # Terminal prices and payoffs, then backward induction (vectorized).
        j = np.arange(n + 1)
        s_terminal = S * u**j * d ** (n - j)
        if product.option_type == "Call":
            values = np.maximum(s_terminal - K, 0.0)
        else:
            values = np.maximum(K - s_terminal, 0.0)
        for _ in range(n):
            values = disc * (p_up * values[1:] + (1.0 - p_up) * values[:-1])
        value = float(values[0])

        intrinsic = product.intrinsic_value()
        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="binomial_tree.european_option",
        )
        result.add_step(
            CalculationStep(
                label="Up factor",
                symbol="u",
                value=u,
                formula=r"u = e^{\sigma\sqrt{\Delta t}}",
                inputs={"sigma": sigma, "dt": dt},
                note=f"{n} steps of {dt * 365:.1f} days each.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Down factor", symbol="d", value=d, formula=r"d = 1/u"
            )
        )
        result.add_step(
            CalculationStep(
                label="Risk-neutral up probability",
                symbol="q",
                value=p_up,
                formula=r"q = \frac{e^{(r - \delta)\Delta t} - d}{u - d}",
                note="Not a forecast — the unique probability making the "
                "discounted stock a fair game. Risk-neutral pricing, visible.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Backward-induced value",
                symbol="V_0",
                value=value,
                formula=r"V_{t} = e^{-r\Delta t}\,[\,q V_{up} + (1-q) V_{down}\,]",
            )
        )
        result.add_step(
            CalculationStep(
                label="Time value", symbol="V_{time}", value=value - intrinsic
            )
        )
        result.outputs = {
            "fair_value": value,
            "intrinsic_value": intrinsic,
            "time_value": value - intrinsic,
            "steps": float(n),
            "up_factor": u,
            "risk_neutral_p": p_up,
            "risk_free_rate_used": r,
            "dividend_yield_used": q,
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
