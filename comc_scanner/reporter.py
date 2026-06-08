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

# Columns shown in the console/markdown table (compact subset of the full row).
_TABLE_COLS = [
    ("rank", "#"),
    ("margin_pct", "Margin%"),
    ("comc_price", "COMC$"),
    ("tcg_reference", "TCG$"),
    ("profit_abs", "Profit$"),
    ("card", "Card"),
    ("set", "Set"),
    ("number", "No."),
    ("condition", "Cond"),
    ("sub_type", "Sub"),
    ("confidence", "Conf"),
]
_MAXW = {"card": 30, "set": 26, "condition": 10, "sub_type": 16}


def _cell(key: str, value: object) -> str:
    s = "" if value is None else str(value)
    w = _MAXW.get(key)
    if w and len(s) > w:
        s = s[: w - 1] + "…"
    return s.replace("|", "/")


def render_markdown(deals: list[Deal], era: str, top_n: int) -> str:
    title = f"### COMC deals — era: {era} — top {min(len(deals), top_n)} (margem desc.)"
    if not deals:
        return title + "\n\n_(nenhum deal acima do limiar ainda)_"
    header = "| " + " | ".join(label for _, label in _TABLE_COLS) + " |"
    sep = "| " + " | ".join("---" for _ in _TABLE_COLS) + " |"
    lines = [title, "", header, sep]
    for rank, deal in enumerate(deals[:top_n], 1):
        row = deal.as_row()
        row["rank"] = rank
        lines.append("| " + " | ".join(_cell(k, row.get(k, "")) for k, _ in _TABLE_COLS) + " |")
    return "\n".join(lines)


class Reporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.results_dir.mkdir(parents=True, exist_ok=True)

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
        rows = [{"rank": i, **d.as_row()} for i, d in enumerate(deals, 1)]
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rdir = self.settings.results_dir

        self._write_csv(rows, rdir / f"comc_deals_{era}_latest.csv")
        self._write_csv(rows, rdir / f"comc_deals_{era}_{stamp}.csv")
        payload = {
            "era": era,
            "generated_utc": stamp,
            "min_gross_margin": self.settings.min_gross_margin,
            "top_n": self.settings.top_n,
            "count": len(rows),
            "deals": rows,
            "low_confidence": [d.as_row() for d in (low_confidence or [])],
        }
        self._write_json(payload, rdir / f"comc_deals_{era}_latest.json")
        self._write_json(payload, rdir / f"comc_deals_{era}_{stamp}.json")

        table = render_markdown(deals, era, self.settings.top_n)
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
