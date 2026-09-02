"""Métricas da oportunidade + ordem de ranking (spec §7-8).

- desconto %  = (ref − comc) / ref × 100   → a "margem" canônica deste scanner
- lucro US$   = ref − comc
- ROI %       = (ref − comc) / comc × 100   → retorno sobre o capital empregado

Ordem: maior ROI → maior desconto % → maior lucro absoluto → Pokémon mais
popular (rank menor na lista icônica). Só desconto % enganaria: carta de US$12
com 40% "vale" menos que uma de US$300 com 25%.
"""
from __future__ import annotations

from dataclasses import dataclass

UNRANKED = 9999  # Pokémon fora da lista icônica (só aparece com --all-pokemon)


@dataclass(frozen=True, slots=True)
class Metrics:
    discount_pct: float
    roi_pct: float
    profit_abs: float


def compute_metrics(tcg_reference: float, comc_price: float) -> Metrics:
    profit = tcg_reference - comc_price
    discount = (profit / tcg_reference * 100.0) if tcg_reference > 0 else float("-inf")
    roi = (profit / comc_price * 100.0) if comc_price > 0 else float("inf")
    return Metrics(discount_pct=round(discount, 2), roi_pct=round(roi, 2),
                   profit_abs=round(profit, 2))


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def sort_key(row: dict) -> tuple[float, float, float, int]:
    """Chave para ``sorted(...)``: menor = melhor (negativos nas métricas)."""
    try:
        rank = int(row.get("pokemon_rank") or UNRANKED)
    except (TypeError, ValueError):
        rank = UNRANKED
    return (-_f(row, "roi_pct"), -_f(row, "margin_pct"), -_f(row, "profit_abs"), rank)


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=sort_key)
