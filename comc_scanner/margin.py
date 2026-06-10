"""Margin formulas, isolated so the policy is a one-line switch.

Default is gross margin = (tcg_reference - comc_price) / tcg_reference, matching the
"margem bruta > 20%" requirement. `markup` and a fee-aware variant are provided for
when fees/shipping should be modelled later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def gross_margin(tcg_reference: float, comc_price: float) -> float:
    if tcg_reference <= 0:
        return float("-inf")
    return (tcg_reference - comc_price) / tcg_reference


def markup(tcg_reference: float, comc_price: float) -> float:
    if comc_price <= 0:
        return float("inf")
    return (tcg_reference - comc_price) / comc_price


@dataclass(slots=True)
class FeeModel:
    """Future-proofing: model marketplace fees/shipping to get net margin."""
    sale_fee_pct: float = 0.0
    flat_fee: float = 0.0

    def net_proceeds(self, tcg_reference: float) -> float:
        return tcg_reference * (1.0 - self.sale_fee_pct) - self.flat_fee

    def net_margin(self, tcg_reference: float, comc_price: float) -> float:
        proceeds = self.net_proceeds(tcg_reference)
        if proceeds <= 0:
            return float("-inf")
        return (proceeds - comc_price) / proceeds


def get_margin_fn(mode: str) -> Callable[[float, float], float]:
    return markup if (mode or "gross").lower() == "markup" else gross_margin
