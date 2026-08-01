"""Phase 5D tests: the advanced models.

Each model must pass two kinds of trial:

* **Collapse to the baseline** — with its extra machinery switched off, it
  must reproduce the simpler model it generalizes (Heston with xi→0 = BS;
  Merton with lambda=0 = BS exactly; SABR with nu=0 = BS; Vasicek with
  sigma=0 and b=r0 = flat-rate discounting exactly).
* **Its signature economics** — the one qualitative effect it was built to
  produce (skewed wings, fat left tail, mean-reverting duration).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from efpvl_engine import MarketSnapshot
from efpvl_engine.models.black_scholes import BlackScholes
from efpvl_engine.models.heston import Heston
from efpvl_engine.models.jump_and_sabr import SABR, MertonJumpDiffusion
from efpvl_engine.models.vasicek import Vasicek
from efpvl_engine.products.european_option import EuropeanOption
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond

MARKET = MarketSnapshot()
BS = BlackScholes()


def option(kind: str, strike: float = 100.0, vol: float = 0.20) -> EuropeanOption:
    return EuropeanOption(
        kind, 100.0, strike, 1.0, vol, risk_free_rate=0.04, dividend_yield=0.018
    )


# --------------------------------------------------------------------------- #
# Heston                                                                       #
# --------------------------------------------------------------------------- #


class _HestonNoVolOfVol(Heston):
    model_id = "heston_test_flat"
    XI = 1e-4
    RHO = 0.0


@pytest.mark.parametrize("kind", ["Call", "Put"])
@pytest.mark.parametrize("strike", [85.0, 100.0, 115.0])
def test_heston_collapses_to_black_scholes(kind, strike):
    """xi -> 0 with v0 = theta freezes variance at sigma^2: BS must emerge."""
    o = option(kind, strike=strike)
    assert _HestonNoVolOfVol().price(o, MARKET).fair_value == pytest.approx(
        BS.price(o, MARKET).fair_value, rel=2e-3, abs=2e-3
    )


def test_heston_put_call_parity():
    c = Heston().price(option("Call"), MARKET).fair_value
    p = Heston().price(option("Put"), MARKET).fair_value
    parity = 100.0 * math.exp(-0.018) - 100.0 * math.exp(-0.04)
    assert c - p == pytest.approx(parity, abs=1e-3)


def test_heston_negative_rho_skews_toward_low_strikes():
    """The signature: with rho < 0, OTM puts gain value vs BS while OTM calls
    give some up — the left tail is where the extra probability went."""
    otm_put = option("Put", strike=80.0)
    otm_call = option("Call", strike=120.0)
    put_gap = (
        Heston().price(otm_put, MARKET).fair_value
        - BS.price(otm_put, MARKET).fair_value
    )
    call_gap = (
        Heston().price(otm_call, MARKET).fair_value
        - BS.price(otm_call, MARKET).fair_value
    )
    assert put_gap > call_gap


def test_heston_probabilities_are_probabilities():
    res = Heston().price(option("Call"), MARKET)
    assert 0.0 < res.outputs["p1"] < 1.0
    assert 0.0 < res.outputs["p2"] < 1.0
    assert res.outputs["p1"] > res.outputs["p2"]  # standard ordering


# --------------------------------------------------------------------------- #
# Merton Jump Diffusion                                                        #
# --------------------------------------------------------------------------- #


class _MertonNoJumps(MertonJumpDiffusion):
    model_id = "merton_test_nojumps"
    LAMBDA = 0.0


@pytest.mark.parametrize("kind", ["Call", "Put"])
@pytest.mark.parametrize("strike", [85.0, 100.0, 115.0])
def test_merton_with_zero_intensity_is_exactly_black_scholes(kind, strike):
    o = option(kind, strike=strike)
    assert _MertonNoJumps().price(o, MARKET).fair_value == pytest.approx(
        BS.price(o, MARKET).fair_value, rel=1e-12
    )


def test_merton_downward_jumps_fatten_the_left_tail():
    otm_put = option("Put", strike=75.0)
    assert (
        MertonJumpDiffusion().price(otm_put, MARKET).fair_value
        > BS.price(otm_put, MARKET).fair_value
    )


def test_merton_poisson_weights_sum_to_one():
    res = MertonJumpDiffusion().price(option("Call"), MARKET)
    captured = next(s.value for s in res.steps if "Poisson" in s.label)
    assert captured == pytest.approx(1.0, abs=1e-10)


# --------------------------------------------------------------------------- #
# SABR                                                                         #
# --------------------------------------------------------------------------- #


class _SABRFlat(SABR):
    model_id = "sabr_test_flat"
    NU = 0.0
    RHO = 0.0


@pytest.mark.parametrize("kind", ["Call", "Put"])
@pytest.mark.parametrize("strike", [85.0, 100.0, 115.0])
def test_sabr_with_zero_vol_of_vol_is_black_scholes(kind, strike):
    o = option(kind, strike=strike)
    assert _SABRFlat().price(o, MARKET).fair_value == pytest.approx(
        BS.price(o, MARKET).fair_value, rel=1e-10
    )


def test_sabr_negative_rho_tilts_vols_to_low_strikes():
    model = SABR()
    forward = 100.0 * math.exp((0.04 - 0.018) * 1.0)
    low = model.implied_vol(forward, 80.0, 1.0, 0.20)
    atm = model.implied_vol(forward, forward, 1.0, 0.20)
    high = model.implied_vol(forward, 120.0, 1.0, 0.20)
    assert low > atm  # the skew
    assert low > high  # asymmetric: left wing above right


def test_sabr_atm_vol_close_to_alpha():
    model = SABR()
    forward = 100.0 * math.exp((0.04 - 0.018) * 1.0)
    assert model.implied_vol(forward, forward, 1.0, 0.20) == pytest.approx(
        0.20, rel=0.05
    )


# --------------------------------------------------------------------------- #
# Vasicek                                                                      #
# --------------------------------------------------------------------------- #


class _VasicekDeterministic(Vasicek):
    model_id = "vasicek_test_flat"
    SIGMA_R = 0.0


def zcb(years: int) -> ZeroCouponBond:
    return ZeroCouponBond(100.0, date(2026, 8, 3), date(2026 + years, 8, 3))


def test_vasicek_deterministic_limit_hand_formula():
    """sigma = 0: P = exp(-bT - (r0-b)B) exactly — recomputed independently."""
    res = _VasicekDeterministic().price(zcb(5), MARKET)
    T = zcb(5).time_to_maturity()
    a = Vasicek.MEAN_REVERSION_A
    r0 = MARKET.curve.zero_rate(1.0 / 12.0)
    b = MARKET.curve.zero_rate(10.0)
    B = (1 - math.exp(-a * T)) / a
    expected = 100.0 * math.exp(-b * T - (r0 - b) * B)
    assert res.fair_value == pytest.approx(expected, rel=1e-12)


def test_vasicek_prices_decrease_with_maturity():
    values = [Vasicek().price(zcb(y), MARKET).fair_value for y in (1, 5, 10, 20)]
    assert all(v2 < v1 for v1, v2 in zip(values, values[1:], strict=False))
    assert all(0 < v < 100 for v in values)


def test_vasicek_duration_factor_saturates():
    """Mean reversion caps rate risk: B(T) -> 1/a for long maturities."""
    res = Vasicek().price(zcb(30), MARKET)
    B = next(s.value for s in res.steps if s.symbol == "B(T)")
    assert pytest.approx(1.0 / Vasicek.MEAN_REVERSION_A, rel=0.02) == B


def test_vasicek_volatility_raises_bond_prices():
    """Convexity: rate volatility makes bonds slightly MORE valuable."""
    with_vol = Vasicek().price(zcb(10), MARKET).fair_value
    without = _VasicekDeterministic().price(zcb(10), MARKET).fair_value
    assert with_vol > without


# --------------------------------------------------------------------------- #
# Catalog                                                                      #
# --------------------------------------------------------------------------- #


def test_ten_models_and_widened_support():
    import efpvl_engine as e

    assert len(e.list_models()) == 10
    o = option("Call")
    ids = {m.model_id for m in e.models_for(o)}
    assert {
        "black_scholes",
        "binomial_tree",
        "monte_carlo",
        "heston",
        "merton_jump_diffusion",
        "sabr",
    } <= ids
    z = zcb(5)
    zids = {m.model_id for m in e.models_for(z)}
    assert {"discounted_cash_flow", "vasicek"} <= zids
