"""Heston stochastic volatility model (1993) for European options.

Variance is itself a mean-reverting random process, correlated with the
stock — which is exactly the ingredient the smile demands: negative
correlation makes crashes and volatility spikes arrive together, fattening
the left tail and tilting implied vols against low strikes.

Pricing uses the semi-closed form: two probabilities P₁, P₂ obtained by
integrating the characteristic function (the "little Heston trap"
formulation of Albrecher et al., numerically stable for long maturities).

Calibration in this laboratory (documented, exposed in outputs): the user's
volatility input sets today's variance v₀ = σ² and its long-run level θ;
mean-reversion κ, vol-of-vol ξ, and correlation ρ are fixed classroom
values chosen to produce a realistic equity skew. As ξ → 0 the model
collapses to Black–Scholes — a convergence the test suite enforces.
"""

from __future__ import annotations

import math
import time

import numpy as np

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.european_option import EuropeanOption


@register_model
class Heston(PricingModel):
    model_id = "heston"
    display_name = "Heston Stochastic Volatility"

    # Classroom calibration — class attributes so tests can override.
    KAPPA = 1.5  # mean-reversion speed of variance
    XI = 0.5  # vol-of-vol
    RHO = -0.7  # spot/variance correlation (negative = equity skew)

    _U_MAX = 200.0
    _N_POINTS = 4000

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, EuropeanOption)

    # ------------------------------------------------------------------ #

    def _probability(
        self,
        j: int,
        S: float,
        K: float,
        T: float,
        r: float,
        q: float,
        v0: float,
        theta: float,
    ) -> float:
        """P_j = Pr(S_T > K) under the two Heston measures (j = 1, 2)."""
        kappa, xi, rho = self.KAPPA, self.XI, self.RHO
        u_j = 0.5 if j == 1 else -0.5
        b_j = kappa - rho * xi if j == 1 else kappa

        u = np.linspace(1e-8, self._U_MAX, self._N_POINTS)
        iu = 1j * u

        d = np.sqrt((rho * xi * iu - b_j) ** 2 - xi * xi * (2 * u_j * iu - u * u))
        g = (b_j - rho * xi * iu - d) / (b_j - rho * xi * iu + d)
        exp_dt = np.exp(-d * T)

        c_term = (r - q) * iu * T + (kappa * theta / (xi * xi)) * (
            (b_j - rho * xi * iu - d) * T - 2.0 * np.log((1.0 - g * exp_dt) / (1.0 - g))
        )
        d_term = (
            (b_j - rho * xi * iu - d) / (xi * xi) * (1.0 - exp_dt) / (1.0 - g * exp_dt)
        )
        f = np.exp(c_term + d_term * v0 + iu * math.log(S))

        integrand = np.real(np.exp(-iu * math.log(K)) * f / iu)
        return float(0.5 + np.trapezoid(integrand, u) / math.pi)

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, EuropeanOption)
        t0 = time.perf_counter()

        S, K = product.spot, product.strike
        T = product.time_to_expiry
        v0 = product.volatility**2  # user's vol sets today's variance ...
        theta = v0  # ... and its long-run level
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

        p1 = self._probability(1, S, K, T, r, q, v0, theta)
        p2 = self._probability(2, S, K, T, r, q, v0, theta)
        df_r, df_q = math.exp(-r * T), math.exp(-q * T)
        call = S * df_q * p1 - K * df_r * p2
        value = (
            call
            if product.option_type == "Call"
            else (
                call - S * df_q + K * df_r  # put-call parity
            )
        )

        feller = 2 * self.KAPPA * theta >= self.XI**2

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="heston.european_option",
        )
        result.add_step(
            CalculationStep(
                label="Initial and long-run variance",
                symbol="v_0 = \\theta",
                value=v0,
                formula=r"dv = \kappa(\theta - v)\,dt + \xi\sqrt{v}\,dW_v",
                note=f"Set from your volatility input ({product.volatility:.1%}). "
                f"kappa = {self.KAPPA}, xi = {self.XI}, rho = {self.RHO} "
                "(fixed classroom calibration).",
            )
        )
        result.add_step(
            CalculationStep(
                label="Exercise probability (stock measure)",
                symbol="P_1",
                value=p1,
                note="From integrating the characteristic function - the "
                "stochastic-vol analogue of N(d1).",
            )
        )
        result.add_step(
            CalculationStep(
                label="Exercise probability (money measure)",
                symbol="P_2",
                value=p2,
                note="The analogue of N(d2).",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"{product.option_type} value",
                symbol="V",
                value=value,
                formula=r"C = S e^{-qT} P_1 - K e^{-rT} P_2",
                note=None
                if product.option_type == "Call"
                else "Put obtained from the call via put-call parity.",
            )
        )
        result.outputs = {
            "fair_value": value,
            "p1": p1,
            "p2": p2,
            "v0": v0,
            "kappa": self.KAPPA,
            "xi_vol_of_vol": self.XI,
            "rho_correlation": self.RHO,
            "feller_condition_met": float(feller),
            "risk_free_rate_used": r,
            "dividend_yield_used": q,
        }
        if not feller:
            result.warnings.append(
                "Feller condition 2*kappa*theta >= xi^2 not met: variance can "
                "touch zero. Harmless for pricing here, but worth knowing."
            )
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
