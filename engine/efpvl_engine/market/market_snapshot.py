"""Concrete MarketData backed by a curated, versioned snapshot.

Every market variable carries a *provenance* label so the Market Data page
can honestly distinguish:

* ``market``  — taken from the curated snapshot (yield curve, ATM vol, FX...),
* ``user``    — supplied by the user in the product form,
* ``derived`` — computed by the engine (forward rates, discount factors...).
"""

from __future__ import annotations

from typing import Any

from efpvl_engine.core.base import MarketData
from efpvl_engine.market.curve import ZeroCurve, load_snapshot


class MarketSnapshot(MarketData):
    """Market state assembled from a snapshot plus optional user overrides."""

    def __init__(
        self,
        snapshot: dict[str, Any] | None = None,
        overrides: dict[str, float] | None = None,
    ) -> None:
        self.snapshot = snapshot if snapshot is not None else load_snapshot()
        self.curve = ZeroCurve.from_snapshot(self.snapshot)
        self.overrides = dict(overrides or {})

    # -- MarketData interface ------------------------------------------- #

    def discount_factor(self, t_years: float) -> float:
        return self.curve.discount_factor(t_years)

    def describe(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot.get("snapshot_id"),
            "as_of": self.snapshot.get("as_of"),
            "note": self.snapshot.get("description"),
            "curve": self.curve.describe(),
            "overrides": self.overrides,
        }

    # -- Named lookups with provenance ---------------------------------- #

    def value(self, key: str) -> tuple[float, str]:
        """Return ``(value, provenance)`` for a named market variable.

        User overrides win over snapshot values; provenance reflects that.
        """
        if key in self.overrides:
            return float(self.overrides[key]), "user"
        if key == "risk_free_rate":
            return float(self.snapshot["risk_free_rate"]), "market"
        if key == "dividend_yield":
            return float(self.snapshot["equity"]["dividend_yield"]), "market"
        if key == "implied_vol_atm":
            return float(self.snapshot["equity"]["implied_vol_atm"]), "market"
        raise KeyError(f"Unknown market variable: {key!r}")
