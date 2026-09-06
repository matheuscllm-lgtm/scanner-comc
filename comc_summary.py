#!/usr/bin/env python
"""comc_summary.py — ferramenta de ENTREGA canônica do scanner COMC.

Espelho do ``myp_summary.py`` do MYP scanner: lê o JSON gravado pelo Reporter
(``results/comc_deals_<escopo>_latest.json``) e gera o markdown de entrega que o
agente cola VERBATIM no chat — nunca montar tabela à mão.

Uso:
    python comc_summary.py results/comc_deals_grupo1_latest.json \
        -o results/comc-grupo1-2026-09-02.md [--group 1] [--sensitivity 10,15,20]

O formato da tabela tem UMA fonte de verdade: ``comc_scanner/reporter.py``
(``render_rows_table``/``render_row_line``). Este script só divide as linhas em
baldes — 🟢 OK vs ⚠️ MATCH_REVIEW (validar manualmente) —, ambos na ordem do
ranking (ROI bruto → desconto → spread → popularidade do Pokémon), e escreve o
cabeçalho com o funil do scan. Todas as linhas aparecem; links vêm das colunas
``comc_url``/``ref_url`` do JSON. Sem recomendação de compra.

``--sensitivity 10,15,20`` (modo diagnóstico): o MAIOR limiar é o operacional
(faixa ≥20% = candidato comercial OK / MATCH_REVIEW); as faixas abaixo
(15–19,99%, 10–14,99%) são só diagnóstico — NÃO são oportunidade — e saem com
TODAS as linhas da faixa, status na coluna, mais uma tabela de contagens por
limiar. Faixa = coluna Desconto% (``margin_pct``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from comc_scanner import groups
from comc_scanner.models import STATUS_OK
from comc_scanner.ranking import sort_rows
from comc_scanner.reporter import TRUST_CONFIDENCE, classify_row, funnel_lines, render_rows_table

CLEAN_TITLE = "## 🟢 Oportunidades OK (match confiável + preço de referência real)"
REVIEW_TITLE = ("## ⚠️ MATCH_REVIEW — validar manualmente (confiança baixa, preço mid/low, "
                "vendas<3 ou coluna÷vendas)")
EMPTY_BUCKET = "_(nenhuma linha neste balde)_"


def _trust(payload: dict) -> float:
    """Limiar de confiança DO RUN (gravado no JSON pelo Reporter). A entrega usa o
    mesmo limiar que o scan usou — nunca o default do módulo — para um deal
    classificado MATCH_REVIEW no scan jamais virar OK na tabela."""
    try:
        return float(payload.get("trust_confidence") or TRUST_CONFIDENCE)
    except (TypeError, ValueError):
        return TRUST_CONFIDENCE


def split_buckets(payload: dict) -> tuple[list[dict], list[dict], int]:
    """(ok, review, n_low_confidence): OK = status OK pela mesma regra do reporter
    (com o `trust_confidence` do run); todo o resto (MATCH_REVIEW + balde
    low_confidence) vai para revisão — nunca é dropado. Ambos na ordem do ranking."""
    trust = _trust(payload)
    deals = list(payload.get("deals") or [])
    low_conf = list(payload.get("low_confidence") or [])
    ok: list[dict] = []
    review: list[dict] = []
    for row in deals:
        status, _ = classify_row(row, trust=trust)
        (ok if status == STATUS_OK else review).append(row)
    review.extend(low_conf)
    return sort_rows(ok), sort_rows(review), len(low_conf)


def _section(title: str, rows: list[dict], trust: float) -> list[str]:
    lines = [title, ""]
    lines.append(render_rows_table(rows, trust) if rows else EMPTY_BUCKET)
    lines.append("")
    return lines


def _top_n_warning(payload: dict) -> str | None:
    top_n = payload.get("top_n")
    count = payload.get("count")
    if isinstance(top_n, int) and isinstance(count, int) and 0 < top_n <= count:
        return (f"- ⚠️ Lista cheia no teto top_n={top_n} — pode haver mais deals acima "
                "do threshold que foram cortados; re-rode o scan com --top-n maior.")
    return None


# ── modo diagnóstico --sensitivity ──────────────────────────────────────────────

def parse_sensitivity(text: str) -> list[int]:
    """"10,15,20" → [10, 15, 20]: inteiros positivos, estritamente crescentes (o maior é
    o limiar operacional). Qualquer outra coisa é erro de argumento."""
    try:
        vals = [int(p.strip()) for p in str(text).split(",") if p.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--sensitivity espera inteiros separados por vírgula, ex. 10,15,20 (recebi {text!r})"
        ) from exc
    if not vals or any(v <= 0 for v in vals) or any(b <= a for a, b in zip(vals, vals[1:])):
        raise argparse.ArgumentTypeError(
            f"--sensitivity espera inteiros positivos em ordem crescente, ex. 10,15,20 "
            f"(recebi {text!r})")
    return vals


def _discount(row: dict) -> float:
    try:
        return float(row.get("margin_pct") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct_br(value: float) -> str:
    """19.99 → "19,99"; 20 → "20" (vírgula decimal, sem zeros à toa)."""
    txt = f"{value:.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",")


def sensitivity_bands(thresholds: list[int]) -> list[tuple[int, int | None]]:
    """[10, 15, 20] → [(20, None), (15, 20), (10, 15)]: faixas [lo, hi) da maior para a
    menor; a primeira (hi=None) é a operacional."""
    asc = sorted(thresholds)
    bands: list[tuple[int, int | None]] = [(asc[-1], None)]
    for lo, hi in zip(reversed(asc[:-1]), reversed(asc[1:])):
        bands.append((lo, hi))
    return bands


def _in_band(row: dict, lo: int, hi: int | None) -> bool:
    d = _discount(row)
    return d >= lo and (hi is None or d < hi)


def sensitivity_counts(ok: list[dict], review: list[dict], thresholds: list[int]) -> list[str]:
    """Tabela `| Limiar | OK | MATCH_REVIEW | Total |` acumulada (≥20, ≥15, ≥10)."""
    lines = ["| Limiar | OK | MATCH_REVIEW | Total |", "| --- | --- | --- | --- |"]
    for t in sorted(thresholds, reverse=True):
        n_ok = sum(1 for r in ok if _discount(r) >= t)
        n_rev = sum(1 for r in review if _discount(r) >= t)
        lines.append(f"| ≥{t}% | {n_ok} | {n_rev} | {n_ok + n_rev} |")
    return lines


def sensitivity_sections(ok: list[dict], review: list[dict], thresholds: list[int],
                         trust: float) -> list[str]:
    """Seções do modo diagnóstico: faixa operacional em 2 baldes (OK / MATCH_REVIEW) e
    cada faixa diagnóstica com TODAS as suas linhas (OK e MATCH_REVIEW juntas, status
    na coluna), sempre via `render_rows_table` — nunca tabela à mão."""
    lines: list[str] = []
    for lo, hi in sensitivity_bands(thresholds):
        if hi is None:
            lines += _section(f"## 🟢 ≥{lo}% — candidato comercial (sujeito às demais validações)",
                              [r for r in ok if _in_band(r, lo, hi)], trust)
            lines += _section(f"## ⚠️ ≥{lo}% — MATCH_REVIEW",
                              [r for r in review if _in_band(r, lo, hi)], trust)
        else:
            rows = sort_rows([r for r in ok + review if _in_band(r, lo, hi)])
            lines += _section(f"## 🔬 Diagnóstico {lo}–{_pct_br(hi - 0.01)}% — NÃO é oportunidade",
                              rows, trust)
    return lines


def build_markdown(payload: dict, group: int | None = None,
                   sensitivity: list[int] | None = None) -> str:
    ok, review, n_low = split_buckets(payload)
    scope = payload.get("scope") or payload.get("era", "?")
    grupo = f"grupo {group}" if group else f"escopo {scope}"
    graded = payload.get("graded_allow") or []
    min_discount = payload.get("min_discount_percent", "?")
    header = [
        "# COMC → referência (TCGplayer raw · PriceCharting slabs/LP) — entrega do scan",
        "",
        f"- Snapshot: {payload.get('generated_utc', '?')} (UTC) · {grupo}",
        f"- OK: {len(ok)} · MATCH_REVIEW: {len(review)} (sendo {n_low} do balde low-confidence)"
        + (" — todas as faixas; contagem por limiar abaixo" if sensitivity else ""),
        f"- Desconto mínimo: {min_discount}% · piso US$"
        f"{payload.get('min_comc_price', '?')} · raw NM; EX-NM separada para revisão; LP só com "
        f"referência LP · só inglês · "
        f"Pokémon: {'lista icônica' if payload.get('iconic_only', True) else 'todos'}",
        f"- Slabs aceitos: {', '.join(graded) if graded else '—'}",
    ]
    funnel = payload.get("funnel") or {}
    if funnel:
        header.append("- Funil: " + " · ".join(funnel_lines(funnel)))
    warning = _top_n_warning(payload)
    if warning:
        header.append(warning)
    trust = _trust(payload)
    if sensitivity:
        operational = max(sensitivity)
        header.append(f"- Modo diagnóstico: scan com desconto mínimo {min_discount}% · "
                      f"limiar operacional {operational}%")
        try:
            scan_min = float(min_discount)
        except (TypeError, ValueError):
            scan_min = None
        if scan_min is not None and scan_min > min(sensitivity):
            header.append(f"- ⚠️ O scan rodou com desconto mínimo {_pct_br(scan_min)}% > menor "
                          f"limiar {min(sensitivity)}%: faixas abaixo de {_pct_br(scan_min)}% "
                          "ficam vazias por construção (re-rode o scan com --min-discount "
                          f"{min(sensitivity)} para enxergá-las).")
        header.append("")
        header.extend(sensitivity_counts(ok, review, sensitivity))
        header.append("")
        body = sensitivity_sections(ok, review, sensitivity, trust)
    else:
        header.append("")
        body = _section(CLEAN_TITLE, ok, trust) + _section(REVIEW_TITLE, review, trust)
    unpriced = payload.get("unpriced_review") or []
    if unpriced:
        body += _section("## 🔎 Revisão sem referência — não são oportunidades aprovadas", unpriced, trust)
    coverage = payload.get("coverage") or {}
    for scope, info in coverage.items():
        missing = info.get("without_validated_path") or []
        if missing:
            body.extend([f"Cobertura {scope}: {len(missing)} sets sem caminho COMC validado: " + ", ".join(missing), ""])
    footer = [
        "_OK valida a correspondência e a referência de preço; aquisição continua pendente de fotos, condição física, vendedor e custos. População não é verificada automaticamente. Valores são brutos._",
        "",
        f"_MATCH_REVIEW = confiança de match < {trust:.2f}, preço de referência "
        "mid/low (fallback do TCGplayer, não é venda real), `vendas<3` (mediana com só "
        "1–2 vendas comparáveis) ou `coluna÷vendas` (coluna informativa do PriceCharting "
        ">30% longe da mediana de vendas) — conferir manualmente antes de qualquer "
        "decisão. `baixa-liquidez(365d)` é nota, não muda o status: ≥3 vendas só em 365 "
        "dias (não em 180). "
        "`PC vendas <nota|LP> (n=…, mês..mês)` = mediana de ≥3 vendas concluídas da mesma "
        "carta, variante, certificadora e nota (ou LP explícito, para raw LP). "
        "Link [referência] = página da carta no PriceCharting (vendas eBay, gráfico, PSA 10/9) também para cartas soltas; o preço raw continua o TCGplayer market (TCG market|mid|low). "
        "Desconto% = (ref − COMC)/ref; Spread$ = ref − COMC (bruto, sem taxas); "
        "ROI bruto% = spread/COMC. "
        "Ranking: ROI bruto → desconto % → spread US$ → popularidade do Pokémon. "
        "O scanner reporta dados; não é recomendação de compra._",
        "",
    ]
    return "\n".join(header + body + footer)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json_path", help="JSON do Reporter (results/comc_deals_<escopo>_latest.json)")
    ap.add_argument("-o", "--output", required=True,
                    help="arquivo .md de saída (obrigatório), ex.: results/comc-grupo1-<data>.md")
    ap.add_argument("--group", type=int, choices=tuple(groups.VALID_GROUP_NUMBERS),
                    help="número do grupo escaneado (só rótulo do cabeçalho)")
    ap.add_argument("--sensitivity", type=parse_sensitivity, default=None, metavar="10,15,20",
                    help="modo diagnóstico: limiares de desconto crescentes; o maior é o "
                         "operacional, os demais viram faixas 'NÃO é oportunidade'")
    args = ap.parse_args(argv)

    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8-sig"))
    md = build_markdown(payload, group=args.group, sensitivity=args.sensitivity)

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
