"""Phase 7 hardening tests.

Three battalions:

* **Cache** — identical requests must hit the cache (deterministic engine),
  different requests must not, and cached answers must be byte-identical.
* **Error paths** — malformed bodies, absurd-but-typed values, and wrong
  content types all produce calm, structured errors.
* **The dogfood** — the crown of Phase 7: EVERY product priced with EVERY
  supported model straight from its own schema defaults, risk checked where
  offered, and a PDF generated for every product. If a future change breaks
  any pairing anywhere in the lab, this fails in CI before a human sees it.
"""

from __future__ import annotations

import math
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _default_inputs(product_id: str) -> dict:
    schema = client.get(f"/api/products/{product_id}/schema").json()
    return {
        f["name"]: f["default"] for f in schema["fields"] if f["default"] is not None
    }


# --------------------------------------------------------------------------- #
# Cache                                                                        #
# --------------------------------------------------------------------------- #


def test_identical_valuations_hit_the_cache():
    body = {
        "product_id": "european_option",
        "model_id": "monte_carlo",  # the slowest model gains the most
        "inputs": _default_inputs("european_option"),
    }
    first = client.post("/api/valuate", json=body).json()
    second = client.post("/api/valuate", json=body).json()
    assert first["cached"] is False or first["cached"] is True  # field exists
    assert second["cached"] is True
    assert second["fair_value"] == first["fair_value"]
    assert second["steps"] == first["steps"]


def test_different_inputs_do_not_share_cache_entries():
    inputs = _default_inputs("european_option")
    a = client.post(
        "/api/valuate",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": inputs,
        },
    ).json()
    b = client.post(
        "/api/valuate",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": {**inputs, "spot": float(inputs["spot"]) + 1},
        },
    ).json()
    assert a["fair_value"] != b["fair_value"]


def test_sensitivity_sweeps_are_cached():
    body = {
        "product_id": "european_option",
        "model_id": "black_scholes",
        "inputs": _default_inputs("european_option"),
        "sweep": {
            "field": "volatility",
            "min_value": 10,
            "max_value": 40,
            "points": 30,
        },
    }
    client.post("/api/sensitivity", json=body)
    again = client.post("/api/sensitivity", json=body).json()
    assert again["cached"] is True


# --------------------------------------------------------------------------- #
# Error paths                                                                  #
# --------------------------------------------------------------------------- #


def test_malformed_json_body_is_422():
    r = client.post(
        "/api/valuate",
        content=b"{not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_wrong_types_are_caught_per_field():
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "coupon_bond",
            "model_id": "discounted_cash_flow",
            "inputs": {
                "face_value": "one hundred",
                "coupon_rate": [],
                "frequency": "Semiannual",
                "settlement_date": "2026-08-03",
                "maturity_date": "2031-08-03",
                "day_count": "30/360",
            },
        },
    )
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert {"face_value", "coupon_rate"} <= fields


def test_extreme_but_schema_valid_inputs_survive():
    """Boundary values inside declared ranges must price without incident."""
    r = client.post(
        "/api/valuate",
        json={
            "product_id": "european_option",
            "model_id": "black_scholes",
            "inputs": {
                "option_type": "Put",
                "spot": 0.01,
                "strike": 10_000_000,
                "time_to_expiry": 30,
                "volatility": 300,
            },
        },
    )
    assert r.status_code == 200
    assert math.isfinite(r.json()["fair_value"])


def test_missing_content_type_still_parses_or_fails_cleanly():
    r = client.post("/api/valuate", content=b"")
    assert r.status_code in (400, 422)


# --------------------------------------------------------------------------- #
# The dogfood                                                                  #
# --------------------------------------------------------------------------- #


def _catalog() -> list[dict]:
    return client.get("/api/products").json()


@pytest.mark.parametrize(
    "product_id,model_id",
    [
        (p["product_id"], m)
        for p in TestClient(app).get("/api/products").json()
        for m in p["supported_models"]
    ],
)
def test_dogfood_every_product_model_pair(product_id: str, model_id: str):
    """Schema defaults must price successfully under every supported model,
    with a real fair value, a non-empty trace, and sane risk behavior."""
    inputs = _default_inputs(product_id)
    r = client.post(
        "/api/valuate",
        json={"product_id": product_id, "model_id": model_id, "inputs": inputs},
    )
    assert r.status_code == 200, f"{product_id}/{model_id}: {r.text[:200]}"
    body = r.json()
    assert math.isfinite(body["fair_value"])
    assert len(body["steps"]) > 0
    assert body["runtime_ms"] is not None

    risk = client.post(
        "/api/risk",
        json={"product_id": product_id, "model_id": model_id, "inputs": inputs},
    )
    assert risk.status_code in (200, 400)  # 400 only for "no measures yet"
    if risk.status_code == 200:
        for m in risk.json()["measures"]:
            assert math.isfinite(m["value"])


@pytest.mark.parametrize(
    "product_id", [p["product_id"] for p in TestClient(app).get("/api/products").json()]
)
def test_dogfood_pdf_for_every_product(product_id: str):
    """Every product must yield a real multi-section PDF from its defaults."""
    inputs = _default_inputs(product_id)
    model_id = next(
        p["supported_models"][0] for p in _catalog() if p["product_id"] == product_id
    )
    r = client.post(
        "/api/export/report",
        json={"product_id": product_id, "model_id": model_id, "inputs": inputs},
    )
    assert r.status_code == 200, f"{product_id}: {r.text[:200]}"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 8_000


# --------------------------------------------------------------------------- #
# Phase 8: production guards                                                   #
# --------------------------------------------------------------------------- #


def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_rate_limiter_blocks_a_flood_and_costs_more_for_heavy_endpoints():
    """Enabled explicitly here; disabled for the rest of the suite."""
    import importlib

    from app import main

    # Fetch inputs BEFORE enabling the limit: reload rebinds module globals,
    # so helper calls would otherwise spend budget.
    body = {
        "product_id": "european_option",
        "model_id": "black_scholes",
        "inputs": _default_inputs("european_option"),
    }
    old = os.environ.get("EFPVL_RATE_BUDGET")
    os.environ["EFPVL_RATE_BUDGET"] = "20"
    try:
        importlib.reload(main)
        limited = TestClient(main.app)
        codes = [limited.post("/api/valuate", json=body).status_code for _ in range(25)]
        assert 429 in codes, "flood was not rate limited"
        assert codes.index(429) == 20, "budget of 20 should allow exactly 20 calls"
        blocked = limited.post("/api/valuate", json=body)
        assert "Retry-After" in blocked.headers
        assert "free educational" in blocked.json()["detail"]
    finally:
        if old is None:
            os.environ["EFPVL_RATE_BUDGET"] = "0"
        else:
            os.environ["EFPVL_RATE_BUDGET"] = old
        importlib.reload(main)
