"""Merton Jump Diffusion (1976) and SABR (2002) for European options.

Two different answers to the same complaint about Black–Scholes:

* **Merton** adds Poisson jumps to the price path itself — crashes as
  events, not just diffusion. The price is an elegant series: a
  probability-weighted sum of Black–Scholes prices, one per jump count.
  With jump intensity λ = 0 it IS Black–Scholes (the tests enforce this
  exactly), and with downward-biased jumps it fattens the left tail — OTM
  puts get more expensive, which is the smile's origin story.

* **SABR** models the *forward* with stochastic lognormal volatility and
  answers in the market's own language: Hagan's asymptotic formula maps
  strike to implied volatility, which is then fed through Black–Scholes.
  It is the industry's standard smile interpolator. With vol-of-vol ν = 0
  (and β = 1) the smile flattens to α and SABR collapses to Black–Scholes.
"""

from __future__ import annotations

import math
import time

from scipy.stats import norm

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.products.european_option import EuropeanOption


def _bs_price(
    kind: str, s: float, k: float, t: float, sigma: float, r: float, q: float
) -> float:
    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma**2) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    if kind == "Call":
        return s * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    return k * math.exp(-r * t) * norm.cdf(-d2) - s * math.exp(-q * t) * norm.cdf(-d1)


def _rates(product: EuropeanOption, market: MarketData) -> tuple[float, float]:
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
    return r, q


# --------------------------------------------------------------------------- #


@register_model
class MertonJumpDiffusion(PricingModel):
    model_id = "merton_jump_diffusion"
    display_name = "Merton Jump Diffusion"

    # Classroom calibration — overridable in tests.
    LAMBDA = 0.10  # jumps per year
    MU_J = -0.10  # mean log-jump (negative: crashes, not rallies)
    SIGMA_J = 0.15  # log-jump dispersion
    _N_TERMS = 40

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, EuropeanOption)

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, EuropeanOption)
        t0 = time.perf_counter()
        S, K = product.spot, product.strike
        T, sigma = product.time_to_expiry, product.volatility
        r, q = _rates(product, market)

        lam, mu_j, s_j = self.LAMBDA, self.MU_J, self.SIGMA_J
        k_bar = math.exp(mu_j + 0.5 * s_j * s_j) - 1.0  # expected jump size
        lam_p = lam * (1.0 + k_bar)

        value = 0.0
        weight_used = 0.0
        for n in range(self._N_TERMS):
            w = math.exp(-lam_p * T) * (lam_p * T) ** n / math.factorial(n)
            if w < 1e-14 and n > 2:
                break
            sigma_n = math.sqrt(sigma * sigma + n * s_j * s_j / T)
            r_n = r - lam * k_bar + n * math.log(1.0 + k_bar) / T
            value += w * _bs_price(product.option_type, S, K, T, sigma_n, r_n, q)
            weight_used += w

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="merton_jump_diffusion.european_option",
        )
        result.add_step(
            CalculationStep(
                label="Jump calibration",
                symbol=r"\lambda,\ \mu_J,\ \sigma_J",
                value=lam,
                note=f"{lam:.2f} jumps/yr, mean log-jump {mu_j:+.2f} "
                f"(downward - crashes), dispersion {s_j:.2f}. Expected jump "
                f"size k = {k_bar:+.3f} (fixed classroom values).",
            )
        )
        result.add_step(
            CalculationStep(
                label="Series of conditional BS prices",
                symbol="V",
                value=value,
                formula=(
                    r"V = \sum_{n\ge 0} \frac{e^{-\lambda' T}(\lambda' T)^n}{n!}"
                    r"\, BS(\sigma_n, r_n)"
                ),
                note="Condition on n jumps having happened: the world is "
                "Black-Scholes with variance and drift adjusted for those "
                "jumps; weight by the Poisson probability of n.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Poisson weight captured",
                symbol=r"\sum w_n",
                value=weight_used,
                note="Effectively 1 - the truncated tail is negligible.",
            )
        )
        result.outputs = {
            "fair_value": value,
            "jump_intensity": lam,
            "mean_log_jump": mu_j,
            "jump_dispersion": s_j,
            "expected_jump_size": k_bar,
            "intrinsic_value": product.intrinsic_value(),
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result


# --------------------------------------------------------------------------- #


@register_model
class SABR(PricingModel):
    model_id = "sabr"
    display_name = "SABR (Hagan)"

    # Classroom calibration, beta = 1 (lognormal backbone) — overridable.
    BETA = 1.0
    RHO = -0.30  # forward/vol correlation: negative tilts vols to low strikes
    NU = 0.60  # vol-of-vol: bends the smile

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, EuropeanOption)

    def implied_vol(
        self, forward: float, strike: float, T: float, alpha: float
    ) -> float:
        """Hagan's beta = 1 asymptotic implied volatility."""
        rho, nu = self.RHO, self.NU
        correction = (
            1.0 + (0.25 * rho * nu * alpha + (2 - 3 * rho * rho) * nu * nu / 24.0) * T
        )
        if abs(math.log(forward / strike)) < 1e-12 or nu < 1e-12:
            return alpha * correction
        z = (nu / alpha) * math.log(forward / strike)
        x = math.log((math.sqrt(1 - 2 * rho * z + z * z) + z - rho) / (1 - rho))
        return alpha * (z / x) * correction

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, EuropeanOption)
        t0 = time.perf_counter()
        S, K = product.spot, product.strike
        T = product.time_to_expiry
        alpha = product.volatility  # user's vol anchors the ATM level
        r, q = _rates(product, market)

        forward = S * math.exp((r - q) * T)
        vol = self.implied_vol(forward, K, T, alpha)
        value = _bs_price(product.option_type, S, K, T, vol, r, q)

        atm_vol = self.implied_vol(forward, forward, T, alpha)

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=product.product_id,
            model_id=self.model_id,
            explanation_key="sabr.european_option",
        )
        result.add_step(
            CalculationStep(
                label="Forward",
                symbol="F",
                value=forward,
                formula=r"F = S e^{(r-q)T}",
                note="SABR lives on the forward, not the spot.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Smile-consistent implied vol at this strike",
                symbol=r"\sigma_{SABR}(K)",
                value=vol,
                formula=r"\sigma(K) = \alpha \frac{z}{x(z)}\big[1 + c\,T\big]",
                note=f"alpha = {alpha:.1%} (your input), rho = {self.RHO}, "
                f"nu = {self.NU}, beta = {self.BETA}. ATM level: {atm_vol:.2%}. "
                "Negative rho raises vols below the forward - the equity skew.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Price via Black-Scholes at the SABR vol",
                symbol="V",
                value=value,
                note="SABR answers in the market's own language: a vol per "
                "strike, then the standard formula.",
            )
        )
        result.outputs = {
            "fair_value": value,
            "sabr_implied_vol": vol,
            "atm_implied_vol": atm_vol,
            "forward": forward,
            "rho": self.RHO,
            "nu_vol_of_vol": self.NU,
            "beta": self.BETA,
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result
