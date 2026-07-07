#!/usr/bin/env python
"""comc_summary.py — ferramenta de ENTREGA canônica do scanner COMC.

Espelho do ``myp_summary.py`` do MYP scanner: lê o JSON gravado pelo Reporter
(``results/comc_deals_<era>_latest.json``) e gera o markdown de entrega que o
agente cola VERBATIM no chat — nunca montar tabela à mão.

Uso:
    python comc_summary.py results/comc_deals_recent_latest.json \
        -o results/comc-grupo1-2026-07-06.md [--group 1]

O formato da tabela tem UMA fonte de verdade: ``comc_scanner/reporter.py``
(``render_rows_table``/``render_row_line``) — este script só divide as linhas em
duas seções (deals confiáveis vs. validar manualmente), soma a cobertura de
preço (market/mid/low) e escreve o cabeçalho. Todas as linhas aparecem (nenhum
balde é escondido); links vêm das colunas ``comc_url``/``tcg_url`` do JSON,
nunca inventados. Sem recomendação de compra — a decisão de capital é do
operador.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from comc_scanner.reporter import (
    TRUST_CONFIDENCE,
    TRUSTED_PRICE_FIELD,
    render_rows_table,
)

CLEAN_TITLE = f"## 🟢 Deals (confiança ≥{TRUST_CONFIDENCE:.2f}, preço market)"
REVIEW_TITLE = "## ⚠️ Validar manualmente (confiança baixa ou preço mid/low)"


def _confidence(row: dict) -> float:
    try:
        return float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _price_field(row: dict) -> str:
    value = row.get("price_field")
    return "" if value is None else str(value).strip()


def _margin(row: dict) -> float:
    try:
        return float(row.get("margin_pct") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def split_buckets(payload: dict) -> tuple[list[dict], list[dict], int]:
    """(clean, review, n_low_confidence): clean = confiança ≥ gate E preço market;
    todo o resto (fallback mid/low, confiança baixa, balde low_confidence do
    Reporter) vai para "validar" — nunca é dropado. Ambos ordenados por margem
    desc."""
    deals = list(payload.get("deals") or [])
    low_conf = list(payload.get("low_confidence") or [])
    clean: list[dict] = []
    review: list[dict] = []
    for row in deals:
        if _confidence(row) >= TRUST_CONFIDENCE and _price_field(row) == TRUSTED_PRICE_FIELD:
            clean.append(row)
        else:
            review.append(row)
    review.extend(low_conf)
    clean.sort(key=_margin, reverse=True)
    review.sort(key=_margin, reverse=True)
    return clean, review, len(low_conf)


def price_coverage_line(rows: list[dict]) -> str:
    """Linha de honestidade de preço: quantas linhas têm preço market REAL vs.
    fallback mid/low (o fallback nunca é apresentado como real)."""
    counts = Counter(_price_field(row) or "desconhecido" for row in rows)
    parts = [f"{counts.pop(field, 0)} {field}" for field in ("market", "mid", "low")]
    parts.extend(f"{n} {field}" for field, n in sorted(counts.items()))
    return "Cobertura de preço market: " + " · ".join(parts)


def _section(title: str, rows: list[dict]) -> list[str]:
    lines = [title, ""]
    if rows:
        lines.append(render_rows_table(rows))
    else:
        lines.append("_(nenhuma linha neste balde)_")
    lines.append("")
    return lines


def build_markdown(payload: dict, group: int | None = None) -> str:
    clean, review, n_low = split_buckets(payload)
    all_rows = clean + review
    era = payload.get("era", "?")
    grupo = f"grupo {group}" if group else "grupo —"
    header = [
        "# COMC → TCGplayer — entrega do scan",
        "",
        f"- Snapshot: {payload.get('generated_utc', '?')} (UTC) · era: {era} · {grupo}",
        f"- Deals ok: {len(clean)} · validar: {len(review)} "
        f"(sendo {n_low} do balde low-confidence)",
        f"- {price_coverage_line(all_rows)}",
        f"- Limiar de margem bruta: {payload.get('min_gross_margin', '?')} (fração) · "
        "piso US$10 · NM-only · EN-only",
        "",
    ]
    body = _section(CLEAN_TITLE, clean) + _section(REVIEW_TITLE, review)
    footer = [
        "_Linhas `validar` = confiança de match < "
        f"{TRUST_CONFIDENCE:.2f} e/ou preço de referência mid/low (fallback, não é "
        "venda real) — conferir manualmente antes de qualquer decisão. O scanner "
        "reporta dados; não é recomendação de compra._",
        "",
    ]
    return "\n".join(header + body + footer)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json_path", help="JSON do Reporter (results/comc_deals_<era>_latest.json)")
    ap.add_argument("-o", "--output", required=True,
                    help="arquivo .md de saída (obrigatório), ex.: results/comc-grupo1-<data>.md")
    ap.add_argument("--group", type=int, choices=(1, 2, 3, 4),
                    help="número do grupo escaneado (só rótulo do cabeçalho)")
    args = ap.parse_args(argv)

    # utf-8-sig: tolerate a BOM (Windows editors/PS 5.1 add one; the fleet's
    # recorded BOM bugs say "never trust the file to be BOM-free"). Decodes
    # plain UTF-8 identically.
    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8-sig"))
    md = build_markdown(payload, group=args.group)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):  # Windows console: emoji precisam de UTF-8
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass
    print(md)
    print(f"[comc_summary] markdown gravado em {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
