"""Phase 5 tests: linear rates products and numerical option models.

The identities exercised here are the ones a rates quant would demand:

* Par FRA (K = forward) is worth zero.
* The floating leg telescopes to N(1 − DF(T)).
* A swap struck at the par rate has NPV ≈ 0; value is monotone in the strike.
* A zero-spread FRN at reset is worth exactly par.
* DV01 from analytic annuity vs numerical curve bump agree.
* Binomial (500 steps) converges to Black–Scholes; MC lands within its own
  reported confidence band around Black–Scholes.
"""

from __future__ import annotations

from datetime import date

import pytest

from efpvl_engine import MarketSnapshot
from efpvl_engine.models.binomial_tree import BinomialTree
from efpvl_engine.models.black_scholes import BlackScholes
from efpvl_engine.models.discounted_cash_flow import DiscountedCashFlow
from efpvl_engine.models.monte_carlo import MonteCarlo
from efpvl_engine.products.european_option import EuropeanOption
from efpvl_engine.products.forward_rate_agreement import ForwardRateAgreement
from efpvl_engine.products.rates_swaps import FloatingRateNote, InterestRateSwap

MARKET = MarketSnapshot()
DCF = DiscountedCashFlow()


# --------------------------------------------------------------------------- #
# Forward Rate Agreement                                                       #
# --------------------------------------------------------------------------- #


def make_fra(fixed_rate: float, position: str = "Pay fixed") -> ForwardRateAgreement:
    return ForwardRateAgreement(
        notional=1_000_000.0,
        fixed_rate=fixed_rate,
        settlement_date=date(2026, 8, 3),
        start_date=date(2027, 2, 3),
        end_date=date(2027, 8, 3),
        position=position,
    )


def test_par_fra_is_worthless():
    """Lock exactly the curve's forward and the FRA has zero value."""
    probe = DCF.price(make_fra(0.04), MARKET)
    fwd = probe.outputs["forward_rate"]
    par = DCF.price(make_fra(fwd), MARKET)
    assert par.fair_value == pytest.approx(0.0, abs=1e-6)


def test_fra_signs_and_symmetry():
    fwd = DCF.price(make_fra(0.04), MARKET).outputs["forward_rate"]
    below = DCF.price(make_fra(fwd - 0.01, "Pay fixed"), MARKET).fair_value
    assert below > 0  # locked cheaper than the forward: payer gains
    recv = DCF.price(make_fra(fwd - 0.01, "Receive fixed"), MARKET).fair_value
    assert recv == pytest.approx(-below, rel=1e-12)


def test_fra_hand_formula():
    fra = make_fra(0.03)
    t1, t2, tau = fra.times()
    df1, df2 = MARKET.discount_factor(t1), MARKET.discount_factor(t2)
    fwd = (df1 / df2 - 1) / tau
    expected = fra.notional * tau * (fwd - 0.03) * df2
    assert DCF.price(fra, MARKET).fair_value == pytest.approx(expected, rel=1e-12)


# --------------------------------------------------------------------------- #
# Interest Rate Swap                                                           #
# --------------------------------------------------------------------------- #


def make_swap(fixed_rate: float, position: str = "Pay fixed") -> InterestRateSwap:
    return InterestRateSwap(
        notional=1_000_000.0,
        fixed_rate=fixed_rate,
        frequency=2,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        position=position,
    )


def test_floating_leg_telescopes():
    """PV of projected floating coupons must equal N(1 − DF(T)) exactly."""
    res = DCF.price(make_swap(0.04), MARKET)
    t_end = res.outputs  # noqa: F841 - readability
    swap = make_swap(0.04)
    from efpvl_engine.market.daycount import year_fraction

    t = year_fraction(swap.settlement_date, swap.maturity_date, swap.day_count)
    telescoped = swap.notional * (1.0 - MARKET.discount_factor(t))
    assert res.outputs["floating_leg_pv"] == pytest.approx(telescoped, rel=1e-10)


def test_par_swap_has_zero_npv():
    par = DCF.price(make_swap(0.04), MARKET).outputs["par_rate"]
    res = DCF.price(make_swap(par), MARKET)
    assert res.fair_value == pytest.approx(0.0, abs=1e-6)


def test_payer_value_monotone_decreasing_in_fixed_rate():
    values = [DCF.price(make_swap(k), MARKET).fair_value for k in (0.02, 0.04, 0.06)]
    assert values[0] > values[1] > values[2]


def test_payer_receiver_mirror():
    v_pay = DCF.price(make_swap(0.05, "Pay fixed"), MARKET).fair_value
    v_recv = DCF.price(make_swap(0.05, "Receive fixed"), MARKET).fair_value
    assert v_pay == pytest.approx(-v_recv, rel=1e-12)


def test_swap_risk_pv01_and_dv01_consistent():
    """Analytic PV01 (annuity) and numerical DV01 (curve bump) must agree in
    magnitude for a payer swap, and the payer's DV01 must be positive."""
    risk = DCF.risk_measures(make_swap(0.04), MARKET)
    assert risk["pv01"] > 0
    assert risk["dv01"] > 0  # payer gains when rates rise
    # A payer swap's curve DV01 ≈ fixed-leg PV01 (floating leg ~ rate-neutral)
    assert risk["dv01"] == pytest.approx(risk["pv01"], rel=0.08)
    recv = DCF.risk_measures(make_swap(0.04, "Receive fixed"), MARKET)
    assert recv["dv01"] == pytest.approx(-risk["dv01"], rel=1e-9)


# --------------------------------------------------------------------------- #
# Floating Rate Note                                                           #
# --------------------------------------------------------------------------- #


def make_frn(spread_bps: float) -> FloatingRateNote:
    return FloatingRateNote(
        notional=1_000_000.0,
        spread_bps=spread_bps,
        frequency=4,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
    )


def test_zero_spread_frn_is_par():
    """The cleanest identity in rates: floater at reset, no spread ⇒ par."""
    res = DCF.price(make_frn(0.0), MARKET)
    assert res.fair_value == pytest.approx(1_000_000.0, rel=1e-12)
    assert res.outputs["price_pct_of_par"] == pytest.approx(100.0, abs=1e-9)


def test_positive_spread_frn_above_par():
    assert DCF.price(make_frn(50.0), MARKET).fair_value > 1_000_000.0
    assert DCF.price(make_frn(-50.0), MARKET).fair_value < 1_000_000.0


def test_frn_dv01_is_small():
    """A floater's rate risk is tiny next to a fixed bond's — that's its point."""
    frn_risk = DCF.risk_measures(make_frn(0.0), MARKET)
    # 5y $1m fixed bond DV01 is ~$450; the floater should be ~two orders less
    assert abs(frn_risk["dv01"]) < 50.0


# --------------------------------------------------------------------------- #
# Numerical models vs Black–Scholes                                            #
# --------------------------------------------------------------------------- #


def make_option(kind: str, **kw) -> EuropeanOption:
    base = dict(
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.018,
    )
    base.update(kw)
    return EuropeanOption(kind, **base)


@pytest.mark.parametrize("kind", ["Call", "Put"])
@pytest.mark.parametrize("strike", [80.0, 100.0, 120.0])
def test_binomial_converges_to_black_scholes(kind, strike):
    o = make_option(kind, strike=strike)
    bs = BlackScholes().price(o, MARKET).fair_value
    tree = BinomialTree().price(o, MARKET).fair_value
    assert tree == pytest.approx(bs, rel=2e-3, abs=2e-3)


def test_binomial_risk_neutral_probability_traced():
    res = BinomialTree().price(make_option("Call"), MARKET)
    assert 0.0 < res.outputs["risk_neutral_p"] < 1.0
    assert any("Risk-neutral" in s.label for s in res.steps)


@pytest.mark.parametrize("kind", ["Call", "Put"])
def test_monte_carlo_within_its_own_confidence_band(kind):
    o = make_option(kind)
    bs = BlackScholes().price(o, MARKET).fair_value
    mc = MonteCarlo().price(o, MARKET)
    se = mc.outputs["standard_error"]
    assert se > 0
    assert abs(mc.fair_value - bs) < 4 * se  # generous: 4 SE


def test_monte_carlo_is_reproducible():
    o = make_option("Call")
    v1 = MonteCarlo().price(o, MARKET).fair_value
    v2 = MonteCarlo().price(o, MARKET).fair_value
    assert v1 == v2  # fixed seed: same answer every run


def test_option_supported_by_at_least_three_models():
    from efpvl_engine import models_for

    ids = {m.model_id for m in models_for(make_option("Call"))}
    assert {"black_scholes", "binomial_tree", "monte_carlo"} <= ids


def test_new_models_have_authored_content():
    from efpvl_engine.content import model_content

    for mid in ("binomial_tree", "monte_carlo"):
        c = model_content(mid)
        assert c is not None and len(c["variables"]) >= 4


def test_glossary_covers_swap_measures():
    from efpvl_engine.content import risk_content

    emitted = set(DCF.risk_measures(make_swap(0.04), MARKET).keys())
    assert emitted <= set(risk_content().keys())
