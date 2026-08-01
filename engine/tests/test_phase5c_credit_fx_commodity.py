"""Phase 5 Batch C tests: credit, FX, commodity, and inflation products.

The signature identities:

* A CDS struck at its own par spread is worth zero; buyer/seller mirror.
* An FX forward struck at the parity forward is worth zero; delta ≈ N e^{−r_f T}.
* Commodity fair futures rises with storage cost, falls with convenience yield.
* Currency swap positions mirror; the domestic leg equals a plain bond's PV.
* An inflation-linked bond at π = 0 IS the nominal coupon bond — exactly.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from efpvl_engine import MarketSnapshot
from efpvl_engine.market.daycount import DayCount
from efpvl_engine.models.discounted_cash_flow import DiscountedCashFlow
from efpvl_engine.models.hazard_rate import HazardRate
from efpvl_engine.products.coupon_bond import CouponBond
from efpvl_engine.products.credit_default_swap import CreditDefaultSwap
from efpvl_engine.products.currency_and_inflation import (
    CurrencySwap,
    InflationLinkedBond,
)
from efpvl_engine.products.fx_and_commodity import (
    CommodityFutures,
    CostOfCarry,
    FXForward,
)

MARKET = MarketSnapshot()
DCF = DiscountedCashFlow()
COC = CostOfCarry()
HAZ = HazardRate()


# --------------------------------------------------------------------------- #
# Credit Default Swap                                                          #
# --------------------------------------------------------------------------- #


def make_cds(
    contract_bps=100.0, market_bps=95.0, recovery=0.4, position="Buy protection"
):
    return CreditDefaultSwap(
        notional=1_000_000.0,
        contract_spread_bps=contract_bps,
        market_spread_bps=market_bps,
        recovery_rate=recovery,
        frequency=4,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        position=position,
    )


def test_cds_at_par_spread_is_worthless():
    par_bps = HAZ.price(make_cds(), MARKET).outputs["par_spread_bps"]
    res = HAZ.price(make_cds(contract_bps=par_bps), MARKET)
    assert res.fair_value == pytest.approx(0.0, abs=1e-6)


def test_cds_buyer_seller_mirror_and_direction():
    buy = HAZ.price(make_cds(contract_bps=50.0), MARKET).fair_value
    sell = HAZ.price(make_cds(contract_bps=50.0, position="Sell protection"), MARKET)
    assert buy > 0  # paying less than fair for protection
    assert sell.fair_value == pytest.approx(-buy, rel=1e-12)


def test_cds_value_increases_with_market_spread_for_buyer():
    values = [
        HAZ.price(make_cds(market_bps=b), MARKET).fair_value for b in (60, 95, 200)
    ]
    assert values[0] < values[1] < values[2]


def test_credit_triangle_and_default_probability():
    res = HAZ.price(make_cds(market_bps=95.0, recovery=0.4), MARKET)
    lam = res.outputs["implied_hazard_rate"]
    assert lam == pytest.approx(0.0095 / 0.6, rel=1e-12)
    pd5 = res.outputs["default_probability"]
    assert 0.0 < pd5 < 1.0
    # PD ≈ 1 − e^{−λ·5y} (schedule year fractions are close to 5.07 ACT/360)
    assert pd5 == pytest.approx(1 - math.exp(-lam * 5.07), abs=0.005)


def test_cds_risk_measures():
    risk = HAZ.risk_measures(make_cds(), MARKET)
    assert risk["cs01"] > 0  # buyer gains as spreads widen
    assert 0 < risk["default_probability"] < 1
    sell = HAZ.risk_measures(make_cds(position="Sell protection"), MARKET)
    assert sell["cs01"] == pytest.approx(-risk["cs01"], rel=1e-9)


# --------------------------------------------------------------------------- #
# FX Forward                                                                   #
# --------------------------------------------------------------------------- #


def make_fx(contract_rate: float, position="Buy foreign") -> FXForward:
    return FXForward(
        notional_foreign=1_000_000.0,
        spot_fx=1.09,
        contract_rate=contract_rate,
        foreign_rate=0.025,
        time_to_delivery=1.0,
        position=position,
    )


def test_fx_forward_at_parity_is_worthless():
    fair = COC.price(make_fx(1.09), MARKET).outputs["fair_forward"]
    assert COC.price(make_fx(fair), MARKET).fair_value == pytest.approx(0.0, abs=1e-8)


def test_covered_interest_parity_hand_formula():
    res = COC.price(make_fx(1.09), MARKET)
    r_d = res.outputs["domestic_rate_used"]
    expected = 1.09 * math.exp((r_d - 0.025) * 1.0)
    assert res.outputs["fair_forward"] == pytest.approx(expected, rel=1e-12)
    # Domestic rates above foreign ⇒ forward premium
    assert res.outputs["fair_forward"] > 1.09


def test_fx_forward_mirror_and_delta():
    v_buy = COC.price(make_fx(1.05), MARKET).fair_value
    v_sell = COC.price(make_fx(1.05, "Sell foreign"), MARKET).fair_value
    assert v_buy == pytest.approx(-v_sell, rel=1e-12)

    risk = COC.risk_measures(make_fx(1.05), MARKET)
    # Analytic: dV/dS = N e^{-r_f T}
    assert risk["fx_delta"] == pytest.approx(1_000_000.0 * math.exp(-0.025), rel=1e-3)


# --------------------------------------------------------------------------- #
# Commodity Futures                                                            #
# --------------------------------------------------------------------------- #


def make_commodity(storage=0.02, convenience=0.015, contract=80.0) -> CommodityFutures:
    return CommodityFutures(
        contracts_units=1000.0,
        spot_price=78.4,
        contract_price=contract,
        storage_cost=storage,
        convenience_yield=convenience,
        time_to_delivery=0.5,
        position="Long",
    )


def test_commodity_futures_at_fair_price_is_worthless():
    fair = COC.price(make_commodity(), MARKET).outputs["fair_futures_price"]
    res = COC.price(make_commodity(contract=fair), MARKET)
    assert res.fair_value == pytest.approx(0.0, abs=1e-8)


def test_carry_monotonicity():
    base = COC.price(make_commodity(), MARKET).outputs["fair_futures_price"]
    more_storage = COC.price(make_commodity(storage=0.06), MARKET).outputs[
        "fair_futures_price"
    ]
    more_convenience = COC.price(make_commodity(convenience=0.08), MARKET).outputs[
        "fair_futures_price"
    ]
    assert more_storage > base  # storage costs push futures up
    assert more_convenience < base  # convenience pulls them down (backwardation)


def test_commodity_spot_delta():
    risk = COC.risk_measures(make_commodity(), MARKET)
    res = COC.price(make_commodity(), MARKET)
    analytic = (
        1000.0 * res.outputs["fair_futures_price"] / 78.4 * MARKET.discount_factor(0.5)
    )
    assert risk["spot_delta"] == pytest.approx(analytic, rel=1e-3)


# --------------------------------------------------------------------------- #
# Currency Swap                                                                #
# --------------------------------------------------------------------------- #


def make_ccy_swap(position="Receive foreign") -> CurrencySwap:
    return CurrencySwap(
        notional_domestic=1_000_000.0,
        spot_fx=1.09,
        domestic_rate_leg=0.04,
        foreign_rate_leg=0.025,
        foreign_discount_rate=0.025,
        frequency=1,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        position=position,
    )


def test_currency_swap_positions_mirror():
    v1 = DCF.price(make_ccy_swap(), MARKET).fair_value
    v2 = DCF.price(make_ccy_swap("Receive domestic"), MARKET).fair_value
    assert v1 == pytest.approx(-v2, rel=1e-12)


def test_currency_swap_domestic_leg_is_a_bond():
    """The domestic leg must equal a plain coupon bond's dirty price."""
    swap_leg = DCF.price(make_ccy_swap(), MARKET).outputs["domestic_leg_pv"]
    bond = CouponBond(
        face_value=1_000_000.0,
        coupon_rate=0.04,
        frequency=1,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        day_count=DayCount.THIRTY_360,
    )
    bond_pv = DCF.price(bond, MARKET).outputs["dirty_price"]
    assert swap_leg == pytest.approx(bond_pv, rel=1e-10)


def test_currency_swap_fx_delta_equals_foreign_leg_pv():
    """Seasoned swap, fixed foreign notional: dV/dS = PV of the foreign leg
    in foreign currency (the converted value is linear in spot)."""
    risk = DCF.risk_measures(make_ccy_swap(), MARKET)
    pv_f = DCF.price(make_ccy_swap(), MARKET).outputs["foreign_leg_pv_foreign_ccy"]
    assert risk["fx_delta"] == pytest.approx(pv_f, rel=1e-12)
    assert risk["fx_delta"] > 0
    recv_dom = DCF.risk_measures(make_ccy_swap("Receive domestic"), MARKET)
    assert recv_dom["fx_delta"] == pytest.approx(-pv_f, rel=1e-12)


# --------------------------------------------------------------------------- #
# Inflation-Linked Bond                                                        #
# --------------------------------------------------------------------------- #


def make_linker(breakeven=0.023, coupon=0.015) -> InflationLinkedBond:
    return InflationLinkedBond(
        face_value=100.0,
        real_coupon_rate=coupon,
        breakeven_inflation=breakeven,
        frequency=2,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
    )


def test_linker_at_zero_breakeven_is_the_nominal_bond():
    """π = 0 must reproduce the plain coupon bond to machine precision."""
    linker = DCF.price(make_linker(breakeven=0.0, coupon=0.05), MARKET).fair_value
    bond = CouponBond(
        face_value=100.0,
        coupon_rate=0.05,
        frequency=2,
        settlement_date=date(2026, 8, 3),
        maturity_date=date(2031, 8, 3),
        day_count=DayCount.THIRTY_360,
    )
    nominal = DCF.price(bond, MARKET).outputs["dirty_price"]
    assert linker == pytest.approx(nominal, rel=1e-12)


def test_linker_value_monotone_in_breakeven():
    values = [
        DCF.price(make_linker(breakeven=pi), MARKET).fair_value
        for pi in (0.0, 0.02, 0.04)
    ]
    assert values[0] < values[1] < values[2]


def test_linker_risk_measures():
    risk = DCF.risk_measures(make_linker(), MARKET)
    assert risk["inflation01"] > 0
    assert risk["dv01"] < 0  # a long bond loses when nominal rates rise


# --------------------------------------------------------------------------- #
# Catalog & content integrity                                                  #
# --------------------------------------------------------------------------- #


def test_eleven_products_ten_models():
    import efpvl_engine as e

    assert len(e.list_products()) == 11
    assert len(e.list_models()) == 10


def test_new_models_content_and_glossary_coverage():
    from efpvl_engine.content import model_content, risk_content

    for mid in ("hazard_rate", "cost_of_carry"):
        c = model_content(mid)
        assert c is not None and len(c["variables"]) >= 4

    glossary = set(risk_content().keys())
    emitted: set[str] = set()
    emitted |= set(HAZ.risk_measures(make_cds(), MARKET).keys())
    emitted |= set(COC.risk_measures(make_fx(1.05), MARKET).keys())
    emitted |= set(COC.risk_measures(make_commodity(), MARKET).keys())
    emitted |= set(DCF.risk_measures(make_ccy_swap(), MARKET).keys())
    emitted |= set(DCF.risk_measures(make_linker(), MARKET).keys())
    missing = emitted - glossary
    assert not missing, f"measures without explanations: {missing}"
