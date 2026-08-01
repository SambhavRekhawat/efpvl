"""EFPVL API routes.

The waiter's full vocabulary:

    GET  /products              What's on the menu?
    GET  /products/{id}/schema  What does this dish need? (drives the UI form)
    GET  /models                All cooking methods, with metadata
    GET  /models/{id}           One cooking method in detail
    GET  /market-data           Today's curated market snapshot, with provenance
    POST /valuate               Cook it — returns the full explainable result
    POST /sensitivity           Cook it many times along one axis (for charts)
    POST /risk                  Risk measures paired with authored explanations
    POST /compare               Same product, several models, side by side
    POST /export/report         Professional PDF valuation report
    GET  /explain/risk          The full risk-measure glossary

Error contract:
    404 unknown product/model · 400 model can't price product or bad economics
    422 per-field validation errors the frontend can render inline
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import efpvl_engine as engine
import numpy as np
from efpvl_engine.content import risk_content
from efpvl_engine.market.market_snapshot import MarketSnapshot
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .schemas import CompareRequest, SensitivityRequest, ValuationRequest

router = APIRouter()

# One snapshot per process: static curated data, cheap to share.
_MARKET = MarketSnapshot()

# ---- Response cache ------------------------------------------------------- #
# Every model in the laboratory is deterministic (Monte Carlo is seeded), so
# identical requests yield identical results — caching them makes repeated
# slider positions and re-Calculates instant. Bounded FIFO, per process.
_CACHE_MAX = 512
_RESPONSE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _cache_key(kind: str, *parts: Any) -> str:
    return (
        kind + "|" + "|".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    )


def _cache_get(key: str) -> dict[str, Any] | None:
    hit = _RESPONSE_CACHE.get(key)
    if hit is not None:
        _RESPONSE_CACHE.move_to_end(key)
        return {**hit, "cached": True}
    return None


def _cache_put(key: str, value: dict[str, Any]) -> dict[str, Any]:
    _RESPONSE_CACHE[key] = value
    if len(_RESPONSE_CACHE) > _CACHE_MAX:
        _RESPONSE_CACHE.popitem(last=False)
    return {**value, "cached": False}


# --------------------------------------------------------------------------- #
# Catalog                                                                      #
# --------------------------------------------------------------------------- #


@router.get("/products")
def list_products() -> list[dict[str, Any]]:
    out = []
    for cls in engine.list_products():
        m = cls.meta()
        out.append(
            {
                "product_id": m.product_id,
                "display_name": m.display_name,
                "asset_class": m.asset_class,
                "summary": m.summary,
                "supported_models": list(m.supported_models),
            }
        )
    return sorted(out, key=lambda p: (p["asset_class"], p["display_name"]))


@router.get("/products/{product_id}/schema")
def product_schema(product_id: str) -> dict[str, Any]:
    cls = _get_product_cls(product_id)
    m = cls.meta()
    return {
        "product_id": m.product_id,
        "display_name": m.display_name,
        "supported_models": list(m.supported_models),
        "fields": [f.to_dict() for f in cls.input_schema()],
    }


@router.get("/models")
def list_models() -> list[dict[str, Any]]:
    return [cls.describe() for cls in engine.list_models()]


@router.get("/models/{model_id}")
def model_detail(model_id: str) -> dict[str, Any]:
    return _get_model_cls(model_id).describe()


@router.get("/market-data")
def market_data() -> dict[str, Any]:
    """The curated snapshot plus provenance guidance for the Market Data page."""
    snap = _MARKET.snapshot
    return {
        "provenance_legend": {
            "market": "Taken from the curated snapshot below.",
            "user": "Supplied by you in the product form (overrides market).",
            "derived": "Computed by the engine (discount factors, forwards...).",
        },
        "snapshot": snap,
        "curve": _MARKET.curve.describe(),
    }


# --------------------------------------------------------------------------- #
# Pricing                                                                      #
# --------------------------------------------------------------------------- #


@router.post("/valuate")
def valuate(req: ValuationRequest) -> dict[str, Any]:
    key = _cache_key("valuate", req.product_id, req.model_id, req.inputs)
    if (hit := _cache_get(key)) is not None:
        return hit
    product, model = _build(req.product_id, req.model_id, req.inputs)
    try:
        result = model.price(product, _MARKET)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=f"Pricing failed: {exc}") from exc
    return _cache_put(key, result.to_dict())


@router.post("/sensitivity")
def sensitivity(req: SensitivityRequest) -> dict[str, Any]:
    """Reprice along a grid over one input field — the data behind every chart."""
    cls = _get_product_cls(req.product_id)
    field_names = {f.name for f in cls.input_schema()}
    if req.sweep.field not in field_names:
        raise HTTPException(
            status_code=400,
            detail=f"'{req.sweep.field}' is not an input of {req.product_id}.",
        )
    if req.sweep.max_value <= req.sweep.min_value:
        raise HTTPException(status_code=400, detail="sweep max must exceed min.")

    key = _cache_key(
        "sweep", req.product_id, req.model_id, req.inputs, req.sweep.model_dump()
    )
    if (hit := _cache_get(key)) is not None:
        return hit

    # Validate the base inputs once, with the swept field pinned to the grid
    # start so an intentionally-omitted swept field doesn't fail validation.
    base = dict(req.inputs)
    base[req.sweep.field] = req.sweep.min_value
    _validate_or_422(cls, base)
    model = _instantiate_supported_model(req.model_id, cls, base)

    grid = np.linspace(req.sweep.min_value, req.sweep.max_value, req.sweep.points)
    points: list[dict[str, Any]] = []
    for x in grid:
        candidate = dict(base)
        candidate[req.sweep.field] = float(x)
        try:
            product = cls.from_inputs(candidate)
            res = model.price(product, _MARKET)
            points.append(
                {"x": float(x), "fair_value": res.fair_value, "outputs": res.outputs}
            )
        except (ValueError, ZeroDivisionError, OverflowError):
            points.append({"x": float(x), "fair_value": None, "outputs": {}})

    return _cache_put(
        key,
        {
            "product_id": req.product_id,
            "model_id": req.model_id,
            "swept_field": req.sweep.field,
            "points": points,
        },
    )


@router.post("/risk")
def risk(req: ValuationRequest) -> dict[str, Any]:
    """Risk measures for a product/model pair, joined with authored content."""
    product, model = _build(req.product_id, req.model_id, req.inputs)
    try:
        measures = model.risk_measures(product, _MARKET)
    except NotImplementedError:
        raise HTTPException(
            status_code=400,
            detail=f"Model {req.model_id!r} has no risk measures for "
            f"{req.product_id!r} yet.",
        ) from None
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=f"Risk failed: {exc}") from exc

    glossary = risk_content()
    return {
        "product_id": req.product_id,
        "model_id": req.model_id,
        "measures": [
            {"key": k, "value": v, **glossary.get(k, {})} for k, v in measures.items()
        ],
    }


@router.get("/explain/risk")
def explain_risk() -> dict[str, Any]:
    """The complete authored risk-measure glossary."""
    return risk_content()


@router.post("/compare")
def compare(req: CompareRequest) -> dict[str, Any]:
    """Run several models on one product; report values, runtimes, and gaps."""
    cls = _get_product_cls(req.product_id)
    _validate_or_422(cls, req.inputs)
    product = _from_inputs_or_400(cls, req.inputs)

    results: list[dict[str, Any]] = []
    for model_id in req.model_ids:
        model_cls = _get_model_cls(model_id)
        if not model_cls.supports(product):
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_id!r} cannot price {req.product_id!r}.",
            )
        try:
            res = model_cls().price(product, _MARKET)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise HTTPException(
                status_code=400, detail=f"{model_id} failed: {exc}"
            ) from exc
        described = model_cls.describe()
        results.append(
            {
                "model_id": model_id,
                "display_name": described.get("display_name", model_id),
                "fair_value": res.fair_value,
                "runtime_ms": res.runtime_ms,
                "outputs": res.outputs,
                "warnings": res.warnings,
                "comparison_note": described.get("comparison_note"),
                "assumptions": described.get("assumptions", [])[:4],
                "limitations": described.get("limitations", [])[:4],
            }
        )

    baseline = results[0]["fair_value"]
    for r in results:
        r["diff_vs_baseline"] = r["fair_value"] - baseline
        r["diff_bps"] = (
            1e4 * (r["fair_value"] - baseline) / abs(baseline) if baseline else None
        )
    return {
        "product_id": req.product_id,
        "baseline_model_id": req.model_ids[0],
        "results": results,
    }


@router.post("/export/report")
def export_report(req: ValuationRequest) -> Response:
    """Generate the professional PDF valuation report."""
    from .reports import build_report

    product, model = _build(req.product_id, req.model_id, req.inputs)
    try:
        result = model.price(product, _MARKET).to_dict()
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=f"Pricing failed: {exc}") from exc
    try:
        risk_measures = model.risk_measures(product, _MARKET)
    except (NotImplementedError, ValueError):
        risk_measures = None

    pdf = build_report(
        req.product_id, req.model_id, req.inputs, result, risk_measures, _MARKET
    )
    filename = f"efpvl_{req.product_id}_{req.model_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _get_product_cls(product_id: str):
    try:
        return engine.get_product(product_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Unknown product: {product_id!r}"
        ) from None


def _get_model_cls(model_id: str):
    try:
        return engine.get_model(model_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Unknown model: {model_id!r}"
        ) from None


def _validate_or_422(cls, inputs: dict[str, Any]) -> None:
    errors = cls.validate(inputs)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Input validation failed.",
                "errors": [{"field": e.field, "message": e.message} for e in errors],
            },
        )


def _instantiate_supported_model(model_id: str, product_cls, sample_inputs):
    model_cls = _get_model_cls(model_id)
    probe = _from_inputs_or_400(product_cls, sample_inputs)
    if not model_cls.supports(probe):
        raise HTTPException(
            status_code=400,
            detail=f"Model {model_id!r} cannot price {product_cls.product_id!r}.",
        )
    return model_cls()


def _from_inputs_or_400(cls, inputs: dict[str, Any]):
    try:
        return cls.from_inputs(inputs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid product terms: {exc}"
        ) from exc


def _build(product_id: str, model_id: str, inputs: dict[str, Any]):
    cls = _get_product_cls(product_id)
    _validate_or_422(cls, inputs)
    product = _from_inputs_or_400(cls, inputs)
    model_cls = _get_model_cls(model_id)
    if not model_cls.supports(product):
        raise HTTPException(
            status_code=400,
            detail=f"Model {model_id!r} cannot price {product_id!r}.",
        )
    return product, model_cls()
