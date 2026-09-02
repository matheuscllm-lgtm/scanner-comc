"""Modo `--iconic`: faixa de desconto 30-40% com DUAS referências.

Pedido do operador (2026-09-02): scanner COMC só de cartas de personagens
icônicos, com preço 30-40% abaixo da referência do PriceCharting e do
TCGplayer. Como as compras ficam ARMAZENADAS na conta COMC do operador, não
há frete nem taxa por compra — a margem é BRUTA pura, exatamente a fórmula
default do repo: `(referência − preço COMC) / referência` = "X% abaixo da
referência".

Regras (travadas em tests/test_iconic.py):
- **Margem que classifica = a mais CONSERVADORA** entre a margem vs TCGplayer
  (market do tcgcsv) e a margem vs PriceCharting (mediana de vendas reais).
  Se qualquer referência disser que o desconto é menor, vale a menor — nunca a
  mais otimista. Sem PriceCharting (falha/sem match) vale só a TCG, e a linha
  ganha a flag `sem PC` (vai pra "validar", nunca pra 🟢 limpa).
- **Faixa** `[min, max]` (default 0.30–0.40): `faixa` = dentro; `acima` = mais
  de 40% abaixo (na frota, desconto grande demais é o sinal clássico de
  variante/condição errada ou anúncio-lixo — vai pra 🚨 REVISAR, nunca 🟢);
  `abaixo` = a referência conservadora rebaixou pra menos de 30% (mostrada,
  contrato "todas as linhas").
- **Divergência** entre as duas referências > 40% → flag `PC diverge`
  (uma das fontes está furada; conferir a versão nos dois links).
- Nunca inventa preço; nunca recomenda compra.
"""
from __future__ import annotations

import logging

from .config import Settings
from .margin import get_margin_fn
from .models import Deal

log = logging.getLogger("comc_scanner.iconic")

# |ref_tcg − ref_pc| / max(...) acima disto = referências discordam demais.
PC_DIVERGENCE_RATIO = 0.40


# --- classificação (funções puras sobre a linha plana do JSON) --------------

def _num(value) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def band_margin(row: dict) -> float | None:
    """Margem (fração) que classifica: min(margem TCG, margem PC); só TCG se
    não houver PC. None se nem a TCG existir."""
    m_tcg = _num(row.get("margin_pct"))
    m_pc = _num(row.get("pc_margin_pct"))
    if m_tcg is None:
        return None
    m = m_tcg if m_pc is None else min(m_tcg, m_pc)
    return m / 100.0


def band_of(row: dict, lo: float, hi: float | None) -> str:
    """'faixa' | 'acima' | 'abaixo' | 'sem_margem'."""
    m = band_margin(row)
    if m is None:
        return "sem_margem"
    if m < lo:
        return "abaixo"
    if hi is not None and m > hi:
        return "acima"
    return "faixa"


def pc_diverges(row: dict, ratio: float = PC_DIVERGENCE_RATIO) -> bool:
    ref_tcg, ref_pc = _num(row.get("tcg_reference")), _num(row.get("pc_reference"))
    if not ref_tcg or not ref_pc:
        return False
    return abs(ref_tcg - ref_pc) / max(ref_tcg, ref_pc) > ratio


def iconic_flags(row: dict) -> list[str]:
    """Flags extras do modo icônico (além de `validar`/`preço:<campo>`)."""
    flags = []
    if _num(row.get("pc_reference")) is None:
        flags.append("sem PC")
    elif pc_diverges(row):
        flags.append("PC diverge")
    return flags


# --- enriquecimento com PriceCharting ---------------------------------------

class PriceChartingEnricher:
    """Preenche `pc_reference`/`pc_margin`/`pc_url` nos deals (cache por produto
    + variante em memória; o módulo pricecharting já cacheia as páginas 24h em
    disco). Falha → campos ficam None (flag `sem PC`)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[tuple[int, str], dict | None] = {}
        self._margin_fn = get_margin_fn(settings.margin_mode)

    def lookup(self, deal: Deal) -> dict | None:
        key = (deal.product.product_id, deal.sub_type_used or "")
        if key not in self._cache:
            from .pricecharting import resolve_pc_ref  # lazy: rede só quando usado

            self._cache[key] = resolve_pc_ref(
                deal.product.name, deal.product.number, deal.product.set_name,
                sub_type=deal.sub_type_used,
            )
        return self._cache[key]

    def enrich(self, deals: list[Deal]) -> None:
        if not self.settings.pricecharting_enabled:
            return
        for deal in deals:
            if deal.pc_reference is not None:
                continue
            ref = self.lookup(deal)
            if not ref:
                continue
            deal.pc_reference = float(ref["median"])
            deal.pc_n_sales = int(ref.get("n_sales") or 0)
            deal.pc_url = str(ref.get("url") or "")
            deal.pc_margin = self._margin_fn(deal.pc_reference, deal.listing.price)
        n_ok = sum(1 for d in deals if d.pc_reference is not None)
        log.info("PriceCharting: %d/%d deals com referência de vendas reais.", n_ok, len(deals))
