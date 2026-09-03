"""Reporting: console markdown table + JSON/CSV files (fonte ÚNICA do formato de linha).

A tabela canônica de entrega (modelo MYP, cross-scanner) tem UMA fonte: as funções
`render_rows_table`/`render_row_line` daqui. `comc_summary.py` (a ferramenta de
entrega) só reparte as linhas em baldes e reusa estas funções — nunca montar
tabela à mão.

Colunas: # | Desconto% | ROI bruto% | COMC$ | Ref$ | Spread$ | Pokémon | Carta | Set |
Tipo | Ref | Conf | Status | Links
- `Desconto%` = (ref − COMC)/ref; `Spread$` = ref − COMC (bruto, sem taxas);
  `ROI bruto%` = spread/COMC (nomenclatura do operador, 2026-09-02);
- `Carta` = nome + número de coleção ("Pikachu 173/165");
- `Tipo` = "Raw NM" / "Raw EX-NM" / "Raw LP" ou o rótulo da nota do slab ("PSA 10",
  "CGC 10 Pristine", "BGS 10 Black Label");
- `Ref` = de onde veio o preço de referência: "TCG market|mid|low" (TCGplayer via
  tcgcsv, raw NM) ou "PC vendas <nota|LP> (n=…, mês..mês)" (PriceCharting: mediana
  de vendas concluídas da mesma carta, variante, certificadora e nota — ou LP);
  JSON antigo: "PC coluna <nota> (antigo)";
- `Status` = OK ou MATCH_REVIEW + motivos (confiança < trust, slab×ref-raw,
  preço mid/low, vendas<3, coluna÷vendas, formato antigo) + notas que NÃO mudam
  o status (`baixa-liquidez(365d)`);
- `Links` = "[oferta](url COMC) · [referência](url onde conferir o preço)".

Compatibilidade de leitura: JSONs gravados antes da PR A trazem `profit_abs` (usado
como spread) e `ref_source` "pricecharting"/"pricecharting-proxy" (marcados como
antigos, nunca OK).
"""
from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path

from .config import Settings
from .models import STATUS_OK, STATUS_REVIEW, Deal
from .ranking import sort_rows

log = logging.getLogger("comc_scanner.reporter")

# Confidence at/above which a match is treated as solid; below it the row is
# MATCH_REVIEW so the operator double-checks the card↔reference pairing.
TRUST_CONFIDENCE = 0.90
# TCGplayer reference chain market -> mid -> low ("market" = real observed sale).
TRUSTED_PRICE_FIELD = "market"
# Mínimo de vendas comparáveis para a mediana valer como referência OK (1–2 = "thin").
MIN_COMPARABLE_SALES = 3
# Coluna exata do PriceCharting (informativa) mais longe que isto da mediana de vendas
# → sanidade falhou → revisar.
COLUMN_DEVIATION_MAX = 0.30

_SALES_SOURCE_PREFIX = "pricecharting-sales"   # "pricecharting-sales" | "pricecharting-sales-lp"
_LEGACY_COLUMN_SOURCE = "pricecharting"        # JSON antigo: coluna do PC como referência
_LEGACY_PROXY_SOURCE = "pricecharting-proxy"   # JSON antigo: bucket genérico / nota vizinha

_TABLE_COLS = [
    ("rank", "#"),
    ("margin_pct", "Desconto%"),
    ("roi_pct", "ROI bruto%"),
    ("comc_price", "COMC$"),
    ("tcg_reference", "Ref$"),
    ("spread_abs", "Spread$"),
    ("pokemon", "Pokémon"),
    ("card_number", "Carta"),
    ("set", "Set"),
    ("listing_type", "Tipo"),
    ("ref_label", "Ref"),
    ("confidence", "Conf"),
    ("status", "Status"),
    ("links", "Links"),
]
_MAXW = {"card_number": 34, "set": 26, "listing_type": 20, "pokemon": 14}

# Rótulos do funil (spec §13) — usados no log final e no cabeçalho da entrega.
# Ordem = ordem lógica do funil (triagem → match → referência → limiar → baldes).
FUNNEL_LABELS = [
    ("seen", "Listagens analisadas"),
    ("skip_graded_in_raw", "Ignoradas: gradada na passada raw"),
    ("skip_raw_in_slab", "Ignoradas: solta na passada de slabs"),
    ("skip_grade_unparsed", "Ignoradas: nota do slab não reconhecida"),
    ("skip_grade_out_of_scope", "Ignoradas: nota fora do escopo"),
    ("skip_condition", "Ignoradas: condição fora do permitido (WotC ≤2003 NM/EX-NM; "
                       "2004+ NM; LP só com referência LP)"),
    ("skip_language", "Ignoradas: idioma ≠ inglês"),
    ("skip_price_floor", "Ignoradas: abaixo do piso US$"),
    ("skip_price_ceiling", "Ignoradas: acima do teto US$ (--max-price)"),
    ("skip_not_iconic", "Ignoradas: Pokémon fora da lista"),
    ("match_failed", "Matches rejeitados (carta não identificada)"),
    ("skip_rarity", "Ignoradas: raridade (chase-only)"),
    ("slab_no_reference", "Slabs sem vendas comparáveis (mesma certificadora+nota+variante) "
                          "— sem referência"),
    ("slab_pc_error", "Slabs com ERRO na fonte PriceCharting (rede/bloqueio/layout)"),
    ("slab_grade_malformed", "Slabs com nota ilegível"),
    ("lp_prefilter", "Raw LP acima do pré-filtro (COMC > ref NM × (1 − desconto mín.))"),
    ("lp_no_reference", "Raw LP sem ≥3 vendas LP comparáveis — sem referência"),
    ("lp_pc_error", "Raw LP com ERRO na fonte PriceCharting"),
    ("below_discount", "Descartadas: desconto abaixo do mínimo"),
    ("pc_link_missing", "Raw aprovadas sem página no PriceCharting (link [referência] = TCGplayer)"),
    ("pc_link_error", "Raw aprovadas com ERRO na fonte PriceCharting ao buscar o link (= TCGplayer)"),
    ("ok", "Aprovadas OK (antes da dedupe)"),
    ("review", "Aprovadas MATCH_REVIEW (antes da dedupe)"),
    ("low_confidence", "Balde low-confidence (antes da dedupe)"),
    ("dedup_dropped", "Duplicadas removidas (mesma listagem vista mais de uma vez)"),
    ("listing_errors", "Listagens com erro interno (puladas)"),
    ("comc_errors", "Sets bloqueados na COMC"),
    ("comc_partial_sets", "Sets/passadas truncados (bloqueio no meio)"),
    ("sets_capped_max_english", "Sets/passadas cortados por --max-english"),
]
_KNOWN_FUNNEL_KEYS = {k for k, _ in FUNNEL_LABELS}


def funnel_lines(counts: dict) -> list[str]:
    """Linhas 'rótulo: N' do funil (só as com valor > 0, mais 'analisadas'); contadores
    sem rótulo conhecido aparecem como 'outros: k=v' (nunca somem da entrega)."""
    out = []
    for key, label in FUNNEL_LABELS:
        n = int(counts.get(key, 0) or 0)
        if n or key == "seen":
            out.append(f"{label}: {n}")
    extra = {k: v for k, v in counts.items() if k not in _KNOWN_FUNNEL_KEYS and v}
    if extra:
        out.append("outros: " + ", ".join(f"{k}={v}" for k, v in sorted(extra.items())))
    return out


def _price_field(row: dict) -> str:
    return "" if row.get("price_field") is None else str(row.get("price_field")).strip()


def _source(row: dict) -> str:
    return str(row.get("ref_source") or "tcgplayer")


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_row(row: dict, trust: float = TRUST_CONFIDENCE) -> tuple[str, list[str]]:
    """(status, motivos) de uma linha. OK só quando: confiança ≥ trust E a referência é
    (raw NM) preço 'market' real do TCGplayer, ou (slab/LP) mediana de ≥3 vendas
    comparáveis cuja coluna informativa (se houver) não destoa >30%.

    Motivos de MATCH_REVIEW:
    - `confiança<x`      — match carta↔referência abaixo do limiar do run;
    - `slab×ref-raw`     — slab com referência de carta solta (nunca OK);
    - `preço:mid|low`    — TCGplayer sem preço market (fallback, não é venda real);
    - `vendas<3(n=…)`    — mediana com 1–2 vendas ("thin"); n ausente = desconhecido, não flaga;
    - `coluna÷vendas(c)` — coluna exata do PC >30% longe da mediana de vendas;
    - `ref~proxy` / `ref=coluna(antigo)` — JSON gravado antes da PR A (formato antigo).
    Baixa liquidez (≥3 vendas só em 365 dias) NÃO entra aqui — é nota (`row_notes`).
    """
    reasons: list[str] = []
    try:
        conf = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < trust:
        reasons.append(f"confiança<{trust:.2f}")
    source = _source(row)
    field = _price_field(row)
    listing_type = str(row.get("listing_type") or "")
    if source == "tcgplayer" and listing_type and not listing_type.startswith("Raw"):
        reasons.append("slab×ref-raw")  # slab com referência de carta solta: nunca OK
    if source == "tcgplayer" and field and field != TRUSTED_PRICE_FIELD:
        reasons.append(f"preço:{field}")
    if source.startswith(_SALES_SOURCE_PREFIX):
        raw_n = row.get("ref_n_sales")
        if raw_n is not None:  # ausente = desconhecido (JSON antigo), não zero
            try:
                n = int(raw_n)
            except (TypeError, ValueError):
                n = None
            if n is not None and n < MIN_COMPARABLE_SALES:
                reasons.append(f"vendas<{MIN_COMPARABLE_SALES}(n={n})")
    col = _float_or_none(row.get("ref_column_price"))
    ref = _float_or_none(row.get("tcg_reference")) or 0.0
    if col is not None and ref > 0 and abs(col - ref) / ref > COLUMN_DEVIATION_MAX:
        reasons.append(f"coluna÷vendas({col:.2f})")
    if source == _LEGACY_PROXY_SOURCE:
        reasons.append("ref~proxy")
    elif source == _LEGACY_COLUMN_SOURCE:
        reasons.append("ref=coluna(antigo)")
    return (STATUS_REVIEW if reasons else STATUS_OK), reasons


def row_notes(row: dict) -> list[str]:
    """Notas informativas que NÃO mudam o status: `baixa-liquidez(365d)` quando a
    referência só juntou ≥3 vendas na janela de 365 dias (`ref_liquidity == "low"`)."""
    notes: list[str] = []
    if str(row.get("ref_liquidity") or "") == "low":
        notes.append("baixa-liquidez(365d)")
    return notes


def _status_cell(row: dict, trust: float = TRUST_CONFIDENCE) -> str:
    status, reasons = classify_row(row, trust=trust)
    return " · ".join([status, *reasons, *row_notes(row)])


def _ref_label(row: dict) -> str:
    """Coluna `Ref`: "PC vendas PSA 9 (n=5, 2026-03..2026-08)" / "PC vendas LP (n=4, …)"
    (mediana de vendas), "TCG market|mid|low" (TCGplayer) ou, em JSON antigo,
    "PC coluna PSA 10 (antigo)" / "PC GRADE 9.5~ (antigo)"."""
    field = _price_field(row)
    source = _source(row)
    if source.startswith(_SALES_SOURCE_PREFIX):
        return f"PC {field}".strip()
    if source == _LEGACY_PROXY_SOURCE:
        return f"PC {field}~ (antigo)"
    if source == _LEGACY_COLUMN_SOURCE:
        return f"PC coluna {field} (antigo)"
    return f"TCG {field}".strip()


def _links_cell(row: dict) -> str:
    """Coluna `Links`: "[oferta](comc_url) · [referência](ref_url|tcg_url)".

    `oferta` = listagem na COMC; `referência` = página onde conferir o preço usado
    (TCGplayer para raw NM; PriceCharting para slab/LP). Lidos do deal, nunca
    inventados; "—" se nenhum. URLs percent-encodadas (espaço/parênteses quebram o
    markdown).
    """
    from urllib.parse import quote
    parts = []
    comc_url = "" if row.get("comc_url") is None else str(row.get("comc_url"))
    ref_url = row.get("ref_url") or row.get("tcg_url")
    ref_url = "" if ref_url is None else str(ref_url)
    if comc_url:
        parts.append(f"[oferta]({quote(comc_url, safe='%/?&=:+,*')})")
    if ref_url:
        parts.append(f"[referência]({quote(ref_url, safe='%/?&=:+,*')})")
    return " · ".join(parts) if parts else "—"


def _cell(key: str, value: object) -> str:
    if key == "links":
        return "" if value is None else str(value)
    s = "" if value is None else str(value)
    w = _MAXW.get(key)
    if w and len(s) > w:
        s = s[: w - 1] + "…"
    return s.replace("|", "/")


def table_header_lines() -> list[str]:
    header = "| " + " | ".join(label for _, label in _TABLE_COLS) + " |"
    sep = "| " + " | ".join("---" for _ in _TABLE_COLS) + " |"
    return [header, sep]


def render_row_line(row: dict, rank: int, trust: float = TRUST_CONFIDENCE) -> str:
    """One canonical table line from a flat deal row (Deal.as_row() or the same
    dict re-read from the Reporter JSON/CSV). `trust` = the run's TRUST_CONFIDENCE
    (gravado no JSON) so the delivery never re-classifies with a different bar.
    JSON antigo (só `profit_abs`): o valor antigo preenche a coluna Spread$."""
    row = dict(row)
    row["rank"] = rank
    if "spread_abs" not in row and "profit_abs" in row:
        row["spread_abs"] = row["profit_abs"]
    row["status"] = _status_cell(row, trust)
    row["ref_label"] = _ref_label(row)
    row["links"] = _links_cell(row)
    return "| " + " | ".join(_cell(k, row.get(k, "")) for k, _ in _TABLE_COLS) + " |"


def render_rows_table(rows: list[dict], trust: float = TRUST_CONFIDENCE) -> str:
    lines = table_header_lines()
    lines.extend(render_row_line(row, rank, trust) for rank, row in enumerate(rows, 1))
    return "\n".join(lines)


def render_markdown(deals: list[Deal], label: str, top_n: int,
                    trust: float = TRUST_CONFIDENCE) -> str:
    title = (f"### COMC deals — {label} — top {min(len(deals), top_n)} "
             "(ROI bruto → desconto → spread)")
    if not deals:
        return title + "\n\n_(nenhum deal acima do limiar ainda)_"
    rows = sort_rows([d.as_row() for d in deals])[:top_n]
    return "\n".join([title, "", render_rows_table(rows, trust)])


class Reporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.results_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_csv(rows: list[dict], path: Path) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _write_json(payload: dict, path: Path) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def flush(self, deals: list[Deal], label: str, low_confidence: list[Deal] | None = None,
              stats: dict | None = None) -> str:
        """Write latest + timestamped CSV/JSON and print the markdown table."""
        rows = sort_rows([d.as_row() for d in deals])[: self.settings.top_n]
        rows = [{"rank": i, **r} for i, r in enumerate(rows, 1)]
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rdir = self.settings.results_dir

        self._write_csv(rows, rdir / f"comc_deals_{label}_latest.csv")
        self._write_csv(rows, rdir / f"comc_deals_{label}_{stamp}.csv")
        payload = {
            "scope": label,
            "generated_utc": stamp,
            "min_discount_percent": self.settings.min_discount_percent,
            "min_comc_price": self.settings.min_comc_price,
            "graded_allow": sorted(self.settings.graded_allow),
            "iconic_only": self.settings.iconic_only,
            "trust_confidence": self.settings.trust_confidence,
            "top_n": self.settings.top_n,
            "count": len(rows),
            "funnel": dict(stats or {}),
            "deals": rows,
            "low_confidence": sort_rows([d.as_row() for d in (low_confidence or [])]),
        }
        self._write_json(payload, rdir / f"comc_deals_{label}_latest.json")
        self._write_json(payload, rdir / f"comc_deals_{label}_{stamp}.json")

        table = render_markdown(deals, label, self.settings.top_n,
                                trust=self.settings.trust_confidence)
        print("\n" + table + "\n")
        if stats:
            print("Funil: " + " · ".join(funnel_lines(stats)) + "\n")
        return table
