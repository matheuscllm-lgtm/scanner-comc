"""Scan orchestration: era selection, chunked/resumable scanning, hourly flush."""
from __future__ import annotations

import logging
import re
import signal
import time

from .config import Settings
from .comc_scraper import ComcAccessError, ComcScraper, listings_from_json, parse_html_file
from .matcher import match
from .models import Deal
from .normalize import normalize_set, set_aliases, set_contains
from .reporter import Reporter
from .segments import ChunkCursor, TcgSet, select_sets, to_sets
from .tcg_index import TcgIndex
from .tcgcsv_client import TcgCsvClient

log = logging.getLogger("comc_scanner.pipeline")

_CODE_PREFIX = re.compile(r"^[A-Za-z0-9]{2,6}:\s*")


def comc_search_term(set_name: str) -> str:
    """Human set title for a COMC text search (drops the 'SV01:'/'SWSH07:' code)."""
    return _CODE_PREFIX.sub("", set_name).strip()


class BestDeals:
    """Tracks qualifying deals (and low-confidence ones) deduped by listing/product."""

    def __init__(self, top_n: int):
        self.top_n = top_n
        self.best: dict[tuple, Deal] = {}
        self.low: dict[tuple, Deal] = {}

    @staticmethod
    def _key(deal: Deal) -> tuple:
        ident = deal.listing.url or f"{deal.listing.raw_name}:{round(deal.listing.price, 2)}"
        return (deal.product.product_id, ident)

    def add(self, deal: Deal, gate: float, threshold: float) -> None:
        if deal.margin < threshold:
            return
        bucket = self.best if deal.match_confidence >= gate else self.low
        key = self._key(deal)
        cur = bucket.get(key)
        if cur is None or deal.margin > cur.margin:
            bucket[key] = deal
        self._prune()

    def _prune(self) -> None:
        cap = max(self.top_n * 20, 1000)
        for name in ("best", "low"):
            bucket = getattr(self, name)
            if len(bucket) > cap * 2:
                trimmed = sorted(bucket.items(), key=lambda kv: kv[1].margin, reverse=True)[:cap]
                setattr(self, name, dict(trimmed))

    def qualifying(self) -> list[Deal]:
        return sorted(self.best.values(), key=lambda d: d.margin, reverse=True)

    def low_conf(self) -> list[Deal]:
        return sorted(self.low.values(), key=lambda d: d.margin, reverse=True)[: self.top_n]


class Scanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = TcgCsvClient(settings)
        self.reporter = Reporter(settings)
        self._stop = False
        try:
            signal.signal(signal.SIGINT, self._on_signal)
            signal.signal(signal.SIGTERM, self._on_signal)
        except (ValueError, OSError):
            pass  # not in main thread

    def _on_signal(self, *_a) -> None:
        log.warning("Stop requested; will flush and save progress.")
        self._stop = True

    # --- index helpers ---------------------------------------------------
    def _ensure_index(self, sets: list[TcgSet], index: TcgIndex) -> None:
        for ts in sets:
            if index.has_group(ts.group_id):
                continue
            products = self.client.products(ts.group_id)
            prices = self.client.prices(ts.group_id)
            index.add_group(ts.group_id, ts.name, ts.abbreviation, products, prices)

    def _alias_map(self, sets: list[TcgSet]) -> dict[str, TcgSet]:
        amap: dict[str, TcgSet] = {}
        for ts in sets:
            for a in set_aliases(ts.name) | {normalize_set(ts.abbreviation)}:
                if a:
                    amap.setdefault(a, ts)
        return amap

    @staticmethod
    def _resolve_tset(set_hint: str | None, amap: dict[str, TcgSet]) -> TcgSet | None:
        if not set_hint:
            return None
        key = normalize_set(set_hint)
        if key in amap:
            return amap[key]
        for alias, ts in amap.items():
            if set_contains(alias, key):
                return ts
        return None

    # --- modes -----------------------------------------------------------
    def refresh_prices(self, era: str = "all") -> int:
        """Force-download the snapshot for the selected era's sets. Returns set count."""
        self.settings.tcgcsv_force_refresh = True
        groups = self.client.groups(force=True)
        sets = select_sets(groups, self.settings, era)
        index = TcgIndex()
        self._ensure_index(sets, index)
        log.info("Refreshed snapshot %s for %d sets (era=%s).",
                 self.client.snapshot_date(), len(sets), era)
        return len(sets)

    def capture(self, url: str, out_path: str) -> None:
        """Save a rendered COMC page to disk (for offline selector tuning)."""
        try:
            with ComcScraper(self.settings) as scraper:
                scraper.capture(url, out_path)
        except (ImportError, ComcAccessError) as exc:
            log.error("Capture unavailable: %s", exc)

    def parse_file(self, html_path: str) -> None:
        """Parse a saved COMC page and print the listings extracted (selector check)."""
        listings = parse_html_file(html_path)
        log.info("Parsed %d listings from %s", len(listings), html_path)
        for L in listings[:15]:
            print(f"  {L.raw_name!r}  price={L.price}  set={L.set_hint!r} "
                  f"num={L.number_hint!r}  cond={L.condition!r}  url={L.url}")
        if not listings:
            print("  (no listings parsed — the COMC selectors in comc_scraper.py likely "
                  "need adjusting for this page's DOM)")

    def dry_run(self, listings_path: str | None = None, era: str = "all",
                html_path: str | None = None) -> BestDeals:
        listings = parse_html_file(html_path) if html_path else listings_from_json(listings_path)
        groups = self.client.groups()
        tsets = to_sets(groups, self.settings)
        amap = self._alias_map(tsets)
        needed = {}
        for L in listings:
            ts = self._resolve_tset(L.set_hint, amap)
            if ts:
                needed[ts.group_id] = ts
        index = TcgIndex()
        self._ensure_index(list(needed.values()), index)
        best = BestDeals(self.settings.top_n)
        gate, thr = self.settings.min_match_confidence, self.settings.min_gross_margin
        for L in listings:
            if L.graded and not self.settings.comc_include_graded:
                continue
            ts = self._resolve_tset(L.set_hint, amap)
            ctx = normalize_set(ts.name) if ts else None
            deal = match(L, index, self.settings, context_set_key=ctx)
            if deal:
                deal.era = ts.era if ts else ""
                best.add(deal, gate, thr)
        label = era if era != "all" else "dryrun"
        self.reporter.flush(best.qualifying(), label, best.low_conf())
        return best

    def run_once(self, era: str, resume: bool = True) -> BestDeals:
        groups = self.client.groups()
        all_sets = select_sets(groups, self.settings, era)
        snapshot = self.client.snapshot_date()
        cursor = ChunkCursor.load(era, snapshot) if resume else ChunkCursor(era, snapshot)
        if not resume:
            cursor.clear()
            cursor = ChunkCursor(era, snapshot)
        start = cursor.next_set_index
        if start >= len(all_sets):
            log.info("Era '%s' complete for %s; restarting sweep.", era, snapshot)
            cursor = ChunkCursor(era, snapshot)
            start = 0
        max_sets = self.settings.max_sets_per_chunk or len(all_sets)
        chunk = all_sets[start: start + max_sets]
        log.info("Scanning era '%s': %d sets in this chunk (from index %d of %d).",
                 era, len(chunk), start, len(all_sets))

        index = TcgIndex()
        self._ensure_index(chunk, index)
        best = BestDeals(self.settings.top_n)
        gate, thr = self.settings.min_match_confidence, self.settings.min_gross_margin
        deadline = (time.monotonic() + self.settings.max_run_seconds) if self.settings.max_run_seconds else None
        next_flush = time.time() + self.settings.scan_interval_s
        completed = start

        try:
            with ComcScraper(self.settings) as scraper:
                for offset, ts in enumerate(chunk):
                    set_index = start + offset
                    term = comc_search_term(ts.name)
                    ctx = normalize_set(ts.name)
                    page_start = cursor.page if set_index == start else 1
                    last_page = page_start - 1
                    for page_no, listings in scraper.iter_listings(
                        term, max_pages=self.settings.max_pages_per_set, start_page=page_start
                    ):
                        for L in listings:
                            if L.graded and not self.settings.comc_include_graded:
                                continue
                            deal = match(L, index, self.settings, context_set_key=ctx)
                            if deal:
                                deal.era = ts.era
                                best.add(deal, gate, thr)
                        last_page = page_no
                        if time.time() >= next_flush:
                            self.reporter.flush(best.qualifying(), era, best.low_conf())
                            next_flush += self.settings.scan_interval_s
                        if self._stop or (deadline and time.monotonic() >= deadline):
                            cursor.next_set_index = set_index
                            cursor.page = last_page + 1
                            cursor.save()
                            self.reporter.flush(best.qualifying(), era, best.low_conf())
                            log.info("Budget/stop hit; cursor saved at set %d page %d.",
                                     set_index, cursor.page)
                            return best
                    completed = set_index + 1
                    cursor.next_set_index = completed
                    cursor.page = 1
                    cursor.save()
                    if self._stop:
                        break
        except ImportError:
            log.error(
                "Playwright is required for live COMC scanning. Install with:\n"
                "    pip install -r requirements.txt && playwright install chromium"
            )
            return best
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)
            return best

        self.reporter.flush(best.qualifying(), era, best.low_conf())
        if completed >= len(all_sets):
            cursor.clear()
            log.info("Era '%s' sweep complete.", era)
        return best

    def run_loop(self, era: str) -> None:
        while not self._stop:
            self.client._snapshot_date = None  # re-date daily snapshot each sweep
            self.run_once(era, resume=True)
            if self._stop:
                break
            cursor_exists = ChunkCursor._path(era).exists()
            if cursor_exists:
                continue  # more chunks remain in this era; keep going
            log.info("Era '%s' done; sleeping %ds before next sweep.", era, self.settings.scan_interval_s)
            self._sleep(self.settings.scan_interval_s)

    def _sleep(self, seconds: int) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stop:
            time.sleep(min(5, end - time.monotonic()))
