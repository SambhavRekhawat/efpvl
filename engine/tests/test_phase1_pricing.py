"""Phase 1 tests: market infrastructure + first three product families.

Two kinds of checks, both essential:

* **Golden values** — known answers from the literature (Hull's classic
  Black–Scholes example) and exact hand calculations.
* **Property tests** — identities that must hold for *any* inputs: a par
  bond prices to par, put–call parity, monotonicity, DF(0) = 1, and the
  house rule that every model emits a calculation trace.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from efpvl_engine import MarketSnapshot, ZeroCurve
from efpvl_engine.market.daycount import DayCount, add_months, year_fraction
from efpvl_engine.models.black_scholes import BlackScholes
from efpvl_engine.models.discounted_cash_flow import DiscountedCashFlow
from efpvl_engine.products.coupon_bond import CouponBond
from efpvl_engine.products.european_option import EuropeanOption
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond


def flat_market(rate: float) -> MarketSnapshot:
    """MarketSnapshot with a flat continuously compounded curve at ``rate``."""
    m = MarketSnapshot()
    m.curve = ZeroCurve.flat(rate)
    return m


# --------------------------------------------------------------------------- #
# Day counts                                                                   #
# --------------------------------------------------------------------------- #


def test_act_360_and_act_365():
    a, b = date(2026, 1, 1), date(2026, 7, 1)  # 181 actual days
    assert year_fraction(a, b, DayCount.ACT_360) == pytest.approx(181 / 360)
    assert year_fraction(a, b, DayCount.ACT_365) == pytest.approx(181 / 365)


def test_thirty_360_full_year_is_exactly_one():
    assert year_fraction(
        date(2026, 3, 15), date(2027, 3, 15), DayCount.THIRTY_360
    ) == pytest.approx(1.0)


def test_thirty_360_month_end_rule():
    # Jan 31 -> Feb 28 under 30/360 US: d1=31->30, days = 30*(1) + (28-30) = 28
    assert year_fraction(
        date(2026, 1, 31), date(2026, 2, 28), DayCount.THIRTY_360
    ) == pytest.approx(28 / 360)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 8, 31), -2) == date(2026, 6, 30)
    assert add_months(date(2026, 5, 15), 6) == date(2026, 11, 15)


# --------------------------------------------------------------------------- #
# Zero curve                                                                   #
# --------------------------------------------------------------------------- #


def test_df_at_zero_is_one_and_curve_reprices_pillars():
    curve = ZeroCurve([1, 2, 5], [0.03, 0.035, 0.04])
    assert curve.discount_factor(0.0) == 1.0
    for t, z in zip(curve.tenors, curve.rates, strict=True):
        assert curve.discount_factor(t) == pytest.approx(math.exp(-z * t), rel=1e-14)
        assert curve.zero_rate(t) == pytest.approx(z, rel=1e-12)


def test_discount_factors_decrease_with_time_for_positive_rates():
    curve = ZeroCurve.from_snapshot(__import__("efpvl_engine").load_snapshot())
    ts = [0.1 * k for k in range(1, 301)]
    dfs = [curve.discount_factor(t) for t in ts]
    assert all(d2 < d1 for d1, d2 in zip(dfs, dfs[1:], strict=False))


def test_forward_rate_recovers_flat_rate():
    curve = ZeroCurve.flat(0.05)
    assert curve.forward_rate(1.0, 2.0) == pytest.approx(0.05, rel=1e-12)


def test_invalid_curves_rejected():
    with pytest.raises(ValueError):
        ZeroCurve([2, 1], [0.03, 0.04])  # not increasing
    with pytest.raises(ValueError):
        ZeroCurve([0.0, 1.0], [0.03, 0.04])  # non-positive tenor
    with pytest.raises(ValueError):
        ZeroCurve([1.0], [0.03, 0.04])  # length mismatch


# --------------------------------------------------------------------------- #
# Zero Coupon Bond                                                             #
# --------------------------------------------------------------------------- #


def test_zcb_hand_calculation():
    """F=100, exactly 5y ACT/365 (with one leap day: 1826 days), flat 4%."""
    bond = ZeroCouponBond(
        face_value=100.0,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        day_count=DayCount.ACT_365,
    )
    t = (date(2031, 8, 3) - date(2026, 8, 3)).days / 365.0
    result = DiscountedCashFlow().price(bond, flat_market(0.04))
    assert result.fair_value == pytest.approx(100.0 * math.exp(-0.04 * t), rel=1e-12)
    assert len(result.steps) >= 3  # explainability contract


def test_zcb_price_below_par_for_positive_rates():
    bond = ZeroCouponBond(100.0, date(2026, 8, 3), date(2036, 8, 3))
    result = DiscountedCashFlow().price(bond, flat_market(0.03))
    assert 0 < result.fair_value < 100.0


# --------------------------------------------------------------------------- #
# Coupon Bond                                                                  #
# --------------------------------------------------------------------------- #


def _bond(coupon: float, years: int = 5, freq: int = 2) -> CouponBond:
    """Bond settling exactly on a coupon date (no accrued) under 30/360."""
    return CouponBond(
        face_value=100.0,
        coupon_rate=coupon,
        frequency=freq,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2026 + years, 8, 3),
        day_count=DayCount.THIRTY_360,
    )


def test_schedule_has_right_count_and_ends_at_maturity():
    bond = _bond(0.05, years=5, freq=2)
    dates = bond.coupon_dates()
    assert len(dates) == 10
    assert dates[-1] == bond.maturity_date
    assert dates[0] == date(2027, 2, 3)


def test_no_accrued_interest_on_a_coupon_date():
    assert _bond(0.05).accrued_interest() == pytest.approx(0.0, abs=1e-12)


def test_accrued_interest_hand_calculation():
    """Settle 3 months into a semiannual period: AI = half the coupon."""
    bond = CouponBond(
        face_value=100.0,
        coupon_rate=0.06,
        frequency=2,
        settlement_date=date(2026, 11, 3),  # prev coupon 2026-08-03, next 2027-02-03
        maturity_date=date(2031, 8, 3),
        day_count=DayCount.THIRTY_360,
    )
    # 30/360: elapsed 90/360, full period 180/360 -> AI = 3.00 * 0.5 = 1.50
    assert bond.accrued_interest() == pytest.approx(1.50, rel=1e-12)


def test_par_bond_prices_to_par():
    """The classic identity: coupon == yield (same compounding) => price = 100.

    Build a flat curve whose semiannually compounded yield is 5%: the
    continuous equivalent is r = 2 ln(1 + 0.05/2).
    """
    y, m = 0.05, 2
    r_cont = m * math.log(1 + y / m)
    bond = _bond(coupon=y, years=5, freq=m)
    result = DiscountedCashFlow().price(bond, flat_market(r_cont))
    assert result.outputs["clean_price"] == pytest.approx(100.0, abs=1e-8)
    assert result.outputs["yield_to_maturity"] == pytest.approx(y, abs=1e-9)


def test_premium_and_discount_bonds():
    y, m = 0.05, 2
    r_cont = m * math.log(1 + y / m)
    market = flat_market(r_cont)
    rich = DiscountedCashFlow().price(_bond(0.08), market)
    cheap = DiscountedCashFlow().price(_bond(0.02), market)
    assert rich.outputs["clean_price"] > 100.0  # coupon > yield: premium
    assert cheap.outputs["clean_price"] < 100.0  # coupon < yield: discount


def test_ytm_round_trip_on_snapshot_curve():
    """Price off the real snapshot curve, then verify the solved YTM reprices."""
    bond = _bond(0.05)
    result = DiscountedCashFlow().price(bond, MarketSnapshot())
    y = result.outputs["yield_to_maturity"]
    m = bond.frequency
    times = bond.year_fractions()
    flows = [amt for _, amt, _ in bond.cashflows()]
    times = times + [times[-1]]
    repriced = sum(
        cf / (1 + y / m) ** (m * t) for cf, t in zip(flows, times, strict=True)
    )
    assert repriced == pytest.approx(result.outputs["dirty_price"], rel=1e-10)


def test_bond_price_decreases_as_rates_rise():
    prices = [
        DiscountedCashFlow().price(_bond(0.05), flat_market(r)).fair_value
        for r in (0.01, 0.03, 0.05, 0.07, 0.09)
    ]
    assert all(p2 < p1 for p1, p2 in zip(prices, prices[1:], strict=False))


# --------------------------------------------------------------------------- #
# Black–Scholes                                                                #
# --------------------------------------------------------------------------- #


def _option(kind: str, **kw) -> EuropeanOption:
    defaults = dict(
        spot=42.0,
        strike=40.0,
        time_to_expiry=0.5,
        volatility=0.20,
        risk_free_rate=0.10,
        dividend_yield=0.0,
    )
    defaults.update(kw)
    return EuropeanOption(option_type=kind, **defaults)


def test_hull_golden_values():
    """Hull's textbook example: S=42, K=40, r=10%, sigma=20%, T=0.5.

    Known results: call ~ 4.76, put ~ 0.81.
    """
    market = MarketSnapshot()
    call = BlackScholes().price(_option("Call"), market)
    put = BlackScholes().price(_option("Put"), market)
    assert call.fair_value == pytest.approx(4.76, abs=0.01)
    assert put.fair_value == pytest.approx(0.81, abs=0.01)
    assert call.outputs["d1"] == pytest.approx(0.7693, abs=1e-4)
    assert call.outputs["d2"] == pytest.approx(0.6278, abs=1e-4)


def test_put_call_parity():
    """C - P = S e^{-qT} - K e^{-rT}, for arbitrary parameters."""
    market = MarketSnapshot()
    for S, K, r, q, sigma, T in [
        (100, 100, 0.04, 0.018, 0.2, 1.0),
        (120, 90, 0.06, 0.0, 0.35, 2.5),
        (80, 110, 0.02, 0.03, 0.15, 0.25),
    ]:
        c = (
            BlackScholes()
            .price(
                _option(
                    "Call",
                    spot=S,
                    strike=K,
                    risk_free_rate=r,
                    dividend_yield=q,
                    volatility=sigma,
                    time_to_expiry=T,
                ),
                market,
            )
            .fair_value
        )
        p = (
            BlackScholes()
            .price(
                _option(
                    "Put",
                    spot=S,
                    strike=K,
                    risk_free_rate=r,
                    dividend_yield=q,
                    volatility=sigma,
                    time_to_expiry=T,
                ),
                market,
            )
            .fair_value
        )
        parity = S * math.exp(-q * T) - K * math.exp(-r * T)
        assert c - p == pytest.approx(parity, abs=1e-10)


def test_option_value_increases_with_volatility():
    market = MarketSnapshot()
    values = [
        BlackScholes().price(_option("Call", volatility=v), market).fair_value
        for v in (0.05, 0.10, 0.20, 0.40, 0.80)
    ]
    assert all(v2 > v1 for v1, v2 in zip(values, values[1:], strict=False))


def test_deep_itm_call_approaches_discounted_forward_intrinsic():
    """For S >> K: C -> S e^{-qT} - K e^{-rT} (optionality worth ~nothing)."""
    market = MarketSnapshot()
    o = _option("Call", spot=500.0, strike=40.0)
    v = BlackScholes().price(o, market).fair_value
    bound = 500.0 * math.exp(-0.0 * 0.5) - 40.0 * math.exp(-0.10 * 0.5)
    assert v == pytest.approx(bound, rel=1e-9)


def test_market_snapshot_supplies_rates_when_not_overridden():
    """Leaving r and q blank pulls snapshot values, with provenance recorded."""
    market = MarketSnapshot()
    o = EuropeanOption("Call", 100.0, 100.0, 1.0, 0.20)  # no r, q given
    result = BlackScholes().price(o, market)
    assert result.outputs["risk_free_rate_used"] == pytest.approx(0.042)
    assert result.outputs["dividend_yield_used"] == pytest.approx(0.018)


def test_option_from_inputs_percent_conversion():
    o = EuropeanOption.from_inputs(
        {
            "option_type": "Put",
            "spot": 100,
            "strike": 95,
            "time_to_expiry": 1.5,
            "volatility": 25,  # percent in the form
            "risk_free_rate": "",  # blank -> use market
        }
    )
    assert o.volatility == pytest.approx(0.25)
    assert o.risk_free_rate is None


def test_all_models_emit_traces():
    """House rule check across every Phase 1 product/model pairing."""
    market = MarketSnapshot()
    results = [
        DiscountedCashFlow().price(
            ZeroCouponBond(100, date(2026, 8, 3), date(2030, 8, 3)), market
        ),
        DiscountedCashFlow().price(_bond(0.05), market),
        BlackScholes().price(_option("Call"), market),
    ]
    for r in results:
        assert len(r.steps) > 0
        assert r.runtime_ms is not None and r.runtime_ms >= 0
        assert r.to_dict()["steps"]  # serializes cleanly for the API
