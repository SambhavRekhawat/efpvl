"""Black–Scholes–Merton model for European options.

Closed-form price under lognormal dynamics with continuous dividend yield q:

    Call = S e^{-qT} N(d1) - K e^{-rT} N(d2)
    Put  = K e^{-rT} N(-d2) - S e^{-qT} N(-d1)

    d1 = [ln(S/K) + (r - q + sigma^2/2) T] / (sigma sqrt(T)),   d2 = d1 - sigma sqrt(T)

The trace exposes every quantity a desk quant would sanity-check by hand:
d1, d2, N(d1), N(d2), both discount factors, and the intrinsic/time split.
"""

from __future__ import annotations

import math
import time

from scipy.stats import norm

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.european_option import EuropeanOption

_PHI = norm.pdf  # standard normal density


@register_model
class BlackScholes(PricingModel):
    model_id = "black_scholes"
    display_name = "Black–Scholes–Merton"

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, EuropeanOption)

    def risk_measures(self, product: Product, market: MarketData) -> dict[str, float]:
        """Analytic Greeks (Merton dividend extension).

        Conventions used by desks and mirrored here:
          delta, gamma        — per 1 unit of spot
          vega                — per 1 vol *point* (1%)
          theta               — per calendar day
          rho                 — per 1 rate *point* (1%)
        """
        assert isinstance(product, EuropeanOption)
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

        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        df_r, df_q = math.exp(-r * T), math.exp(-q * T)
        phi_d1 = float(_PHI(d1))
        nd1, nd2 = float(norm.cdf(d1)), float(norm.cdf(d2))

        gamma = df_q * phi_d1 / (S * sigma * sqrt_t)
        vega = S * df_q * phi_d1 * sqrt_t  # per 1.00 of vol

        if product.option_type == "Call":
            delta = df_q * nd1
            theta = (
                -S * df_q * phi_d1 * sigma / (2 * sqrt_t)
                + q * S * df_q * nd1
                - r * K * df_r * nd2
            )
            rho = K * T * df_r * nd2
        else:
            delta = df_q * (nd1 - 1.0)
            theta = (
                -S * df_q * phi_d1 * sigma / (2 * sqrt_t)
                - q * S * df_q * float(norm.cdf(-d1))
                + r * K * df_r * float(norm.cdf(-d2))
            )
            rho = -K * T * df_r * float(norm.cdf(-d2))

        return {
            "delta": delta,
            "gamma": gamma,
            "vega": vega / 100.0,  # per vol point
            "theta": theta / 365.0,  # per day
            "rho": rho / 100.0,  # per rate point
        }

    @classmethod
    def describe(cls) -> dict:
        from efpvl_engine.content import model_content

        try:
            authored = model_content(cls.model_id)
        except (OSError, ValueError):  # unreadable/corrupt file -> fallback
            authored = None
        if authored is not None:
            return authored
        return {
            "model_id": cls.model_id,
            "display_name": cls.display_name,
            "overview": (
                "Closed-form valuation of European options under lognormal "
                "dynamics with constant volatility and rates (Merton "
                "extension for a continuous dividend yield)."
            ),
            "assumptions": [
                "Underlying follows geometric Brownian motion (lognormal prices).",
                "Volatility and rates are constant over the option's life.",
                "Continuous, frictionless hedging; no transaction costs.",
                "European exercise only.",
            ],
            "limitations": [
                "Constant volatility contradicts the observed smile/skew.",
                "Underprices tail risk (no jumps, thin lognormal tails).",
                "Not valid for American or path-dependent payoffs.",
            ],
            "typical_usage": (
                "Vanilla European equity/FX options; the market's quoting "
                "convention via implied volatility."
            ),
            "computational_complexity": "O(1) — closed form.",
        }

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, EuropeanOption)
        t0 = time.perf_counter()

        S, K = product.spot, product.strike
        T, sigma = product.time_to_expiry, product.volatility

        # Rates: user override wins, else market snapshot, with provenance noted.
        if product.risk_free_rate is not None:
            r, r_src = product.risk_free_rate, "user"
        else:
            r, r_src = market.value("risk_free_rate")
        if product.dividend_yield is not None:
            q, q_src = product.dividend_yield, "user"
        else:
            q, q_src = market.value("dividend_yield")

        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        nd1, nd2 = float(norm.cdf(d1)), float(norm.cdf(d2))
        df_r, df_q = math.exp(-r * T), math.exp(-q * T)

        if product.option_type == "Call":
            value = S * df_q * nd1 - K * df_r * nd2
        else:
            value = K * df_r * float(norm.cdf(-d2)) - S * df_q * float(norm.cdf(-d1))

        intrinsic = product.intrinsic_value()
        time_value = value - intrinsic

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="black_scholes.european_option",
        )
        result.add_step(
            CalculationStep(
                label="d1",
                symbol="d_1",
                value=d1,
                formula=(
                    r"d_1 = \frac{\ln(S/K) + (r - q + \sigma^2/2)T}"
                    r"{\sigma\sqrt{T}}"
                ),
                inputs={"S": S, "K": K, "r": r, "q": q, "sigma": sigma, "T": T},
                note="Standardized moneyness adjusted for drift and volatility.",
            )
        )
        result.add_step(
            CalculationStep(
                label="d2",
                symbol="d_2",
                value=d2,
                formula=r"d_2 = d_1 - \sigma\sqrt{T}",
                inputs={"d1": d1},
            )
        )
        result.add_step(
            CalculationStep(
                label="N(d1)",
                symbol="N(d_1)",
                value=nd1,
                note="Under BS, also the call's delta before the dividend discount.",
            )
        )
        result.add_step(
            CalculationStep(
                label="N(d2)",
                symbol="N(d_2)",
                value=nd2,
                note="Risk-neutral probability the option finishes in the money.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Discount factor (rate)",
                symbol="e^{-rT}",
                value=df_r,
                inputs={"r": r, "T": T},
                note=f"Risk-free rate source: {r_src}.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Discount factor (dividends)",
                symbol="e^{-qT}",
                value=df_q,
                inputs={"q": q, "T": T},
                note=f"Dividend yield source: {q_src}.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"{product.option_type} value",
                symbol="V",
                value=value,
                formula=(
                    r"C = S e^{-qT} N(d_1) - K e^{-rT} N(d_2)"
                    if product.option_type == "Call"
                    else r"P = K e^{-rT} N(-d_2) - S e^{-qT} N(-d_1)"
                ),
            )
        )
        result.add_step(
            CalculationStep(
                label="Intrinsic value",
                symbol="V_{int}",
                value=intrinsic,
                formula=r"\max(S-K,0) \text{ or } \max(K-S,0)",
                note="Value if exercised immediately.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Time value",
                symbol="V_{time}",
                value=time_value,
                formula=r"V_{time} = V - V_{int}",
                note="The premium for optionality before expiry.",
            )
        )

        result.outputs = {
            "fair_value": value,
            "intrinsic_value": intrinsic,
            "time_value": time_value,
            "d1": d1,
            "d2": d2,
            "n_d1": nd1,
            "n_d2": nd2,
            "risk_free_rate_used": r,
            "dividend_yield_used": q,
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
