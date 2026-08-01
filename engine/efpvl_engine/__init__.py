"""EFPVL pricing engine — a pure Python valuation library.

This package contains no web code. The FastAPI layer in ``api/`` wraps it.
"""

# Importing the packages below registers all concrete products and models.
from efpvl_engine import models as _models  # noqa: F401,E402
from efpvl_engine import products as _products  # noqa: F401,E402
from efpvl_engine.core.base import (
    MarketData,
    PricingModel,
    Product,
    get_model,
    get_product,
    list_models,
    list_products,
    models_for,
    register_model,
    register_product,
)
from efpvl_engine.core.result import CalculationStep, ValuationResult
from efpvl_engine.core.schema import FieldType, InputField, ProductMeta
from efpvl_engine.market.curve import ZeroCurve, load_snapshot
from efpvl_engine.market.daycount import DayCount, year_fraction
from efpvl_engine.market.market_snapshot import MarketSnapshot

__version__ = "0.3.0"

__all__ = [
    "DayCount",
    "MarketSnapshot",
    "ZeroCurve",
    "load_snapshot",
    "year_fraction",
    "CalculationStep",
    "FieldType",
    "InputField",
    "MarketData",
    "PricingModel",
    "Product",
    "ProductMeta",
    "ValuationResult",
    "get_model",
    "get_product",
    "list_models",
    "list_products",
    "models_for",
    "register_model",
    "register_product",
]
