#!/usr/bin/env python
"""comc_summary.py — ferramenta de ENTREGA canônica do scanner COMC.

Espelho do ``myp_summary.py`` do MYP scanner: lê o JSON gravado pelo Reporter
(``results/comc_deals_<escopo>_latest.json``) e gera o markdown de entrega que o
agente cola VERBATIM no chat — nunca montar tabela à mão.

Uso:
    python comc_summary.py results/comc_deals_grupo1_latest.json \
        -o results/comc-grupo1-2026-09-02.md [--group 1]

O formato da tabela tem UMA fonte de verdade: ``comc_scanner/reporter.py``
(``render_rows_table``/``render_row_line``). Este script só divide as linhas em
duas seções — 🟢 OK vs ⚠️ MATCH_REVIEW (validar manualmente) —, ambas na ordem
do ranking (ROI → desconto → lucro → popularidade do Pokémon), e escreve o
cabeçalho com o funil do scan. Todas as linhas aparecem; links vêm das colunas
``comc_url``/``ref_url`` do JSON. Sem recomendação de compra.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from comc_scanner.models import STATUS_OK
from comc_scanner.ranking import sort_rows
from comc_scanner.reporter import TRUST_CONFIDENCE, classify_row, funnel_lines, render_rows_table

CLEAN_TITLE = "## 🟢 Oportunidades OK (match confiável + preço de referência real)"
REVIEW_TITLE = "## ⚠️ MATCH_REVIEW — validar manualmente (confiança baixa, preço mid/low ou proxy)"


def split_buckets(payload: dict) -> tuple[list[dict], list[dict], int]:
    """(ok, review, n_low_confidence): OK = status OK pela mesma regra do reporter;
    todo o resto (MATCH_REVIEW + balde low_confidence) vai para revisão — nunca é
    dropado. Ambos na ordem do ranking."""
    deals = list(payload.get("deals") or [])
    low_conf = list(payload.get("low_confidence") or [])
    ok: list[dict] = []
    review: list[dict] = []
    for row in deals:
        status, _ = classify_row(row)
        (ok if status == STATUS_OK else review).append(row)
    review.extend(low_conf)
    return sort_rows(ok), sort_rows(review), len(low_conf)


def _section(title: str, rows: list[dict]) -> list[str]:
    lines = [title, ""]
    lines.append(render_rows_table(rows) if rows else "_(nenhuma linha neste balde)_")
    lines.append("")
    return lines


def _top_n_warning(payload: dict) -> str | None:
    top_n = payload.get("top_n")
    count = payload.get("count")
    if isinstance(top_n, int) and isinstance(count, int) and 0 < top_n <= count:
        return (f"- ⚠️ Lista cheia no teto top_n={top_n} — pode haver mais deals acima "
                "do threshold que foram cortados; re-rode o scan com --top-n maior.")
    return None


def build_markdown(payload: dict, group: int | None = None) -> str:
    ok, review, n_low = split_buckets(payload)
    scope = payload.get("scope") or payload.get("era", "?")
    grupo = f"grupo {group}" if group else f"escopo {scope}"
    graded = payload.get("graded_allow") or []
    header = [
        "# COMC → referência (TCGplayer raw · PriceCharting slabs) — entrega do scan",
        "",
        f"- Snapshot: {payload.get('generated_utc', '?')} (UTC) · {grupo}",
        f"- OK: {len(ok)} · MATCH_REVIEW: {len(review)} (sendo {n_low} do balde low-confidence)",
        f"- Desconto mínimo: {payload.get('min_discount_percent', '?')}% · piso US$"
        f"{payload.get('min_comc_price', '?')} · raw só NM · só inglês · "
        f"Pokémon: {'lista icônica' if payload.get('iconic_only', True) else 'todos'}",
        f"- Slabs aceitos: {', '.join(graded) if graded else '—'}",
    ]
    funnel = payload.get("funnel") or {}
    if funnel:
        header.append("- Funil: " + " · ".join(funnel_lines(funnel)))
    warning = _top_n_warning(payload)
    if warning:
        header.append(warning)
    header.append("")
    body = _section(CLEAN_TITLE, ok) + _section(REVIEW_TITLE, review)
    footer = [
        f"_MATCH_REVIEW = confiança de match < {TRUST_CONFIDENCE:.2f}, preço de referência "
        "mid/low (fallback, não é venda real) ou nota de slab sem coluna exata no "
        "PriceCharting (proxy) — conferir manualmente antes de qualquer decisão. "
        "Ranking: ROI → desconto % → lucro US$ → popularidade do Pokémon. "
        "O scanner reporta dados; não é recomendação de compra._",
        "",
    ]
    return "\n".join(header + body + footer)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json_path", help="JSON do Reporter (results/comc_deals_<escopo>_latest.json)")
    ap.add_argument("-o", "--output", required=True,
                    help="arquivo .md de saída (obrigatório), ex.: results/comc-grupo1-<data>.md")
    ap.add_argument("--group", type=int, choices=(1, 2, 3, 4),
                    help="número do grupo escaneado (só rótulo do cabeçalho)")
    args = ap.parse_args(argv)

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
