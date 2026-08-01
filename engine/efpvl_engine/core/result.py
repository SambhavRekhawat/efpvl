"""Valuation result contract.

The defining feature of EFPVL is that a valuation is never just a number.
Every :class:`PricingModel` must return a :class:`ValuationResult` that carries:

* the fair value,
* every intermediate calculation as an ordered trace of :class:`CalculationStep`,
* named outputs (clean price, YTM, Greeks, ...),
* an explanation payload keyed to authored content.

The API serializes this object verbatim; the frontend renders the trace as the
"Calculation Trace" card. Designing this now (Phase 0) is what makes the lab
explainable by construction rather than by afterthought.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class CalculationStep:
    """A single intermediate step in a pricing calculation.

    Examples: one discount factor, one cash-flow PV, the Black-Scholes ``d1``.

    Attributes:
        label: Human-readable name shown in the UI, e.g. ``"Discount factor DF(2y)"``.
        symbol: Mathematical symbol as LaTeX (rendered client-side), e.g. ``"d_1"``.
        value: The computed numeric value.
        formula: LaTeX for the formula applied at this step.
        inputs: The named inputs that fed this step, for traceability.
        note: Optional one-line teaching note ("why this step matters").
    """

    label: str
    value: float
    symbol: str | None = None
    formula: str | None = None
    inputs: dict[str, float] = field(default_factory=dict)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "symbol": self.symbol,
            "formula": self.formula,
            "inputs": self.inputs,
            "note": self.note,
        }


@dataclass
class ValuationResult:
    """The full, explainable output of pricing one product with one model.

    Attributes:
        fair_value: The headline valuation.
        currency: ISO currency code of the fair value.
        product_id: Registry id of the product that was priced.
        model_id: Registry id of the model that produced this result.
        outputs: Named auxiliary outputs (e.g. ``{"clean_price": ..., "ytm": ...}``).
        steps: Ordered calculation trace. Models append steps as they compute.
        explanation_key: Key into the authored explainability content for this
            model/product pairing (content system lands in Phase 4).
        warnings: Non-fatal caveats, e.g. "yield solver hit iteration cap".
        runtime_ms: Wall-clock pricing time; surfaces on the Model Comparison page.
        as_of: Valuation timestamp (UTC).
    """

    fair_value: float
    currency: str
    product_id: str
    model_id: str
    outputs: dict[str, float] = field(default_factory=dict)
    steps: list[CalculationStep] = field(default_factory=list)
    explanation_key: str | None = None
    warnings: list[str] = field(default_factory=list)
    runtime_ms: float | None = None
    as_of: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_step(self, step: CalculationStep) -> None:
        """Append one intermediate step to the trace (order is preserved)."""
        self.steps.append(step)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation consumed by the API layer."""
        return {
            "fair_value": self.fair_value,
            "currency": self.currency,
            "product_id": self.product_id,
            "model_id": self.model_id,
            "outputs": self.outputs,
            "steps": [s.to_dict() for s in self.steps],
            "explanation_key": self.explanation_key,
            "warnings": self.warnings,
            "runtime_ms": self.runtime_ms,
            "as_of": self.as_of.isoformat(),
        }
