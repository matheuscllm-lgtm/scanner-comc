"""Fórmula de desconto/margem, isolada para a política ser uma linha só.

desconto = (referência − preço_COMC) / referência  (fração; 0.25 = 25%)
Comparado com ``Settings.min_gross_margin`` (= MIN_DISCOUNT_PERCENT / 100).
Sem taxas embutidas: frete/câmbio/IOF o operador calcula por fora. ROI e lucro
absoluto derivados vivem em ``ranking.compute_metrics``.
"""
from __future__ import annotations


def gross_margin(tcg_reference: float, comc_price: float) -> float:
    if tcg_reference <= 0:
        return float("-inf")
    return (tcg_reference - comc_price) / tcg_reference
