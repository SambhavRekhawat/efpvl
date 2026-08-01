"""Input schema primitives.

Every product declares its inputs as :class:`InputField` objects. The API
exposes them at ``GET /products/{id}/schema`` and the frontend builds its
input panels from that response — validation ranges, units, tooltips,
defaults and all.

This is the mechanism that keeps "adding a new product requires minimal
changes" true: a new product ships its own schema, and the form renders
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FieldType(StrEnum):
    NUMBER = "number"
    PERCENT = "percent"  # rendered with % affordance; engine works in decimals
    DATE = "date"
    SELECT = "select"
    CURRENCY = "currency"


@dataclass(frozen=True)
class InputField:
    """One user-supplied input to a product.

    Attributes:
        name: Machine name, snake_case (``coupon_rate``).
        label: Display label (``Coupon Rate``).
        field_type: Rendering/validation type.
        unit: Display unit, e.g. ``"%"``, ``"years"``, ``"USD"``.
        default: Sensible example value pre-filled in the UI.
        min_value / max_value: Server-enforced acceptable range. These bounds
            are a hard contract — the API rejects out-of-range values, which
            doubles as compute-abuse protection once the lab is public.
        step: Suggested UI increment.
        choices: For SELECT fields, the allowed options.
        tooltip: Short hover help.
        description: Longer teaching description shown in expandable help.
        required: Whether the field must be provided.
    """

    name: str
    label: str
    field_type: FieldType
    unit: str | None = None
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    choices: tuple[str, ...] | None = None
    tooltip: str | None = None
    description: str | None = None
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.field_type.value,
            "unit": self.unit,
            "default": self.default,
            "min": self.min_value,
            "max": self.max_value,
            "step": self.step,
            "choices": list(self.choices) if self.choices else None,
            "tooltip": self.tooltip,
            "description": self.description,
            "required": self.required,
        }


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str


def validate_inputs(
    fields: tuple[InputField, ...], inputs: dict[str, Any]
) -> list[ValidationError]:
    """Validate raw inputs against a product's declared schema.

    Returns a (possibly empty) list of errors; the API converts them into a
    422 response with per-field messages the frontend can display inline.
    """
    errors: list[ValidationError] = []
    known = {f.name for f in fields}

    for f in fields:
        if f.name not in inputs or inputs[f.name] is None:
            # Defaults are UI pre-fill hints only. The API is explicit: a
            # required field must be sent, so valuations are reproducible
            # from the request payload alone.
            if f.required:
                errors.append(ValidationError(f.name, f"{f.label} is required."))
            continue
        value = inputs[f.name]
        if f.field_type in (FieldType.NUMBER, FieldType.PERCENT):
            try:
                value = float(value)
            except (TypeError, ValueError):
                errors.append(ValidationError(f.name, f"{f.label} must be a number."))
                continue
            if f.min_value is not None and value < f.min_value:
                errors.append(
                    ValidationError(f.name, f"{f.label} must be ≥ {f.min_value}.")
                )
            if f.max_value is not None and value > f.max_value:
                errors.append(
                    ValidationError(f.name, f"{f.label} must be ≤ {f.max_value}.")
                )
        elif f.field_type == FieldType.SELECT and f.choices:
            if value not in f.choices:
                errors.append(
                    ValidationError(
                        f.name, f"{f.label} must be one of: {', '.join(f.choices)}."
                    )
                )

    for name in inputs:
        if name not in known:
            errors.append(ValidationError(name, "Unknown input field."))

    return errors


@dataclass(frozen=True)
class ProductMeta:
    """Descriptive metadata shown on the Product Selection page."""

    product_id: str
    display_name: str
    asset_class: str  # "Rates" | "Credit" | "Equity" | "FX" | "Commodity" | ...
    summary: str
    supported_models: tuple[str, ...] = field(default_factory=tuple)
