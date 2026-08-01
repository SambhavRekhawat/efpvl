"""Pydantic schemas for the EFPVL API.

Requests are strict (unknown fields rejected) so typos fail loudly instead
of being silently ignored. Server-side caps on the sensitivity sweep are the
compute-abuse guard promised in the roadmap: once public, nobody can ask the
engine for a million repricings in one call.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_SWEEP_POINTS = 200


class ValuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    product_id: str = Field(..., examples=["coupon_bond"])
    model_id: str = Field(..., examples=["discounted_cash_flow"])
    inputs: dict[str, Any] = Field(
        ..., description="Raw form inputs, validated against the product schema."
    )


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    product_id: str
    model_ids: list[str] = Field(..., min_length=2, max_length=4)
    inputs: dict[str, Any]


class SweepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(..., description="Product input to sweep, e.g. 'volatility'.")
    min_value: float
    max_value: float
    points: int = Field(
        50,
        ge=2,
        le=MAX_SWEEP_POINTS,
        description=f"Number of grid points (server cap: {MAX_SWEEP_POINTS}).",
    )


class SensitivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    product_id: str
    model_id: str
    inputs: dict[str, Any]
    sweep: SweepSpec


class FieldError(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
    errors: list[FieldError] = []
