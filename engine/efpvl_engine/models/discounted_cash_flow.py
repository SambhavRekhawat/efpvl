"""Discounted Cash Flow model for bonds.

Values each cash flow with a discount factor from the zero curve, then sums.
Outputs the full bond vocabulary: dirty price, accrued interest, clean price,
and the yield to maturity implied by the curve-based price (solved with
Brent's method, compounded at the coupon frequency).

Every discount factor and every cash-flow PV lands in the calculation trace.
"""

from __future__ import annotations

import time

from scipy.optimize import brentq

from efpvl_engine.core.base import MarketData, PricingModel, Product, register_model
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.market.curve import ZeroCurve
from efpvl_engine.market.daycount import year_fraction
from efpvl_engine.market.market_snapshot import MarketSnapshot
from efpvl_engine.products.coupon_bond import CouponBond
from efpvl_engine.products.currency_and_inflation import (
    CurrencySwap,
    InflationLinkedBond,
)
from efpvl_engine.products.forward_rate_agreement import ForwardRateAgreement
from efpvl_engine.products.rates_swaps import FloatingRateNote, InterestRateSwap
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond

_RATES_PRODUCTS = (
    ZeroCouponBond,
    CouponBond,
    ForwardRateAgreement,
    InterestRateSwap,
    FloatingRateNote,
    CurrencySwap,
    InflationLinkedBond,
)


@register_model
class DiscountedCashFlow(PricingModel):
    model_id = "discounted_cash_flow"
    display_name = "Discounted Cash Flow"

    @classmethod
    def supports(cls, product: Product) -> bool:
        return isinstance(product, _RATES_PRODUCTS)

    def risk_measures(self, product: Product, market: MarketData) -> dict[str, float]:
        """Yield-based bond risk: durations, convexity, DV01.

        Computed at the bond's curve-implied YTM (compounded at the coupon
        frequency; annually for zeros), so measures are consistent with the
        DCF price.
        """
        if isinstance(
            product,
            (ForwardRateAgreement, InterestRateSwap, FloatingRateNote, CurrencySwap),
        ):
            return self._swap_style_risk(product, market)
        if isinstance(product, InflationLinkedBond):
            return self._linker_risk(product, market)
        if isinstance(product, ZeroCouponBond):
            flows = [(product.time_to_maturity(), product.face_value)]
            m = 1
        elif isinstance(product, CouponBond):
            times = product.year_fractions()
            amounts = [amt for _, amt, _ in product.cashflows()]
            # cashflows(): coupons then redemption at the final coupon time
            flows = list(zip(times, amounts[:-1], strict=True))
            flows.append((times[-1], amounts[-1]))
            m = product.frequency
        else:  # pragma: no cover
            raise NotImplementedError

        dirty = sum(cf * market.discount_factor(t) for t, cf in flows)
        y = self._solve_ytm_generic(flows, m, dirty)

        def disc(t: float) -> float:
            return (1 + y / m) ** (-m * t)

        pv_weighted_t = sum(t * cf * disc(t) for t, cf in flows)
        macaulay = pv_weighted_t / dirty
        modified = macaulay / (1 + y / m)
        convexity = (
            sum(cf * t * (t + 1 / m) * disc(t) for t, cf in flows)
            / ((1 + y / m) ** 2)
            / dirty
        )
        dv01 = modified * dirty * 1e-4

        return {
            "yield_to_maturity": y,
            "macaulay_duration": macaulay,
            "modified_duration": modified,
            "convexity": convexity,
            "dv01": dv01,
        }

    @staticmethod
    def _solve_ytm_generic(
        flows: list[tuple[float, float]], m: int, target: float
    ) -> float:
        def f(y: float) -> float:
            return sum(cf * (1 + y / m) ** (-m * t) for t, cf in flows) - target

        return float(brentq(f, -0.5, 2.0, xtol=1e-12, maxiter=200))

    # -- Forward Rate Agreement ------------------------------------------ #

    def _price_fra(
        self, fra: ForwardRateAgreement, market: MarketData
    ) -> ValuationResult:
        t1, t2, tau = fra.times()
        df1, df2 = market.discount_factor(t1), market.discount_factor(t2)
        fwd = (df1 / df2 - 1.0) / tau
        sign = 1.0 if fra.position == "Pay fixed" else -1.0
        value = sign * fra.notional * tau * (fwd - fra.fixed_rate) * df2

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=fra.product_id,
            model_id=self.model_id,
            explanation_key="dcf.forward_rate_agreement",
        )
        result.add_step(
            CalculationStep(
                label="Discount factor to period start",
                symbol="DF(T_1)",
                value=df1,
                inputs={"t1": t1},
            )
        )
        result.add_step(
            CalculationStep(
                label="Discount factor to period end",
                symbol="DF(T_2)",
                value=df2,
                inputs={"t2": t2},
            )
        )
        result.add_step(
            CalculationStep(
                label="Curve-implied forward rate",
                symbol="f",
                value=fwd,
                formula=r"f = \frac{DF(T_1)/DF(T_2) - 1}{\tau}",
                inputs={"tau": tau},
                note="The rate the curve already predicts for [T1, T2] — "
                "locking any other rate creates the value below.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"FRA value ({fra.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm N \tau (f - K) \, DF(T_2)",
                inputs={"K": fra.fixed_rate, "notional": fra.notional},
            )
        )
        result.outputs = {
            "forward_rate": fwd,
            "fixed_rate": fra.fixed_rate,
            "accrual_fraction": tau,
            "discount_factor_end": df2,
        }
        return result

    # -- Interest Rate Swap ------------------------------------------------ #

    def _swap_legs(
        self, swap: InterestRateSwap, market: MarketData
    ) -> tuple[float, float, float, list[CalculationStep]]:
        """(fixed_pv, float_pv, annuity, per-period steps)."""
        steps: list[CalculationStep] = []
        fixed_pv = float_pv = annuity = 0.0
        for start, end, tau in swap.periods():
            t_start = year_fraction(swap.settlement_date, start, swap.day_count)
            t_end = year_fraction(swap.settlement_date, end, swap.day_count)
            df_s = market.discount_factor(max(t_start, 0.0))
            df_e = market.discount_factor(t_end)
            fwd = (df_s / df_e - 1.0) / tau
            fixed_pv += swap.notional * swap.fixed_rate * tau * df_e
            float_pv += swap.notional * fwd * tau * df_e
            annuity += tau * df_e
            steps.append(
                CalculationStep(
                    label=f"Period to {end.isoformat()}",
                    symbol="f_i",
                    value=fwd,
                    inputs={"tau": tau, "DF_end": df_e},
                    note=f"Float cash {swap.notional * fwd * tau:,.2f} · "
                    f"fixed cash {swap.notional * swap.fixed_rate * tau:,.2f}",
                )
            )
        return fixed_pv, float_pv, annuity, steps

    def _price_swap(
        self, swap: InterestRateSwap, market: MarketData
    ) -> ValuationResult:
        fixed_pv, float_pv, annuity, period_steps = self._swap_legs(swap, market)
        t_end = year_fraction(swap.settlement_date, swap.maturity_date, swap.day_count)
        df_n = market.discount_factor(t_end)
        telescoped = swap.notional * (1.0 - df_n)
        par_rate = (1.0 - df_n) / annuity if annuity > 0 else float("nan")
        sign = 1.0 if swap.position == "Pay fixed" else -1.0
        value = sign * (float_pv - fixed_pv)

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=swap.product_id,
            model_id=self.model_id,
            explanation_key="dcf.interest_rate_swap",
        )
        result.steps.extend(period_steps)
        result.add_step(
            CalculationStep(
                label="Fixed leg PV",
                symbol="PV_{fix}",
                value=fixed_pv,
                formula=r"PV_{fix} = N K \sum_i \tau_i DF(t_i)",
            )
        )
        result.add_step(
            CalculationStep(
                label="Floating leg PV",
                symbol="PV_{flt}",
                value=float_pv,
                formula=r"PV_{flt} = N \sum_i f_i \tau_i DF(t_i) = N(1 - DF(T))",
                note=f"Telescoping check: N(1 − DF(T)) = {telescoped:,.2f} — "
                "the floating leg only depends on the final discount factor.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Par swap rate",
                symbol="s_{par}",
                value=par_rate,
                formula=r"s_{par} = \frac{1 - DF(T)}{\sum_i \tau_i DF(t_i)}",
                note="The fixed rate that would make this swap worth zero today.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"Swap value ({swap.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm (PV_{flt} - PV_{fix})",
            )
        )
        result.outputs = {
            "fixed_leg_pv": fixed_pv,
            "floating_leg_pv": float_pv,
            "par_rate": par_rate,
            "annuity": annuity,
            "num_periods": float(len(period_steps)),
        }
        return result

    # -- Floating Rate Note ----------------------------------------------- #

    def _price_frn(self, frn: FloatingRateNote, market: MarketData) -> ValuationResult:
        result = ValuationResult(
            fair_value=0.0,
            currency="USD",
            product_id=frn.product_id,
            model_id=self.model_id,
            explanation_key="dcf.floating_rate_note",
        )
        pv = 0.0
        for start, end, tau in frn.periods():
            t_start = year_fraction(frn.settlement_date, start, frn.day_count)
            t_end = year_fraction(frn.settlement_date, end, frn.day_count)
            df_s = market.discount_factor(max(t_start, 0.0))
            df_e = market.discount_factor(t_end)
            fwd = (df_s / df_e - 1.0) / tau
            coupon = frn.notional * (fwd + frn.spread) * tau
            pv += coupon * df_e
            result.add_step(
                CalculationStep(
                    label=f"Coupon {end.isoformat()}",
                    symbol="c_i",
                    value=coupon * df_e,
                    inputs={"forward": fwd, "spread": frn.spread, "DF": df_e},
                )
            )
        t_n = year_fraction(frn.settlement_date, frn.maturity_date, frn.day_count)
        df_n = market.discount_factor(t_n)
        pv += frn.notional * df_n
        result.add_step(
            CalculationStep(
                label="Notional redemption",
                symbol=r"N \cdot DF(T)",
                value=frn.notional * df_n,
            )
        )
        result.add_step(
            CalculationStep(
                label="FRN value",
                symbol="PV",
                value=pv,
                formula=r"PV = \sum_i N(f_i + s)\tau_i DF(t_i) + N \, DF(T)",
                note="With zero spread this collapses to exactly N: a floater "
                "at reset is worth par.",
            )
        )
        result.fair_value = pv
        result.outputs = {
            "present_value": pv,
            "price_pct_of_par": 100.0 * pv / frn.notional,
            "spread_bps": frn.spread_bps,
        }
        return result

    # -- Currency Swap ----------------------------------------------------- #

    def _price_ccy_swap(self, cs: CurrencySwap, market: MarketData) -> ValuationResult:
        import math as _math

        n_d, n_f = cs.notional_domestic, cs.notional_foreign
        pv_dom = pv_for = 0.0
        for _start, end, tau in cs.periods():
            t = year_fraction(cs.settlement_date, end, cs.day_count)
            pv_dom += n_d * cs.domestic_rate_leg * tau * market.discount_factor(t)
            pv_for += (
                n_f
                * cs.foreign_rate_leg
                * tau
                * _math.exp(-cs.foreign_discount_rate * t)
            )
        t_n = year_fraction(cs.settlement_date, cs.maturity_date, cs.day_count)
        pv_dom += n_d * market.discount_factor(t_n)
        pv_for += n_f * _math.exp(-cs.foreign_discount_rate * t_n)

        pv_for_in_dom = pv_for * cs.spot_fx
        sign = 1.0 if cs.position == "Receive foreign" else -1.0
        value = sign * (pv_for_in_dom - pv_dom)

        result = ValuationResult(
            fair_value=value,
            currency="USD",
            product_id=cs.product_id,
            model_id=self.model_id,
            explanation_key="dcf.currency_swap",
        )
        result.add_step(
            CalculationStep(
                label="Domestic leg PV",
                symbol="PV_d",
                value=pv_dom,
                formula=r"PV_d = N_d\big[c_d \sum_i \tau_i DF(t_i) + DF(T)\big]",
                note="A domestic fixed bond: coupons plus the final notional "
                "exchange, on the zero curve.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Foreign leg PV (foreign ccy)",
                symbol="PV_f",
                value=pv_for,
                formula=(
                    r"PV_f = N_f\big[c_f \sum_i \tau_i e^{-r_f t_i}"
                    r" + e^{-r_f T}\big]"
                ),
                inputs={"N_f": n_f},
            )
        )
        result.add_step(
            CalculationStep(
                label="Foreign leg PV (domestic ccy)",
                symbol=r"S \cdot PV_f",
                value=pv_for_in_dom,
                inputs={"spot_fx": cs.spot_fx},
                note="Converted at today's spot. Initial notional exchanges "
                "cancel at inception since N_d = S · N_f.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"Swap value ({cs.position})",
                symbol="V",
                value=value,
                formula=r"V = \pm (S \cdot PV_f - PV_d)",
            )
        )
        result.outputs = {
            "domestic_leg_pv": pv_dom,
            "foreign_leg_pv_foreign_ccy": pv_for,
            "foreign_leg_pv_domestic_ccy": pv_for_in_dom,
            "notional_foreign": n_f,
        }
        return result

    # -- Inflation-Linked Bond --------------------------------------------- #

    def _price_linker(
        self, bond: InflationLinkedBond, market: MarketData
    ) -> ValuationResult:
        result = ValuationResult(
            fair_value=0.0,
            currency="USD",
            product_id=bond.product_id,
            model_id=self.model_id,
            explanation_key="dcf.inflation_linked_bond",
        )
        pi = bond.breakeven_inflation
        m = bond.frequency
        pv = 0.0
        index_T = 1.0
        for _start, end, _tau in bond.periods():
            t = year_fraction(bond.settlement_date, end, bond.day_count)
            index_ratio = (1.0 + pi) ** t
            cash = bond.face_value * (bond.real_coupon_rate / m) * index_ratio
            df = market.discount_factor(t)
            pv += cash * df
            index_T = index_ratio
            result.add_step(
                CalculationStep(
                    label=f"Indexed coupon {end.isoformat()}",
                    symbol="c_i",
                    value=cash * df,
                    inputs={"index_ratio": index_ratio, "DF": df},
                )
            )
        t_n = year_fraction(bond.settlement_date, bond.maturity_date, bond.day_count)
        principal = bond.face_value * (1.0 + pi) ** t_n
        pv += principal * market.discount_factor(t_n)
        result.add_step(
            CalculationStep(
                label="Inflation-adjusted principal",
                symbol=r"F (1+\pi)^T",
                value=principal,
                formula=r"F_T = F (1 + \pi)^T",
                note=f"Principal grown at breakeven inflation π = {pi:.2%}. "
                "At π = 0 this bond collapses to the plain nominal bond.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Present value",
                symbol="PV",
                value=pv,
                formula=r"PV = \sum_i \tfrac{c}{m} F (1+\pi)^{t_i} DF(t_i)"
                r" + F(1+\pi)^{T} DF(T)",
            )
        )
        result.fair_value = pv
        result.outputs = {
            "present_value": pv,
            "indexed_principal_at_maturity": principal,
            "final_index_ratio": index_T,
            "breakeven_inflation": pi,
        }
        return result

    # -- Curve-bump risk for linear rates products ------------------------- #

    @staticmethod
    def _parallel_bumped(market: MarketData, h: float) -> MarketData:
        """A copy of the market with every zero rate shifted by h."""
        if not isinstance(market, MarketSnapshot):  # pragma: no cover
            raise NotImplementedError("bump requires a MarketSnapshot")
        bumped = MarketSnapshot(snapshot=market.snapshot, overrides=market.overrides)
        bumped.curve = ZeroCurve(
            market.curve.tenors,
            [r + h for r in market.curve.rates],
            currency=market.curve.currency,
            name=f"{market.curve.name}+{h:+.6f}",
        )
        return bumped

    def _swap_style_risk(
        self, product: Product, market: MarketData
    ) -> dict[str, float]:
        h = 1e-4
        v0 = self.price(product, market).fair_value
        v_up = self.price(product, self._parallel_bumped(market, h)).fair_value
        v_dn = self.price(product, self._parallel_bumped(market, -h)).fair_value
        dv01 = (v_up - v_dn) / 2.0  # signed currency change per +1bp
        out = {"dv01": dv01, "npv": v0}
        if isinstance(product, InterestRateSwap):
            _, _, annuity, _ = self._swap_legs(product, market)
            out["pv01"] = product.notional * annuity * 1e-4
            out["par_rate"] = self.price(product, market).outputs["par_rate"]
        if isinstance(product, CurrencySwap):
            # Seasoned swap: the foreign notional is FIXED at inception, so
            # dV/dS is exactly the foreign leg's PV in foreign currency
            # (converted value is linear in spot), signed by position.
            outputs = self.price(product, market).outputs
            sign = 1.0 if product.position == "Receive foreign" else -1.0
            out["fx_delta"] = sign * outputs["foreign_leg_pv_foreign_ccy"]
        return out

    def _linker_risk(
        self, bond: InflationLinkedBond, market: MarketData
    ) -> dict[str, float]:
        v0 = self.price(bond, market).fair_value
        bump = 1e-4
        up = InflationLinkedBond(
            bond.face_value,
            bond.real_coupon_rate,
            bond.breakeven_inflation + bump,
            bond.frequency,
            bond.settlement_date,
            bond.maturity_date,
            bond.day_count,
        )
        inflation01 = self.price(up, market).fair_value - v0
        v_up = self.price(bond, self._parallel_bumped(market, 1e-4)).fair_value
        v_dn = self.price(bond, self._parallel_bumped(market, -1e-4)).fair_value
        return {
            "inflation01": inflation01,
            "dv01": (v_up - v_dn) / 2.0,
            "npv": v0,
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
                "Values an instrument as the sum of its cash flows, each "
                "discounted with a factor read off the zero curve. The "
                "reference method for deterministic cash-flow products."
            ),
            "assumptions": [
                "Cash flows are known with certainty (no default, no optionality).",
                "The zero curve fully describes the time value of money.",
                "Interpolation between curve pillars is log-linear in DF.",
            ],
            "limitations": [
                "Cannot value contingent cash flows (options, callables).",
                "Ignores credit risk unless spreads are added to the curve.",
                "Result is only as good as the input curve.",
            ],
            "typical_usage": "Bonds, swaps legs, any fixed cash-flow schedule.",
            "computational_complexity": "O(n) in the number of cash flows.",
        }

    def price(self, product: Product, market: MarketData) -> ValuationResult:
        t0 = time.perf_counter()
        if isinstance(product, ZeroCouponBond):
            result = self._price_zero(product, market)
        elif isinstance(product, CouponBond):
            result = self._price_coupon(product, market)
        elif isinstance(product, ForwardRateAgreement):
            result = self._price_fra(product, market)
        elif isinstance(product, InterestRateSwap):
            result = self._price_swap(product, market)
        elif isinstance(product, FloatingRateNote):
            result = self._price_frn(product, market)
        elif isinstance(product, CurrencySwap):
            result = self._price_ccy_swap(product, market)
        elif isinstance(product, InflationLinkedBond):
            result = self._price_linker(product, market)
        else:  # pragma: no cover - guarded by supports()
            raise TypeError("DCF cannot price this product")
        result.runtime_ms = (time.perf_counter() - t0) * 1000.0
        return result

    # -- Zero coupon ---------------------------------------------------- #

    def _price_zero(self, bond: ZeroCouponBond, market: MarketData) -> ValuationResult:
        t = bond.time_to_maturity()
        df = market.discount_factor(t)
        pv = bond.face_value * df

        result = ValuationResult(
            fair_value=pv,
            currency="USD",
            product_id=bond.product_id,
            model_id=self.model_id,
            explanation_key="dcf.zero_coupon_bond",
        )
        result.add_step(
            CalculationStep(
                label="Time to maturity",
                symbol="T",
                value=t,
                formula=r"T = \mathrm{yearfrac}(t_{settle}, t_{mat})",
                inputs={},
                note=f"Computed under {bond.day_count.value}.",
            )
        )
        result.add_step(
            CalculationStep(
                label=f"Discount factor DF({t:.4f}y)",
                symbol="DF(T)",
                value=df,
                formula=r"DF(T) = e^{-z(T)\,T}",
                inputs={"T": t},
                note="Read off the zero curve; the price of $1 paid at maturity.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Present value",
                symbol="PV",
                value=pv,
                formula=r"PV = F \cdot DF(T)",
                inputs={"face_value": bond.face_value, "DF": df},
            )
        )
        result.outputs = {
            "present_value": pv,
            "discount_factor": df,
            "time_to_maturity": t,
            "zero_rate": market.curve.zero_rate(t)
            if hasattr(market, "curve")
            else float("nan"),
        }
        return result

    # -- Coupon bond ----------------------------------------------------- #

    def _price_coupon(self, bond: CouponBond, market: MarketData) -> ValuationResult:
        result = ValuationResult(
            fair_value=0.0,
            currency="USD",
            product_id=bond.product_id,
            model_id=self.model_id,
            explanation_key="dcf.coupon_bond",
        )

        dirty = 0.0
        for pay_date, amount, kind in bond.cashflows():
            t = year_fraction(bond.settlement_date, pay_date, bond.day_count)
            df = market.discount_factor(t)
            pv = amount * df
            dirty += pv
            result.add_step(
                CalculationStep(
                    label=f"{kind.title()} {pay_date.isoformat()}",
                    symbol="PV_i",
                    value=pv,
                    formula=r"PV_i = CF_i \cdot DF(t_i)",
                    inputs={"cash_flow": amount, "t": t, "DF": df},
                )
            )

        accrued = bond.accrued_interest()
        clean = dirty - accrued
        ytm = self._solve_ytm(bond, dirty)

        result.add_step(
            CalculationStep(
                label="Dirty price (sum of PVs)",
                symbol="P_{dirty}",
                value=dirty,
                formula=r"P_{dirty} = \sum_i CF_i \cdot DF(t_i)",
                note="What the buyer actually pays: full discounted value.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Accrued interest",
                symbol="AI",
                value=accrued,
                formula=r"AI = c \cdot \frac{\tau_{elapsed}}{\tau_{period}}",
                note="Coupon earned by the seller since the last coupon date.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Clean price",
                symbol="P_{clean}",
                value=clean,
                formula=r"P_{clean} = P_{dirty} - AI",
                note="The quoted price on screens; excludes accrued interest.",
            )
        )
        result.add_step(
            CalculationStep(
                label="Yield to maturity",
                symbol="y",
                value=ytm,
                formula=r"P_{dirty} = \sum_i \frac{CF_i}{(1 + y/m)^{m\,t_i}}",
                note=(
                    "The single rate, compounded at the coupon frequency, that "
                    "reprices the bond exactly. Solved numerically (Brent)."
                ),
            )
        )

        result.fair_value = dirty
        result.outputs = {
            "dirty_price": dirty,
            "clean_price": clean,
            "accrued_interest": accrued,
            "yield_to_maturity": ytm,
            "coupon_amount": bond.coupon_amount(),
            "num_cashflows": float(len(bond.cashflows())),
        }
        return result

    @staticmethod
    def _solve_ytm(bond: CouponBond, target_dirty: float) -> float:
        """Yield (compounded m times/year) matching the dirty price."""
        m = bond.frequency
        times = bond.year_fractions()
        flows = [amt for _, amt, _ in bond.cashflows()]
        # cashflows() lists coupons then redemption; align redemption time:
        times = times + [times[-1]]  # redemption shares the last coupon date

        def pv_at(y: float) -> float:
            return sum(
                cf / (1 + y / m) ** (m * t) for cf, t in zip(flows, times, strict=True)
            )

        f = lambda y: pv_at(y) - target_dirty  # noqa: E731
        try:
            return float(brentq(f, -0.5, 2.0, xtol=1e-12, maxiter=200))
        except ValueError:
            return float("nan")
