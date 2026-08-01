"""Core abstractions: Product, PricingModel, MarketData, and the registries.

Architecture rule (enforced by convention and CI):
    engine  ->  knows nothing about HTTP, FastAPI, or the frontend.
    api     ->  imports the engine, never the reverse.

Every concrete product lives in ``efpvl_engine/products/`` and every concrete
model in ``efpvl_engine/models/``. Both self-register via the decorators below,
so adding a product is: write one module, register it, ship its schema and
tests. No changes to the API or frontend are required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from .result import ValuationResult
from .schema import InputField, ProductMeta, ValidationError, validate_inputs


class MarketData(ABC):
    """Container for market state used in pricing.

    Phase 0 defines the interface only; Phase 1 adds the concrete
    ``MarketSnapshot`` backed by curated JSON snapshots (yield curve, vol,
    FX, spreads) with a visible "as of" timestamp and provenance labels
    (user input vs market input vs derived input).
    """

    @abstractmethod
    def discount_factor(self, t_years: float) -> float:
        """Risk-free discount factor for a cash flow ``t_years`` from valuation."""

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Serializable description of the snapshot for the Market Data page."""


class Product(ABC):
    """A financial product: contract terms + declared input schema.

    Subclasses are pure data + domain logic (cash-flow schedules, payoff
    definitions). They never price themselves — pricing belongs to models —
    but they may expose helpers models need (e.g. ``cashflows()``).
    """

    #: Unique registry id, e.g. ``"zero_coupon_bond"``. Set by subclasses.
    product_id: str

    @classmethod
    @abstractmethod
    def meta(cls) -> ProductMeta:
        """Display metadata for the Product Selection page."""

    @classmethod
    @abstractmethod
    def input_schema(cls) -> tuple[InputField, ...]:
        """Declared inputs; served at ``GET /products/{id}/schema``."""

    @classmethod
    def validate(cls, inputs: dict[str, Any]) -> list[ValidationError]:
        """Validate raw inputs against the declared schema."""
        return validate_inputs(cls.input_schema(), inputs)

    @classmethod
    @abstractmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> Product:
        """Construct a product instance from validated raw inputs."""


class PricingModel(ABC):
    """A valuation methodology (DCF, Black-Scholes, binomial tree, ...).

    Contract:
      * ``supports(product)`` gates the Model Comparison page.
      * ``price`` must populate the :class:`ValuationResult` step trace —
        a model that returns only a number is considered broken in this
        codebase, and tests will assert ``len(result.steps) > 0``.
    """

    #: Unique registry id, e.g. ``"black_scholes"``. Set by subclasses.
    model_id: str
    display_name: str = ""

    @classmethod
    @abstractmethod
    def supports(cls, product: Product) -> bool:
        """Whether this model can price the given product."""

    @abstractmethod
    def price(self, product: Product, market: MarketData) -> ValuationResult:
        """Value the product, recording every intermediate step."""

    def risk_measures(self, product: Product, market: MarketData) -> dict[str, float]:
        """Sensitivity measures for this product under this model.

        Keys are stable identifiers ("delta", "modified_duration", ...) that
        the API pairs with authored risk content. Models that support risk
        override this; the default signals no support.
        """
        raise NotImplementedError(
            f"{self.model_id} does not provide risk measures for {product.product_id}"
        )

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Model metadata for ``GET /models/{id}``.

        Serves the authored explainability JSON when it exists (the normal
        case — CI enforces its presence for every registered model); the
        stub below is a resilience fallback only, so a corrupt file degrades
        instead of erroring.
        """
        from efpvl_engine.content import model_content

        try:
            authored = model_content(cls.model_id)
        except (OSError, ValueError):
            authored = None
        if authored is not None:
            return authored
        return {
            "model_id": cls.model_id,
            "display_name": cls.display_name,
            "overview": "",
            "assumptions": [],
            "limitations": [],
            "typical_usage": "",
            "computational_complexity": "",
        }


# --------------------------------------------------------------------------- #
# Registries — the plug-in mechanism.                                          #
# --------------------------------------------------------------------------- #

_PRODUCTS: dict[str, type[Product]] = {}
_MODELS: dict[str, type[PricingModel]] = {}


def register_product[P: type[Product]](cls: P) -> P:
    """Class decorator: adds a Product subclass to the global registry."""
    pid = getattr(cls, "product_id", None)
    if not pid:
        raise ValueError(f"{cls.__name__} must define a non-empty product_id")
    if pid in _PRODUCTS:
        raise ValueError(f"Duplicate product_id: {pid!r}")
    _PRODUCTS[pid] = cls
    return cls


def register_model[M: type[PricingModel]](cls: M) -> M:
    """Class decorator: adds a PricingModel subclass to the global registry."""
    mid = getattr(cls, "model_id", None)
    if not mid:
        raise ValueError(f"{cls.__name__} must define a non-empty model_id")
    if mid in _MODELS:
        raise ValueError(f"Duplicate model_id: {mid!r}")
    _MODELS[mid] = cls
    return cls


def get_product(product_id: str) -> type[Product]:
    try:
        return _PRODUCTS[product_id]
    except KeyError:
        raise KeyError(f"Unknown product: {product_id!r}") from None


def get_model(model_id: str) -> type[PricingModel]:
    try:
        return _MODELS[model_id]
    except KeyError:
        raise KeyError(f"Unknown model: {model_id!r}") from None


def list_products() -> list[type[Product]]:
    return list(_PRODUCTS.values())


def list_models() -> list[type[PricingModel]]:
    return list(_MODELS.values())


def models_for(product: Product) -> list[type[PricingModel]]:
    """All registered models that can price the given product."""
    return [m for m in _MODELS.values() if m.supports(product)]


def clear_registries() -> None:
    """Test helper — never call from application code."""
    _PRODUCTS.clear()
    _MODELS.clear()


RegistryDecorator = Callable[[type], type]
