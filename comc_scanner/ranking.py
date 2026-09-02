"""Métricas da oportunidade + ordem de ranking (spec §7-8).

Nomenclatura do operador (2026-09-02) — três métricas, nomeadas assim e só assim:
- desconto %   = (ref − comc) / ref × 100   → a "margem" canônica deste scanner
- spread bruto US$ = ref − comc             → diferença bruta, sem taxa nenhuma
- ROI bruto %  = (ref − comc) / comc × 100  → retorno bruto sobre o capital empregado

Ordem: maior ROI bruto → maior desconto % → maior spread bruto → Pokémon mais
popular (rank menor na lista icônica). Só desconto % enganaria: carta de US$12
com 40% "vale" menos que uma de US$300 com 25%.

Compatibilidade: JSONs gravados antes da PR A trazem `profit_abs` em vez de
`spread_abs`; o ranking lê o campo antigo como spread quando o novo não existe.
"""
from __future__ import annotations

from dataclasses import dataclass

UNRANKED = 9999  # Pokémon fora da lista icônica (só aparece com --all-pokemon)


@dataclass(frozen=True, slots=True)
class Metrics:
    discount_pct: float
    roi_pct: float
    spread_abs: float


def compute_metrics(tcg_reference: float, comc_price: float) -> Metrics:
    spread = tcg_reference - comc_price
    discount = (spread / tcg_reference * 100.0) if tcg_reference > 0 else float("-inf")
    roi = (spread / comc_price * 100.0) if comc_price > 0 else float("inf")
    return Metrics(discount_pct=round(discount, 2), roi_pct=round(roi, 2),
                   spread_abs=round(spread, 2))


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def spread_of(row: dict) -> float:
    """Spread bruto da linha: `spread_abs`; JSON antigo só tem `profit_abs` → usa-o."""
    return _f(row, "spread_abs") if "spread_abs" in row else _f(row, "profit_abs")


def sort_key(row: dict) -> tuple[float, float, float, int]:
    """Chave para ``sorted(...)``: menor = melhor (negativos nas métricas)."""
    try:
        rank = int(row.get("pokemon_rank") or UNRANKED)
    except (TypeError, ValueError):
        rank = UNRANKED
    return (-_f(row, "roi_pct"), -_f(row, "margin_pct"), -spread_of(row), rank)


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=sort_key)
