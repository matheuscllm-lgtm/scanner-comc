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

from comc_scanner.iconic import band_of, iconic_flags
from comc_scanner.reporter import (
    TRUST_CONFIDENCE,
    TRUSTED_PRICE_FIELD,
    render_iconic_rows_table,
    render_rows_table,
)

CLEAN_TITLE = f"## 🟢 Deals (confiança ≥{TRUST_CONFIDENCE:.2f}, preço market)"
REVIEW_TITLE = "## ⚠️ Validar manualmente (confiança baixa ou preço mid/low)"

# Modo --iconic (faixa 30-40% com duas referências — comc_scanner/iconic.py)
ICONIC_CLEAN_TITLE = "## 🟢 Na faixa (limpos: confiança alta, preço market, PC confirma)"
ICONIC_REVIEW_TITLE = "## ⚠️ Na faixa — validar manualmente (confiança baixa, preço mid/low, sem PC ou PC diverge)"
ICONIC_ABOVE_TITLE = "## 🚨 Acima da faixa (desconto maior que o teto — conferir variante/condição/anúncio)"
ICONIC_BELOW_TITLE = "## ❌ Abaixo da faixa (a referência conservadora rebaixou pra menos que o mínimo)"


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


def _section(title: str, rows: list[dict], iconic: bool = False) -> list[str]:
    lines = [title, ""]
    if rows:
        lines.append(render_iconic_rows_table(rows) if iconic else render_rows_table(rows))
    else:
        lines.append("_(nenhuma linha neste balde)_")
    lines.append("")
    return lines


def _band_margin_sort(row: dict) -> float:
    from comc_scanner.iconic import band_margin

    return band_margin(row) or 0.0


def split_iconic_buckets(payload: dict) -> dict[str, list[dict]]:
    """Modo icônico: 4 baldes, TODAS as linhas (nenhuma escondida).

    - clean : na faixa E confiança ≥ gate E preço market E PC presente sem
              divergência (os únicos 🟢);
    - review: na faixa, mas com qualquer flag (validar / preço mid-low / sem PC /
              PC diverge) — inclui o balde low_confidence do Reporter;
    - above : margem conservadora ACIMA do teto (desconto grande demais);
    - below : margem conservadora ABAIXO do mínimo (a TCG dizia ≥ mínimo, o PC
              rebaixou) — mostrada por honestidade.
    Ordenação: margem conservadora desc."""
    lo = float(payload.get("min_gross_margin") or 0.30)
    hi = payload.get("max_gross_margin")
    hi = None if hi in (None, "") else float(hi)
    buckets: dict[str, list[dict]] = {"clean": [], "review": [], "above": [], "below": []}
    for row in list(payload.get("deals") or []) + list(payload.get("low_confidence") or []):
        band = band_of(row, lo, hi)
        if band == "acima":
            buckets["above"].append(row)
        elif band in ("abaixo", "sem_margem"):
            buckets["below"].append(row)
        elif (_confidence(row) >= TRUST_CONFIDENCE
              and _price_field(row) == TRUSTED_PRICE_FIELD and not iconic_flags(row)):
            buckets["clean"].append(row)
        else:
            buckets["review"].append(row)
    for rows in buckets.values():
        rows.sort(key=_band_margin_sort, reverse=True)
    return buckets


def pc_coverage_line(rows: list[dict]) -> str:
    """Honestidade da 2ª referência: quantas linhas têm mediana de vendas reais
    do PriceCharting vs. ficaram só com a TCG ("sem PC")."""
    with_pc = sum(1 for r in rows if r.get("pc_reference") not in (None, ""))
    diverge = sum(1 for r in rows if "PC diverge" in iconic_flags(r))
    return (f"Cobertura PriceCharting: {with_pc}/{len(rows)} com mediana de vendas reais · "
            f"{len(rows) - with_pc} sem PC · {diverge} PC diverge (>40% vs TCG)")


def build_iconic_markdown(payload: dict, group: int | None = None) -> str:
    b = split_iconic_buckets(payload)
    all_rows = b["clean"] + b["review"] + b["above"] + b["below"]
    era = payload.get("era", "?")
    grupo = f"grupo {group}" if group else "grupo —"
    lo = payload.get("min_gross_margin", "?")
    hi = payload.get("max_gross_margin")
    faixa = f"{lo}–{hi}" if hi not in (None, "") else f"≥{lo} (sem teto)"
    header = [
        "# COMC → TCGplayer + PriceCharting — ICÔNICOS — entrega do scan",
        "",
        f"- Snapshot: {payload.get('generated_utc', '?')} (UTC) · era: {era} · {grupo}",
        f"- Faixa de desconto (fração): {faixa} · margem que classifica = a mais "
        "CONSERVADORA entre TCGplayer (market tcgcsv) e PriceCharting (mediana de 10 "
        "vendas reais ungraded)",
        f"- Na faixa: {len(b['clean'])} limpos · {len(b['review'])} validar · "
        f"acima da faixa: {len(b['above'])} · abaixo: {len(b['below'])}",
        f"- {price_coverage_line(all_rows)}",
        f"- {pc_coverage_line(all_rows)}",
        "- Escopo: só Pokémon da lista icônica (notorious.py) · NM-only · EN-only · "
        "piso US$10 · margem BRUTA (compra fica na conta COMC: sem frete/taxa embutida)",
    ]
    warning = _top_n_warning(payload)
    if warning:
        header.append(warning)
    header.append("")
    body = (_section(ICONIC_CLEAN_TITLE, b["clean"], iconic=True)
            + _section(ICONIC_REVIEW_TITLE, b["review"], iconic=True)
            + _section(ICONIC_ABOVE_TITLE, b["above"], iconic=True)
            + _section(ICONIC_BELOW_TITLE, b["below"], iconic=True))
    footer = [
        "_Marg TCG% = desconto vs market TCGplayer; Marg PC% = desconto vs mediana de "
        "vendas reais do PriceCharting (— = sem match/sem vendas, nunca inventado). "
        "`sem PC` / `PC diverge` / `validar` / `preço:<campo>` pedem conferência nos "
        "links antes de qualquer decisão. Acima da faixa = desconto maior que o teto, "
        "sinal clássico de variante/condição errada. O scanner reporta dados; não é "
        "recomendação de compra._",
        "",
    ]
    return "\n".join(header + body + footer)


def _top_n_warning(payload: dict) -> str | None:
    """Disclosure do corte ``top_n``: o Reporter corta a lista de deals em
    ``top_n`` ANTES de gravar o JSON — se a lista gravada está CHEIA no teto,
    pode haver mais deals acima do threshold que sumiram silenciosamente.
    Avisar é obrigatório (contrato "todas as linhas"); fingir lista completa
    seria a mesma desonestidade do fallback-como-real."""
    top_n = payload.get("top_n")
    count = payload.get("count")
    if isinstance(top_n, int) and isinstance(count, int) and 0 < top_n <= count:
        return (f"- ⚠️ Lista cheia no teto top_n={top_n} — pode haver mais deals acima "
                "do threshold que foram cortados; re-rode o scan com --top-n maior.")
    return None


def build_markdown(payload: dict, group: int | None = None) -> str:
    if payload.get("mode") == "iconic":
        return build_iconic_markdown(payload, group=group)
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
    ]
    warning = _top_n_warning(payload)
    if warning:
        header.append(warning)
    header.append("")
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
    ap.add_argument("json_path", help="JSON do Reporter (results/comc_deals_<era>_latest.json "
                                      "ou results/comc_iconic_<era>_latest.json)")
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
