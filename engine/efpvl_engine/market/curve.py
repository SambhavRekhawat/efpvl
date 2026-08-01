"""Zero curve — the "price list for money".

A :class:`ZeroCurve` stores continuously compounded zero rates at pillar
tenors and interpolates **log-linearly on discount factors** (equivalent to
piecewise-linear forward rates), the most common simple market scheme.

Extrapolation is flat in the zero rate on both ends, and DF(0) = 1 exactly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class ZeroCurve:
    """Continuously compounded zero curve with log-linear DF interpolation."""

    def __init__(
        self,
        tenors_years: list[float],
        zero_rates: list[float],
        currency: str = "USD",
        name: str = "zero_curve",
    ) -> None:
        if len(tenors_years) != len(zero_rates):
            raise ValueError("tenors and rates must have equal length")
        if len(tenors_years) < 1:
            raise ValueError("curve needs at least one pillar")
        if any(t <= 0 for t in tenors_years):
            raise ValueError("pillar tenors must be positive")
        if sorted(tenors_years) != list(tenors_years):
            raise ValueError("pillar tenors must be strictly increasing")

        self.tenors = list(map(float, tenors_years))
        self.rates = list(map(float, zero_rates))
        self.currency = currency
        self.name = name
        # Precompute log discount factors at pillars: ln DF(t) = -z(t) * t
        self._log_dfs = [-z * t for z, t in zip(self.rates, self.tenors, strict=True)]

    # ------------------------------------------------------------------ #

    def discount_factor(self, t_years: float) -> float:
        """DF(t): present value today of 1 unit paid at time ``t``."""
        if t_years < 0:
            raise ValueError("cannot discount a past cash flow (t < 0)")
        if t_years == 0:
            return 1.0
        t0, tn = self.tenors[0], self.tenors[-1]
        if t_years <= t0:
            return math.exp(-self.rates[0] * t_years)  # flat-rate extrapolation
        if t_years >= tn:
            return math.exp(-self.rates[-1] * t_years)
        # Log-linear interpolation between bracketing pillars
        i = self._bracket(t_years)
        tl, tr = self.tenors[i], self.tenors[i + 1]
        ll, lr = self._log_dfs[i], self._log_dfs[i + 1]
        w = (t_years - tl) / (tr - tl)
        return math.exp(ll + w * (lr - ll))

    def zero_rate(self, t_years: float) -> float:
        """Continuously compounded zero rate implied by DF(t)."""
        if t_years <= 0:
            return self.rates[0]
        return -math.log(self.discount_factor(t_years)) / t_years

    def forward_rate(self, t1: float, t2: float) -> float:
        """Continuously compounded forward rate between ``t1`` and ``t2``."""
        if t2 <= t1:
            raise ValueError("t2 must exceed t1")
        df1, df2 = self.discount_factor(t1), self.discount_factor(t2)
        return math.log(df1 / df2) / (t2 - t1)

    # ------------------------------------------------------------------ #

    def _bracket(self, t: float) -> int:
        lo, hi = 0, len(self.tenors) - 2
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.tenors[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "currency": self.currency,
            "compounding": "continuous",
            "interpolation": "log-linear on discount factors",
            "pillars": [
                {"tenor_years": t, "zero_rate": z}
                for t, z in zip(self.tenors, self.rates, strict=True)
            ],
        }

    # ------------------------------------------------------------------ #

    @classmethod
    def flat(cls, rate: float, currency: str = "USD") -> ZeroCurve:
        """Single-pillar flat curve — invaluable for tests and teaching."""
        return cls([1.0], [rate], currency=currency, name=f"flat@{rate:.4f}")

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> ZeroCurve:
        yc = snapshot["yield_curve"]
        return cls(
            yc["tenors_years"],
            yc["zero_rates"],
            currency=snapshot.get("currency", "USD"),
            name=snapshot.get("snapshot_id", "snapshot_curve"),
        )


def load_snapshot(path: str | Path | None = None) -> dict[str, Any]:
    """Load a curated market snapshot JSON (defaults to the USD baseline)."""
    if path is None:
        path = Path(__file__).parent / "snapshots" / "usd_baseline.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)
