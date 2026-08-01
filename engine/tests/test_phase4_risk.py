"""Phase 4 tests: risk measures and explainability content.

The gold standard for analytic sensitivities is agreement with brute force:
every Greek is checked against a central finite difference of the pricing
function, and every bond measure against bump-and-reprice. Content files are
tested for structural completeness so a missing explanation fails CI, not a
user.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from efpvl_engine import MarketSnapshot
from efpvl_engine.content import model_content, risk_content
from efpvl_engine.models.black_scholes import BlackScholes
from efpvl_engine.models.discounted_cash_flow import DiscountedCashFlow
from efpvl_engine.products.coupon_bond import CouponBond
from efpvl_engine.products.european_option import EuropeanOption
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond

MARKET = MarketSnapshot()


def bs_price(kind: str, S=100.0, K=100.0, T=1.0, sigma=0.2, r=0.04, q=0.018):
    o = EuropeanOption(kind, S, K, T, sigma, risk_free_rate=r, dividend_yield=q)
    return BlackScholes().price(o, MARKET).fair_value


def bs_greeks(kind: str, S=100.0, K=100.0, T=1.0, sigma=0.2, r=0.04, q=0.018):
    o = EuropeanOption(kind, S, K, T, sigma, risk_free_rate=r, dividend_yield=q)
    return BlackScholes().risk_measures(o, MARKET)


# --------------------------------------------------------------------------- #
# Greeks vs finite differences                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["Call", "Put"])
@pytest.mark.parametrize("moneyness", [0.85, 1.0, 1.2])
def test_delta_matches_finite_difference(kind, moneyness):
    S = 100.0 * moneyness
    g = bs_greeks(kind, S=S)
    h = 1e-3
    fd = (bs_price(kind, S=S + h) - bs_price(kind, S=S - h)) / (2 * h)
    assert g["delta"] == pytest.approx(fd, abs=1e-6)


@pytest.mark.parametrize("kind", ["Call", "Put"])
def test_gamma_matches_finite_difference(kind):
    h = 1e-2
    fd = (
        bs_price(kind, S=100 + h) - 2 * bs_price(kind) + bs_price(kind, S=100 - h)
    ) / h**2
    assert bs_greeks(kind)["gamma"] == pytest.approx(fd, rel=1e-4)


@pytest.mark.parametrize("kind", ["Call", "Put"])
def test_vega_matches_finite_difference(kind):
    h = 1e-5
    fd = (bs_price(kind, sigma=0.2 + h) - bs_price(kind, sigma=0.2 - h)) / (2 * h)
    assert bs_greeks(kind)["vega"] == pytest.approx(fd / 100.0, rel=1e-6)


@pytest.mark.parametrize("kind", ["Call", "Put"])
def test_theta_matches_finite_difference(kind):
    h = 1e-5
    # Theta is -dV/dT (value change as calendar time passes = T shrinking)
    fd = -(bs_price(kind, T=1.0 + h) - bs_price(kind, T=1.0 - h)) / (2 * h)
    assert bs_greeks(kind)["theta"] == pytest.approx(fd / 365.0, rel=1e-5)


@pytest.mark.parametrize("kind", ["Call", "Put"])
def test_rho_matches_finite_difference(kind):
    h = 1e-6
    fd = (bs_price(kind, r=0.04 + h) - bs_price(kind, r=0.04 - h)) / (2 * h)
    assert bs_greeks(kind)["rho"] == pytest.approx(fd / 100.0, rel=1e-6)


def test_greek_identities_and_signs():
    c, p = bs_greeks("Call"), bs_greeks("Put")
    q, T = 0.018, 1.0
    # Put-call delta parity: Δc - Δp = e^{-qT}
    assert c["delta"] - p["delta"] == pytest.approx(math.exp(-q * T), abs=1e-12)
    # Gamma and vega are strike-symmetric across call/put
    assert c["gamma"] == pytest.approx(p["gamma"], rel=1e-12)
    assert c["vega"] == pytest.approx(p["vega"], rel=1e-12)
    assert c["gamma"] > 0 and c["vega"] > 0
    assert 0 < c["delta"] < 1 and -1 < p["delta"] < 0
    assert c["rho"] > 0 > p["rho"]


# --------------------------------------------------------------------------- #
# Bond risk vs bump-and-reprice                                                #
# --------------------------------------------------------------------------- #


def make_bond(coupon=0.05, years=5, freq=2) -> CouponBond:
    return CouponBond(
        face_value=100.0,
        coupon_rate=coupon,
        frequency=freq,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2026 + years, 8, 3),
    )


def yield_price(bond: CouponBond, y: float) -> float:
    m = bond.frequency
    times = bond.year_fractions()
    flows = [amt for _, amt, _ in bond.cashflows()]
    times = times + [times[-1]]
    return sum(cf * (1 + y / m) ** (-m * t) for cf, t in zip(flows, times, strict=True))


def test_zero_coupon_macaulay_equals_maturity():
    """The classic sanity check: a zero's duration IS its maturity."""
    zcb = ZeroCouponBond(100.0, date(2026, 8, 3), date(2031, 8, 3))
    r = DiscountedCashFlow().risk_measures(zcb, MARKET)
    assert r["macaulay_duration"] == pytest.approx(zcb.time_to_maturity(), rel=1e-10)


def test_modified_duration_matches_numerical_derivative():
    bond = make_bond()
    r = DiscountedCashFlow().risk_measures(bond, MARKET)
    y, h = r["yield_to_maturity"], 1e-6
    p0 = yield_price(bond, y)
    dpdy = (yield_price(bond, y + h) - yield_price(bond, y - h)) / (2 * h)
    assert r["modified_duration"] == pytest.approx(-dpdy / p0, rel=1e-7)


def test_convexity_matches_numerical_second_derivative():
    bond = make_bond(years=10)
    r = DiscountedCashFlow().risk_measures(bond, MARKET)
    y, h = r["yield_to_maturity"], 1e-4
    p0 = yield_price(bond, y)
    d2 = (yield_price(bond, y + h) - 2 * p0 + yield_price(bond, y - h)) / h**2
    assert r["convexity"] == pytest.approx(d2 / p0, rel=1e-5)
    assert r["convexity"] > 0


def test_dv01_matches_one_bp_bump():
    bond = make_bond()
    r = DiscountedCashFlow().risk_measures(bond, MARKET)
    y = r["yield_to_maturity"]
    bump = (yield_price(bond, y - 1e-4) - yield_price(bond, y + 1e-4)) / 2
    assert r["dv01"] == pytest.approx(bump, rel=1e-4)


def test_longer_bonds_have_more_duration():
    r3 = DiscountedCashFlow().risk_measures(make_bond(years=3), MARKET)
    r10 = DiscountedCashFlow().risk_measures(make_bond(years=10), MARKET)
    assert r10["modified_duration"] > r3["modified_duration"]
    assert r10["convexity"] > r3["convexity"]


# --------------------------------------------------------------------------- #
# Content integrity                                                            #
# --------------------------------------------------------------------------- #

MODEL_KEYS = {
    "model_id",
    "display_name",
    "overview",
    "formula_latex",
    "variables",
    "assumptions",
    "limitations",
    "when_to_use",
    "when_not_to_use",
    "industry_usage",
    "computational_complexity",
}

RISK_KEYS = {
    "name",
    "symbol",
    "unit",
    "formula_latex",
    "definition",
    "interpretation",
    "business_meaning",
    "use_cases",
}


@pytest.mark.parametrize(
    "model_id",
    ["black_scholes", "discounted_cash_flow", "binomial_tree", "monte_carlo"],
)
def test_model_content_is_complete(model_id):
    c = model_content(model_id)
    assert c is not None, f"missing authored content for {model_id}"
    assert set(c.keys()) >= MODEL_KEYS
    assert len(c["variables"]) >= 4
    for v in c["variables"]:
        assert {"symbol", "name", "why_it_matters"} <= set(v.keys())
    assert len(c["assumptions"]) >= 3 and len(c["limitations"]) >= 3


def test_risk_content_covers_every_emitted_measure():
    """Every key a model can emit must have a glossary entry."""
    glossary = risk_content()
    emitted: set[str] = set()
    emitted |= set(bs_greeks("Call").keys())
    emitted |= set(DiscountedCashFlow().risk_measures(make_bond(), MARKET).keys())
    missing = emitted - set(glossary.keys())
    assert not missing, f"risk measures without explanations: {missing}"
    for key, entry in glossary.items():
        assert set(entry.keys()) >= RISK_KEYS, f"incomplete entry: {key}"


def test_describe_serves_authored_content_for_every_registered_model():
    """Regression for the empty-Explainability bug: it is not enough for the
    content file to exist — describe(), which the API serves, must return it.
    """
    import efpvl_engine as e

    for cls in e.list_models():
        d = cls.describe()
        assert d.get("overview"), f"{cls.model_id}: describe() returned empty overview"
        assert d.get("formula_latex"), f"{cls.model_id}: no formula in describe()"
        assert len(d.get("variables", [])) >= 4, f"{cls.model_id}: variables missing"
        assert d.get("assumptions") and d.get("limitations")


def test_content_files_decode_as_utf8_with_expected_unicode():
    """The Windows bug: files are UTF-8 and loaders must say so explicitly.
    The en-dash in 'Black–Scholes–Merton' is the canary."""
    from efpvl_engine.content import model_content

    bs = model_content("black_scholes")
    assert "–" in bs["display_name"]  # real en-dash, not 'â€“'
    assert "â" not in bs["display_name"]
