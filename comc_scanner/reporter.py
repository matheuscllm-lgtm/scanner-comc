"""Reporting: console markdown table, Sheets-friendly CSV/JSON, optional Sheets push."""
from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path

from .config import Settings
from .models import Deal

log = logging.getLogger("comc_scanner.reporter")

# Confidence at/above which a match is treated as solid; below it the row is
# tagged "validar" so the operator double-checks the card↔TCGPlayer pairing.
TRUST_CONFIDENCE = 0.90

# The TCGCSV reference price uses a fallback chain market -> mid -> low (tracked
# end-to-end as `price_field`). "market" is a real observed sale price; "mid"/"low"
# are derived/listing-based and less reliable. A deal whose margin rests on a
# fallback must look DIFFERENT from a real-market one in the operator's primary
# surface (same honesty lesson as MYP's "fallback shown as real", #55/#58), so
# non-"market" rows get an explicit "preço:<campo>" tag added to the Flag column.
# "market" rows stay clean — only fallback rows are marked.
TRUSTED_PRICE_FIELD = "market"

# Columns shown in the console/markdown table (compact subset of the full row).
# This is the CANONICAL delivery table for the chat (see README "Entrega dos
# resultados" / CLAUDE.md). Always render with this function — never hand-build a
# table. Each row carries: `card_number` (Pokémon name + collector number), the
# match `confidence`, a `flag` ("validar" when confidence is below
# TRUST_CONFIDENCE, plus "preço:<campo>" when the reference price is a mid/low
# fallback rather than a real market sale) so suspect rows are marked instead of
# hidden, and a single
# `Links` column ("[oferta](comc_url) · [referência](tcg_url)") — the cross-scanner
# canonical format shared with MYP (`delivery_links`) and Liga (`_links`).
_TABLE_COLS = [
    ("rank", "#"),
    ("margin_pct", "Margin%"),
    ("comc_price", "COMC$"),
    ("tcg_reference", "TCG$"),
    ("profit_abs", "Profit$"),
    ("card_number", "Card"),
    ("set", "Set"),
    ("condition", "Cond"),
    ("sub_type", "Sub"),
    ("confidence", "Conf"),
    ("flag", "Flag"),
    ("links", "Links"),
]
_MAXW = {"card_number": 34, "set": 26, "condition": 10, "sub_type": 16}

# Tabela do modo --iconic: DUAS referências lado a lado (TCG$ = market
# TCGplayer/tcgcsv; PC$ = mediana de vendas reais PriceCharting) e as duas
# margens; a que CLASSIFICA é a mais conservadora (comc_scanner.iconic). Links
# ganham o 3º link [PC] quando a referência PC existe.
_ICONIC_TABLE_COLS = [
    ("rank", "#"),
    ("margin_pct", "Marg TCG%"),
    ("pc_margin_pct", "Marg PC%"),
    ("comc_price", "COMC$"),
    ("tcg_reference", "TCG$"),
    ("pc_reference", "PC$"),
    ("card_number", "Card"),
    ("set", "Set"),
    ("condition", "Cond"),
    ("confidence", "Conf"),
    ("flag", "Flag"),
    ("links", "Links"),
]


def _flag_for(row: dict) -> str:
    """Per-row review flag.

    Two honesty signals, composed:
    - low-confidence match  -> "validar" (else "ok"), never dropped;
    - reference price not backed by a real "market" sale (mid/low fallback)
      -> append "preço:<campo>" so a fallback-backed deal is visually distinct
      from a real-market one. "market" rows carry no price tag.
    e.g. "ok · preço:mid", "validar · preço:low".
    """
    try:
        conf = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    flag = "validar" if conf < TRUST_CONFIDENCE else "ok"

    price_field = row.get("price_field")
    price_field = "" if price_field is None else str(price_field).strip()
    if price_field and price_field != TRUSTED_PRICE_FIELD:
        flag = f"{flag} · preço:{price_field}"
    return flag


def _links_cell(row: dict, with_pc: bool = False) -> str:
    """Coluna `Links`: "[oferta](comc_url) · [referência](tcg_url)".

    Espelha o formato canônico cross-scanner (MYP `delivery_links`, Liga `_links`):
    `oferta` = listagem na COMC; `referência` = preço de referência no TCGPlayer. Os
    dois links são lidos do deal (nunca inventados); emite só os que existirem e "—"
    se nenhum. No modo icônico (`with_pc`) acrescenta `[PC](pc_url)` — a página de
    vendas reais do PriceCharting — quando ela existe.
    """
    parts = []
    comc_url = "" if row.get("comc_url") is None else str(row.get("comc_url"))
    tcg_url = "" if row.get("tcg_url") is None else str(row.get("tcg_url"))
    pc_url = "" if row.get("pc_url") is None else str(row.get("pc_url"))
    if comc_url:
        parts.append(f"[oferta]({comc_url})")
    if tcg_url:
        parts.append(f"[referência]({tcg_url})")
    if with_pc and pc_url:
        parts.append(f"[PC]({pc_url})")
    return " · ".join(parts) if parts else "—"


def _cell(key: str, value: object) -> str:
    if key == "links":  # pre-built markdown links cell — render verbatim
        return "" if value is None else str(value)
    if value is None and key in ("pc_reference", "pc_margin_pct"):
        return "—"  # sem PriceCharting: honesto, nunca 0
    s = "" if value is None else str(value)
    w = _MAXW.get(key)
    if w and len(s) > w:
        s = s[: w - 1] + "…"
    return s.replace("|", "/")


def table_header_lines() -> list[str]:
    """Markdown header + separator for the canonical delivery table."""
    header = "| " + " | ".join(label for _, label in _TABLE_COLS) + " |"
    sep = "| " + " | ".join("---" for _ in _TABLE_COLS) + " |"
    return [header, sep]


def render_row_line(row: dict, rank: int) -> str:
    """One canonical table line from a flat deal row (Deal.as_row() dict or the
    same dict re-read from the Reporter JSON/CSV). Computes flag + Links here so
    every consumer (live scan table, comc_summary.py) shares ONE format source."""
    row = dict(row)  # don't mutate the caller's row
    row["rank"] = rank
    row["flag"] = _flag_for(row)
    row["links"] = _links_cell(row)
    return "| " + " | ".join(_cell(k, row.get(k, "")) for k, _ in _TABLE_COLS) + " |"


def render_rows_table(rows: list[dict]) -> str:
    """Full canonical table (header + every row, ranked in the given order)."""
    lines = table_header_lines()
    lines.extend(render_row_line(row, rank) for rank, row in enumerate(rows, 1))
    return "\n".join(lines)


# --- modo --iconic ---------------------------------------------------------

def iconic_table_header_lines() -> list[str]:
    header = "| " + " | ".join(label for _, label in _ICONIC_TABLE_COLS) + " |"
    sep = "| " + " | ".join("---" for _ in _ICONIC_TABLE_COLS) + " |"
    return [header, sep]


def render_iconic_row_line(row: dict, rank: int) -> str:
    """Linha da tabela icônica: flag = `_flag_for` (validar / preço:<campo>) +
    flags do modo (`sem PC`, `PC diverge`); Links com o 3º link [PC]."""
    from .iconic import iconic_flags  # local: evita import circular

    row = dict(row)
    row["rank"] = rank
    row["flag"] = " · ".join([_flag_for(row), *iconic_flags(row)])
    row["links"] = _links_cell(row, with_pc=True)
    return "| " + " | ".join(_cell(k, row.get(k, "")) for k, _ in _ICONIC_TABLE_COLS) + " |"


def render_iconic_rows_table(rows: list[dict]) -> str:
    lines = iconic_table_header_lines()
    lines.extend(render_iconic_row_line(row, rank) for rank, row in enumerate(rows, 1))
    return "\n".join(lines)


def render_markdown(deals: list[Deal], era: str, top_n: int, iconic: bool = False) -> str:
    label = "COMC deals (icônicos)" if iconic else "COMC deals"
    title = f"### {label} — era: {era} — top {min(len(deals), top_n)} (margem desc.)"
    if not deals:
        return title + "\n\n_(nenhum deal acima do limiar ainda)_"
    rows = [d.as_row() for d in deals[:top_n]]
    table = render_iconic_rows_table(rows) if iconic else render_rows_table(rows)
    return "\n".join([title, "", table])


class Reporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.results_dir.mkdir(parents=True, exist_ok=True)
        # Modo --iconic: enriquece com PriceCharting a cada flush e grava em
        # arquivos PRÓPRIOS (comc_iconic_<era>_*) para não sobrescrever um scan
        # clássico da mesma era.
        self.iconic = bool(settings.iconic_only)
        self._enricher = None
        if self.iconic:
            from .iconic import PriceChartingEnricher

            self._enricher = PriceChartingEnricher(settings)

    @property
    def file_prefix(self) -> str:
        return "comc_iconic" if self.iconic else "comc_deals"

    def _write_csv(self, rows: list[dict], path: Path) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _write_json(self, payload: dict, path: Path) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def flush(
        self, deals: list[Deal], era: str, low_confidence: list[Deal] | None = None
    ) -> str:
        """Write latest + timestamped CSV/JSON, print the markdown table, push Sheets."""
        deals = sorted(deals, key=lambda d: d.margin, reverse=True)[: self.settings.top_n]
        low_confidence = list(low_confidence or [])
        if self._enricher is not None:
            self._enricher.enrich(deals + low_confidence)
        rows = [{"rank": i, **d.as_row()} for i, d in enumerate(deals, 1)]
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rdir = self.settings.results_dir
        prefix = self.file_prefix

        self._write_csv(rows, rdir / f"{prefix}_{era}_latest.csv")
        self._write_csv(rows, rdir / f"{prefix}_{era}_{stamp}.csv")
        payload = {
            "era": era,
            "generated_utc": stamp,
            "mode": "iconic" if self.iconic else "classic",
            "min_gross_margin": self.settings.min_gross_margin,
            "max_gross_margin": self.settings.max_gross_margin,
            "pricecharting": bool(self.iconic and self.settings.pricecharting_enabled),
            "top_n": self.settings.top_n,
            "count": len(rows),
            "deals": rows,
            "low_confidence": [d.as_row() for d in low_confidence],
        }
        self._write_json(payload, rdir / f"{prefix}_{era}_latest.json")
        self._write_json(payload, rdir / f"{prefix}_{era}_{stamp}.json")

        table = render_markdown(deals, era, self.settings.top_n, iconic=self.iconic)
        print("\n" + table + "\n")
        self._maybe_push_to_sheets(rows, era)
        return table

    def _maybe_push_to_sheets(self, rows: list[dict], era: str) -> None:
        creds = self.settings.gsheets_credentials_json
        sheet_id = self.settings.gsheets_id
        if not creds or not sheet_id:
            log.info("Google Sheets disabled (no credentials/sheet id); wrote CSV only.")
            return
        try:
            import gspread  # type: ignore
            from google.oauth2.service_account import Credentials  # type: ignore

            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            info = json.loads(Path(creds).read_text()) if Path(creds).exists() else json.loads(creds)
            gc = gspread.authorize(Credentials.from_service_account_info(info, scopes=scopes))
            sh = gc.open_by_key(sheet_id)
            title = f"{self.settings.gsheets_worksheet} ({era})"
            try:
                ws = sh.worksheet(title)
            except Exception:
                ws = sh.add_worksheet(title=title, rows=max(len(rows) + 5, 50), cols=20)
            ws.clear()
            if rows:
                header = list(rows[0].keys())
                ws.update([header] + [[r.get(c, "") for c in header] for r in rows])
            log.info("Pushed %d rows to Google Sheet worksheet %s", len(rows), title)
        except Exception as exc:  # noqa: BLE001 - never fail the scan on Sheets errors
            log.warning("Google Sheets push failed (%s); CSV still written.", exc)
