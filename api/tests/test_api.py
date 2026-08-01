"""Phase 2 API tests — the waiter's exam.

Covers the happy path of every endpoint and, just as importantly, every
error path: unknown ids (404), incompatible model/product (400), per-field
validation failures (422), sweep abuse (cap enforced by Pydantic), and
economically invalid terms (400).
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BOND_INPUTS = {
    "face_value": 100,
    "coupon_rate": 5,
    "frequency": "Semiannual",
    "settlement_date": "2026-08-03",
    "maturity_date": "2031-08-03",
    "day_count": "30/360",
}

OPTION_INPUTS = {
    "option_type": "Call",
    "spot": 42,
    "strike": 40,
    "time_to_expiry": 0.5,
    "volatility": 20,
    "risk_free_rate": 10,
    "dividend_yield": 0,
}


# --------------------------------------------------------------------------- #
# Catalog                                                                      #
# --------------------------------------------------------------------------- #


def test_products_catalog():
    r = client.get("/api/products")
    assert r.status_code == 200
    ids = {p["product_id"] for p in r.json()}
    assert {"zero_coupon_bond", "coupon_bond", "european_option"} <= ids
    for p in r.json():
        assert p["display_name"] and p["asset_class"] and p["supported_models"]


def test_product_schema_drives_forms():
    r = client.get("/api/products/coupon_bond/schema")
    assert r.status_code == 200
    body = r.json()
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["coupon_rate"]["unit"] == "%"
    assert fields["coupon_rate"]["min"] == 0.0
    assert fields["frequency"]["choices"] == ["Annual", "Semiannual", "Quarterly"]
    assert fields["settlement_date"]["type"] == "date"


def test_unknown_product_is_404():
    assert client.get("/api/products/nope/schema").status_code == 404


def test_models_catalog_and_detail():
    r = client.get("/api/models")
    assert r.status_code == 200
    ids = {m["model_id"] for m in r.json()}
    assert {"discounted_cash_flow", "black_scholes"} <= ids

    r2 = client.get("/api/models/black_scholes")
    assert r2.status_code == 200
    body = r2.json()
    assert body["assumptions"] and body["limitations"]
    assert client.get("/api/models/nope").status_code == 404


def test_market_data_has_provenance_and_curve():
    r = client.get("/api/market-data")
    assert r.status_code == 200
    body = r.json()
    assert set(body["provenance_legend"]) == {"market", "user", "derived"}
    assert body["snapshot"]["snapshot_id"]
    assert len(body["curve"]["pillars"]) >= 5


# --------------------------------------------------------------------------- #
# Valuation                                                                    #
# --------------------------------------------------------------------------- #


def test_valuate_bond_full_result():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": BOND_INPUTS,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fair_value"] > 0
    assert body["outputs"]["clean_price"] > 0
    assert body["outputs"]["yield_to_maturity"] == pytest.approx(0.04005, abs=1e-4)
    assert len(body["steps"]) >= 12  # every coupon PV + summary steps
    assert body["runtime_ms"] is not None


def test_valuate_option_matches_hull():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": OPTION_INPUTS,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fair_value"] == pytest.approx(4.76, abs=0.01)
    labels = [s["label"] for s in body["steps"]]
    assert "d1" in labels and "Time value" in labels


def test_validation_errors_are_422_with_fields():
    bad = dict(BOND_INPUTS, coupon_rate=-3)
    bad.pop("maturity_date")
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": bad,
        },
    )
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert {"coupon_rate", "maturity_date"} <= fields


def test_incompatible_model_is_400():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "black_scholes",
            "inputs": BOND_INPUTS,
        },
    )
    assert r.status_code == 400
    assert "cannot price" in r.json()["detail"]


def test_bad_economics_is_400():
    bad = dict(BOND_INPUTS, maturity_date="2020-01-01")  # matures before settlement
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": bad,
        },
    )
    assert r.status_code == 400


def test_unknown_request_fields_rejected():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": BOND_INPUTS,
            "surprise": True,
        },
    )
    assert r.status_code == 422  # extra="forbid"


# --------------------------------------------------------------------------- #
# Sensitivity                                                                  #
# --------------------------------------------------------------------------- #


def test_sensitivity_option_value_vs_volatility_is_increasing():
    r = client.post(
        "/api/sensitivity",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": OPTION_INPUTS,
            "sweep": {
                "field": "volatility",
                "min_value": 5,
                "max_value": 80,
                "points": 25,
            },
        },
    )
    assert r.status_code == 200
    values = [p["fair_value"] for p in r.json()["points"]]
    assert len(values) == 25
    assert all(b > a for a, b in pairwise(values))


def test_sensitivity_bond_price_vs_coupon_is_increasing():
    r = client.post(
        "/api/sensitivity",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": BOND_INPUTS,
            "sweep": {
                "field": "coupon_rate",
                "min_value": 0,
                "max_value": 10,
                "points": 11,
            },
        },
    )
    assert r.status_code == 200
    values = [p["fair_value"] for p in r.json()["points"]]
    assert all(b > a for a, b in pairwise(values))


def test_sweep_point_cap_enforced():
    r = client.post(
        "/api/sensitivity",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": OPTION_INPUTS,
            "sweep": {
                "field": "volatility",
                "min_value": 5,
                "max_value": 80,
                "points": 100000,
            },
        },
    )
    assert r.status_code == 422  # Pydantic le=200 cap


def test_sweep_unknown_field_is_400():
    r = client.post(
        "/api/sensitivity",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": OPTION_INPUTS,
            "sweep": {"field": "banana", "min_value": 0, "max_value": 1, "points": 5},
        },
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Risk & explainability (Phase 4)                                              #
# --------------------------------------------------------------------------- #


def test_risk_option_greeks_with_content():
    r = client.post(
        "/api/risk",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": OPTION_INPUTS,
        },
    )
    assert r.status_code == 200
    measures = {m["key"]: m for m in r.json()["measures"]}
    assert set(measures) == {"delta", "gamma", "vega", "theta", "rho"}
    assert 0 < measures["delta"]["value"] < 1
    # authored content is joined onto each measure
    assert measures["delta"]["definition"]
    assert measures["gamma"]["business_meaning"]


def test_risk_bond_durations_with_content():
    r = client.post(
        "/api/risk",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": BOND_INPUTS,
        },
    )
    assert r.status_code == 200
    measures = {m["key"]: m["value"] for m in r.json()["measures"]}
    assert measures["macaulay_duration"] > measures["modified_duration"] > 0
    assert measures["convexity"] > 0 and measures["dv01"] > 0


def test_risk_validation_and_errors():
    bad = dict(BOND_INPUTS, coupon_rate=-1)
    r = client.post(
        "/api/risk",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": bad,
        },
    )
    assert r.status_code == 422


def test_explain_risk_glossary():
    r = client.get("/api/explain/risk")
    assert r.status_code == 200
    body = r.json()
    assert {"delta", "dv01", "convexity"} <= set(body.keys())
    assert body["delta"]["formula_latex"]


def test_models_detail_returns_authored_content():
    r = client.get("/api/models/black_scholes")
    assert r.status_code == 200
    body = r.json()
    assert body["formula_latex"] and len(body["variables"]) >= 4
    assert body["when_to_use"] and body["when_not_to_use"]


# --------------------------------------------------------------------------- #
# Phase 5: rates products and numerical models                                 #
# --------------------------------------------------------------------------- #

SWAP_INPUTS = {
    "notional": 1_000_000,
    "fixed_rate": 4.0,
    "position": "Pay fixed",
    "frequency": "Semiannual",
    "settlement_date": "2026-08-03",
    "maturity_date": "2031-08-03",
    "day_count": "ACT/360",
}


def test_catalog_now_has_six_products():
    r = client.get("/api/products")
    ids = {p["product_id"] for p in r.json()}
    assert {
        "forward_rate_agreement",
        "interest_rate_swap",
        "floating_rate_note",
    } <= ids


def test_valuate_swap_with_par_rate_output():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "interest_rate_swap",
            "model_id": "discounted_cash_flow",
            "inputs": SWAP_INPUTS,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "par_rate" in body["outputs"]
    assert body["outputs"]["floating_leg_pv"] > 0
    assert any("Par swap rate" in s["label"] for s in body["steps"])


def test_valuate_frn_zero_spread_is_par():
    inputs = {
        "notional": 1_000_000,
        "spread_bps": 0,
        "frequency": "Quarterly",
        "settlement_date": "2026-08-03",
        "maturity_date": "2031-08-03",
        "day_count": "ACT/360",
    }
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "floating_rate_note",
            "model_id": "discounted_cash_flow",
            "inputs": inputs,
        },
    )
    assert r.status_code == 200
    assert r.json()["fair_value"] == pytest.approx(1_000_000, rel=1e-9)


def test_option_prices_across_three_models_agree():
    values = {}
    for model in ("black_scholes", "binomial_tree", "monte_carlo"):
        r = client.post(
            "/api/valuate",
            json={
                "product_id": "european_option",
                "model_id": model,
                "inputs": OPTION_INPUTS,
            },
        )
        assert r.status_code == 200
        values[model] = r.json()["fair_value"]
    assert values["binomial_tree"] == pytest.approx(values["black_scholes"], rel=3e-3)
    assert values["monte_carlo"] == pytest.approx(values["black_scholes"], rel=2e-2)


def test_swap_risk_endpoint_pv01():
    r = client.post(
        "/api/risk",
        json={
            "product_id": "interest_rate_swap",
            "model_id": "discounted_cash_flow",
            "inputs": SWAP_INPUTS,
        },
    )
    assert r.status_code == 200
    measures = {m["key"]: m for m in r.json()["measures"]}
    assert measures["pv01"]["value"] > 0
    assert measures["pv01"]["definition"]  # glossary joined
    assert "dv01" in measures and "par_rate" in measures


# --------------------------------------------------------------------------- #
# Phase 5 Batch C: credit, FX, commodity, inflation                            #
# --------------------------------------------------------------------------- #


def test_catalog_has_eleven_products():
    r = client.get("/api/products")
    ids = {p["product_id"] for p in r.json()}
    assert {
        "credit_default_swap",
        "fx_forward",
        "currency_swap",
        "commodity_futures",
        "inflation_linked_bond",
    } <= ids
    assert len(ids) == 11


def test_cds_round_trip_with_credit_content():
    inputs = {
        "notional": 1_000_000,
        "contract_spread_bps": 100,
        "market_spread_bps": 95,
        "recovery_rate": 40,
        "position": "Buy protection",
        "frequency": "Quarterly",
        "settlement_date": "2026-08-03",
        "maturity_date": "2031-08-03",
        "day_count": "ACT/360",
    }
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "credit_default_swap",
            "model_id": "hazard_rate",
            "inputs": inputs,
        },
    )
    assert r.status_code == 200
    assert 0 < r.json()["outputs"]["default_probability"] < 1

    r2 = client.post(
        "/api/risk",
        json={
            "product_id": "credit_default_swap",
            "model_id": "hazard_rate",
            "inputs": inputs,
        },
    )
    assert r2.status_code == 200
    measures = {m["key"]: m for m in r2.json()["measures"]}
    assert measures["cs01"]["definition"]  # glossary joined


def test_fx_forward_at_parity_via_api():
    inputs = {
        "notional_foreign": 1_000_000,
        "spot_fx": 1.09,
        "contract_rate": 1.09,
        "foreign_rate": 2.5,
        "time_to_delivery": 1.0,
        "position": "Buy foreign",
    }
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "fx_forward",
            "model_id": "cost_of_carry",
            "inputs": inputs,
        },
    )
    assert r.status_code == 200
    body = r.json()
    fair = body["outputs"]["fair_forward"]
    inputs2 = dict(inputs, contract_rate=fair)
    r2 = client.post(
        "/api/valuate",
        json={
            "product_id": "fx_forward",
            "model_id": "cost_of_carry",
            "inputs": inputs2,
        },
    )
    assert abs(r2.json()["fair_value"]) < 1e-6


def test_every_model_detail_endpoint_serves_full_content():
    """Regression: /models/{id} must never serve empty stubs (the blank
    Explainability page bug)."""
    for m in client.get("/api/models").json():
        detail = client.get(f"/api/models/{m['model_id']}").json()
        assert detail["overview"], f"{m['model_id']} served empty overview"
        assert detail["formula_latex"]
        assert len(detail["variables"]) >= 4


# --------------------------------------------------------------------------- #
# Phase 6: comparison and export                                               #
# --------------------------------------------------------------------------- #


def test_compare_three_models_on_one_option():
    r = client.post(
        "/api/compare",
        json={
            "product_id": "european_option",
            "model_ids": ["black_scholes", "binomial_tree", "monte_carlo"],
            "inputs": OPTION_INPUTS,
        },
    )
    assert r.status_code == 200
    body = r.json()
    rows = {x["model_id"]: x for x in body["results"]}
    assert rows["black_scholes"]["diff_vs_baseline"] == 0.0
    assert abs(rows["binomial_tree"]["diff_bps"]) < 30  # tenths of a bp really
    mc = rows["monte_carlo"]
    assert abs(mc["diff_vs_baseline"]) < 4 * mc["outputs"]["standard_error"]
    assert rows["binomial_tree"]["comparison_note"]
    assert all(x["runtime_ms"] is not None for x in body["results"])


def test_compare_rejects_unsupported_and_short_lists():
    r = client.post(
        "/api/compare",
        json={
            "product_id": "coupon_bond",
            "model_ids": ["discounted_cash_flow", "black_scholes"],
            "inputs": BOND_INPUTS,
        },
    )
    assert r.status_code == 400  # BS cannot price a bond
    r2 = client.post(
        "/api/compare",
        json={
            "product_id": "european_option",
            "model_ids": ["black_scholes"],
            "inputs": OPTION_INPUTS,
        },
    )
    assert r2.status_code == 422  # min 2 models


def test_export_report_returns_pdf_for_option_and_bond():
    for pid, mid, inputs in (
        ("european_option", "black_scholes", OPTION_INPUTS),
        ("coupon_bond", "discounted_cash_flow", BOND_INPUTS),
    ):
        r = client.post(
            "/api/export/report",
            json={"product_id": pid, "model_id": mid, "inputs": inputs},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" in r.headers["content-disposition"]
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 10_000  # a real multi-section document
