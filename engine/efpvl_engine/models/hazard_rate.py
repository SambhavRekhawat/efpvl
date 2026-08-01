"""Reduced-form (hazard rate) model for Credit Default Swaps.

Default is modeled as the first jump of a Poisson process with constant
intensity λ, so survival to time t is Q(t) = e^{−λt}. λ is implied from the
market spread via the credit triangle λ ≈ s / (1 − R) — the single most
useful approximation in credit — and both CDS legs are then survival-weighted
expected values:

    premium leg    = s_contract · Σ τ_i · DF(t_i) · Q(t_i)      (risky annuity)
    protection leg = (1 − R) · Σ DF(t_i^mid) · [Q(t_{i−1}) − Q(t_i)]

Simplifications (standard for an educational pricer, noted in the trace):
flat hazard, no premium accrual-on-default, default settled mid-period.
"""

from __future__ import annotations

import math
import time

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.market.daycount import year_fraction
from efpvl_engine.products.credit_default_swap import CreditDefaultSwap


@register_model
class HazardRate(PricingModel):
    model_id = "hazard_rate"
    display_name = "Hazard Rate (Reduced Form)"

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, CreditDefaultSwap)

    # ------------------------------------------------------------------ #

    def _legs(
        self, cds: CreditDefaultSwap, market: MarketData, market_spread: float
    ) -> tuple[float, float, float, float]:
        """(risky_annuity, protection_pv, survival_T, lambda) per 1 notional."""
        lam = market_spread / (1.0 - cds.recovery_rate)
        annuity = protection = 0.0
        q_prev = 1.0
        t_prev = 0.0
        for _start, end, tau in cds.periods():
            t = year_fraction(cds.settlement_date, end, cds.day_count)
            q = math.exp(-lam * t)
            df = market.discount_factor(t)
            df_mid = market.discount_factor(0.5 * (t_prev + t))
            annuity += tau * df * q
            protection += (1.0 - cds.recovery_rate) * df_mid * (q_prev - q)
            q_prev, t_prev = q, t
        return annuity, protection, q_prev, lam

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        assert isinstance(product, CreditDefaultSwap)
        t0 = time.perf_counter()
        cds = product

        annuity, protection, q_T, lam = self._legs(cds, market, cds.market_spread)
        premium_pv = cds.contract_spread * annuity
        par_spread = protection / annuity if annuity > 0 else float("nan")
        sign = 1.0 if cds.position == "Buy protection" else -1.0
        value = sign * cds.notional * (protection - premium_pv)

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=cds.product_id,
            model_id=self.model_id,
            explanation_key="hazard_rate.credit_default_swap",
        )
        result.add_step(
            CalculationStep(
                label="Implied hazard rate",
                symbol=r"\lambda",
                value=lam,
                formula=r"\lambda \approx \frac{s_{mkt}}{1 - R}",
                inputs={"market_spread": cds.market_spread, "R": cds.recovery_rate},
                note="The credit triangle: default intensity implied by where "
                "the market prices this name's risk.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Survival to maturity",
                symbol="Q(T)",
                value=q_T,
                formula=r"Q(t) = e^{-\lambda t}",
                note=f"Implied probability of default by maturity: {1 - q_T:.2%}.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Risky annuity (per 1 notional)",
                symbol="A",
                value=annuity,
                formula=r"A = \sum_i \tau_i \, DF(t_i) \, Q(t_i)",
                note="Each premium is paid only if the name is still alive — "
                "survival weights make the annuity 'risky'.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Protection leg PV (per 1 notional)",
                symbol="P",
                value=protection,
                formula=r"P = (1-R)\sum_i DF(t^{mid}_i)\,[Q(t_{i-1}) - Q(t_i)]",
                note="Loss (1−R) paid at default, weighted by the probability "
                "default lands in each period; settled mid-period here.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Par CDS spread",
                symbol="s_{par}",
                value=par_spread,
                formula=r"s_{par} = P / A",
                note="The running spread that would make this contract free "
                "to enter today.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"CDS value ({cds.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm N (P - s_{contract} \cdot A)",
            )
        )
        result.outputs = {
            "par_spread_bps": par_spread * 10_000.0,
            "implied_hazard_rate": lam,
            "default_probability": 1.0 - q_T,
            "risky_annuity": annuity,
            "protection_leg_pv": cds.notional * protection,
            "premium_leg_pv": cds.notional * premium_pv,
        }
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result

    # ------------------------------------------------------------------ #

    def risk_measures(self, product: Product, market: MarketData) -> dict[str, float]:
        """CS01, recovery sensitivity, and the default-probability picture."""
        assert isinstance(product, CreditDefaultSwap)
        cds = product
        base = self.price(cds, market).fair_value

        # CS01: +1bp to the market spread, revalue.
        bumped = _clone_with(cds, market_spread_bps=cds.market_spread_bps + 1.0)
        cs01 = self.price(bumped, market).fair_value - base

        # Recovery01: +1 percentage point of recovery, revalue.
        r_up = min(cds.recovery_rate + 0.01, 0.99)
        bumped_r = _clone_with(cds, recovery_rate=r_up)
        recovery01 = self.price(bumped_r, market).fair_value - base

        _, _, q_T, lam = self._legs(cds, market, cds.market_spread)
        return {
            "cs01": cs01,
            "recovery01": recovery01,
            "default_probability": 1.0 - q_T,
            "implied_hazard_rate": lam,
            "npv": base,
        }


def _clone_with(cds: CreditDefaultSwap, **changes) -> CreditDefaultSwap:
    kwargs = dict(
        notional=cds.notional,
        contract_spread_bps=cds.contract_spread_bps,
        market_spread_bps=cds.market_spread_bps,
        recovery_rate=cds.recovery_rate,
        frequency=cds.frequency,
        settlement_date=cds.settlement_date,
        maturity_date=cds.maturity_date,
        position=cds.position,
        day_count=cds.day_count,
    )
    kwargs.update(changes)
    return CreditDefaultSwap(**kwargs)
