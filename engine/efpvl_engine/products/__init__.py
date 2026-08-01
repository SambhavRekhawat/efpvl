"""Concrete products. Importing this package registers them all."""

from efpvl_engine.products.coupon_bond import CouponBond
from efpvl_engine.products.credit_default_swap import CreditDefaultSwap
from efpvl_engine.products.currency_and_inflation import (
    CurrencySwap,
    InflationLinkedBond,
)
from efpvl_engine.products.european_option import EuropeanOption
from efpvl_engine.products.forward_rate_agreement import ForwardRateAgreement
from efpvl_engine.products.fx_and_commodity import CommodityFutures, FXForward
from efpvl_engine.products.rates_swaps import FloatingRateNote, InterestRateSwap
from efpvl_engine.products.zero_coupon_bond import ZeroCouponBond

__all__ = [
    "CommodityFutures",
    "CouponBond",
    "CreditDefaultSwap",
    "CurrencySwap",
    "EuropeanOption",
    "FXForward",
    "FloatingRateNote",
    "ForwardRateAgreement",
    "InflationLinkedBond",
    "InterestRateSwap",
    "ZeroCouponBond",
]
