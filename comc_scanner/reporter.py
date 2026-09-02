"""Reporting: console markdown table + JSON/CSV files (fonte ÚNICA do formato de linha).

A tabela canônica de entrega (modelo MYP, cross-scanner) tem UMA fonte: as funções
`render_rows_table`/`render_row_line` daqui. `comc_summary.py` (a ferramenta de
entrega) só reparte as linhas em baldes e reusa estas funções — nunca montar
tabela à mão.

Colunas: # | Desconto% | ROI% | COMC$ | Ref$ | Lucro$ | Pokémon | Carta | Set |
Tipo | Ref | Conf | Status | Links
- `Carta` = nome + número de coleção ("Pikachu 173/165");
- `Tipo` = "Raw NM" ou a nota do slab ("PSA 10", "CGC 10 Pristine");
- `Ref` = de onde veio o preço de referência: "TCG market|mid|low" (TCGplayer via
  tcgcsv) ou "PC PSA 10" (PriceCharting por nota; "~" = proxy de nota vizinha);
- `Status` = OK ou MATCH_REVIEW + motivos (confiança <0.90, preço mid/low, proxy);
- `Links` = "[oferta](url COMC) · [referência](url onde conferir o preço)".
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

_TABLE_COLS = [
    ("rank", "#"),
    ("margin_pct", "Desconto%"),
    ("roi_pct", "ROI%"),
    ("comc_price", "COMC$"),
    ("tcg_reference", "Ref$"),
    ("profit_abs", "Lucro$"),
    ("pokemon", "Pokémon"),
    ("card_number", "Carta"),
    ("set", "Set"),
    ("listing_type", "Tipo"),
    ("ref_label", "Ref"),
    ("confidence", "Conf"),
    ("status", "Status"),
    ("links", "Links"),
]
_MAXW = {"card_number": 34, "set": 26, "listing_type": 16, "pokemon": 14}

# Rótulos do funil (spec §13) — usados no log final e no cabeçalho da entrega.
FUNNEL_LABELS = [
    ("seen", "Listagens analisadas"),
    ("skip_graded_in_raw", "Ignoradas: gradada na passada raw"),
    ("skip_raw_in_slab", "Ignoradas: solta na passada de slabs"),
    ("skip_grade_unparsed", "Ignoradas: nota do slab não reconhecida"),
    ("skip_grade_out_of_scope", "Ignoradas: nota fora do escopo"),
    ("skip_condition", "Ignoradas: condição ≠ NM"),
    ("skip_language", "Ignoradas: idioma ≠ inglês"),
    ("skip_price_floor", "Ignoradas: abaixo do piso US$"),
    ("skip_not_iconic", "Ignoradas: Pokémon fora da lista"),
    ("match_failed", "Matches rejeitados (carta não identificada)"),
    ("skip_rarity", "Ignoradas: raridade (chase-only)"),
    ("slab_no_reference", "Slabs sem referência PriceCharting"),
    ("below_discount", "Descartadas: desconto abaixo do mínimo"),
    ("ok", "Oportunidades OK"),
    ("review", "Revisão manual (MATCH_REVIEW)"),
    ("low_confidence", "Balde low-confidence"),
    ("comc_errors", "Erros COMC"),
]


def funnel_lines(counts: dict) -> list[str]:
    """Linhas 'rótulo: N' do funil (só as com valor > 0, mais 'analisadas')."""
    out = []
    for key, label in FUNNEL_LABELS:
        n = int(counts.get(key, 0) or 0)
        if n or key == "seen":
            out.append(f"{label}: {n}")
    return out


def classify_row(row: dict, trust: float = TRUST_CONFIDENCE) -> tuple[str, list[str]]:
    """(status, motivos) de uma linha. OK só quando: confiança ≥ trust E referência
    é preço 'market' real (raw) ou coluna exata da nota (slab, sem proxy)."""
    reasons: list[str] = []
    try:
        conf = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < trust:
        reasons.append(f"confiança<{trust:.2f}")
    source = str(row.get("ref_source") or "tcgplayer")
    field = "" if row.get("price_field") is None else str(row.get("price_field")).strip()
    if source == "tcgplayer" and field and field != TRUSTED_PRICE_FIELD:
        reasons.append(f"preço:{field}")
    if source == "pricecharting-proxy":
        reasons.append(f"ref~proxy:{field}")
    return (STATUS_REVIEW if reasons else STATUS_OK), reasons


def _status_cell(row: dict) -> str:
    status, reasons = classify_row(row)
    return " · ".join([status, *reasons])


def _ref_label(row: dict) -> str:
    field = "" if row.get("price_field") is None else str(row.get("price_field")).strip()
    source = str(row.get("ref_source") or "tcgplayer")
    if source.startswith("pricecharting"):
        return f"PC {field}" + ("~" if source.endswith("proxy") else "")
    return f"TCG {field}".strip()


def _links_cell(row: dict) -> str:
    """Coluna `Links`: "[oferta](comc_url) · [referência](ref_url|tcg_url)".

    `oferta` = listagem na COMC; `referência` = página onde conferir o preço usado
    (TCGplayer para raw; PriceCharting para slab). Lidos do deal, nunca inventados;
    "—" se nenhum. URLs percent-encodadas (espaço/parênteses quebram o markdown).
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


def render_row_line(row: dict, rank: int) -> str:
    """One canonical table line from a flat deal row (Deal.as_row() or the same
    dict re-read from the Reporter JSON/CSV)."""
    row = dict(row)
    row["rank"] = rank
    row["status"] = _status_cell(row)
    row["ref_label"] = _ref_label(row)
    row["links"] = _links_cell(row)
    return "| " + " | ".join(_cell(k, row.get(k, "")) for k, _ in _TABLE_COLS) + " |"


def render_rows_table(rows: list[dict]) -> str:
    lines = table_header_lines()
    lines.extend(render_row_line(row, rank) for rank, row in enumerate(rows, 1))
    return "\n".join(lines)


def render_markdown(deals: list[Deal], label: str, top_n: int) -> str:
    title = f"### COMC deals — {label} — top {min(len(deals), top_n)} (ROI → desconto → lucro)"
    if not deals:
        return title + "\n\n_(nenhum deal acima do limiar ainda)_"
    rows = sort_rows([d.as_row() for d in deals])[:top_n]
    return "\n".join([title, "", render_rows_table(rows)])


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
            "top_n": self.settings.top_n,
            "count": len(rows),
            "funnel": dict(stats or {}),
            "deals": rows,
            "low_confidence": sort_rows([d.as_row() for d in (low_confidence or [])]),
        }
        self._write_json(payload, rdir / f"comc_deals_{label}_latest.json")
        self._write_json(payload, rdir / f"comc_deals_{label}_{stamp}.json")

        table = render_markdown(deals, label, self.settings.top_n)
        print("\n" + table + "\n")
        if stats:
            print("Funil: " + " · ".join(funnel_lines(stats)) + "\n")
        return table
