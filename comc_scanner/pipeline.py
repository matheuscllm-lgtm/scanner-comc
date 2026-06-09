"""Scan orchestration: era selection, chunked/resumable scanning, hourly flush."""
from __future__ import annotations

import logging
import re
import signal
import time

from .config import CACHE_DIR, Settings
from .comc_scraper import ComcAccessError, ComcScraper, listings_from_json, parse_html_file
from .firecrawl_client import ComcBlockedError
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

    def warm_profile(self, wait_s: int = 30, url: str | None = None) -> bool:
        """Headful warm-up: clear Cloudflare once so the persistent profile stores the
        cf_clearance cookie; afterwards `--fetch-mode playwright` runs work HEADLESS and
        free (no Firecrawl). Re-run when the cookie expires (CF challenges again)."""
        self.settings.comc_fetch_mode = "playwright"
        self.settings.comc_headless = False
        try:
            with ComcScraper(self.settings) as scraper:
                ok = scraper.warm(url=url, wait_s=wait_s)
        except (ImportError, ComcAccessError) as exc:
            log.error("Warm-up unavailable: %s", exc)
            return False
        log.info("Profile dir: %s", self.settings.comc_profile_dir)
        return ok

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

        consecutive_blocked = 0  # circuit breaker: bail if CF blocks set after set
        try:
            with ComcScraper(self.settings) as scraper:
                for offset, ts in enumerate(chunk):
                    set_index = start + offset
                    term = comc_search_term(ts.name)
                    ctx = normalize_set(ts.name)
                    page_start = cursor.page if set_index == start else 1
                    last_page = page_start - 1
                    set_yielded = False
                    try:
                        for page_no, listings in scraper.iter_listings(
                            term, max_pages=self.settings.max_pages_per_set, start_page=page_start
                        ):
                            set_yielded = True
                            for L in listings:
                                if L.graded and not self.settings.comc_include_graded:
                                    continue
                                if not self._condition_ok(L) or not self._variant_ok(L):
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
                    except ComcBlockedError:
                        # A block after yielding pages is a mid-set hiccup, not a hard block.
                        if set_yielded:
                            consecutive_blocked = 0
                            log.warning("COMC set '%s' blocked mid-pagination; kept partial.",
                                        ts.name)
                            continue
                        consecutive_blocked += 1
                        log.warning("COMC set '%s' blocked by Cloudflare (%d in a row).",
                                    ts.name, consecutive_blocked)
                        if consecutive_blocked >= 3:
                            log.error(
                                "Cloudflare blocked %d sets in a row; aborting chunk to avoid "
                                "burning Firecrawl credits. The faceted text-search URL is "
                                "CF-sensitive — use a set-path/broad strategy or playwright mode.",
                                consecutive_blocked,
                            )
                            self.reporter.flush(best.qualifying(), era, best.low_conf())
                            return best
                        continue  # skip this set, try the next
                    if set_yielded:
                        consecutive_blocked = 0
                    completed = set_index + 1
                    cursor.next_set_index = completed
                    cursor.page = 1
                    cursor.save()
                    if self._stop:
                        break
        except ImportError:
            log.error(
                "Playwright was requested (--fetch-mode playwright) but is not installed. "
                "Install it (pip install -r requirements.txt && playwright install chromium) "
                "or use the default firecrawl mode (headless, no browser)."
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

    def run_broad(self, era: str = "all", resume: bool = True) -> BestDeals:
        """Headless functional scan: paginate the plain (CF-friendly) COMC browse and keep
        only listings the matcher resolves to a TCG set in `era`'s index.

        COMC's faceted TEXT-search URL is reliably Cloudflare-challenged, but the plain
        browse clears it. So instead of searching per-set, we sweep the price-sorted browse
        and let the matcher filter to real TCG cards. Set slugs seen are harvested to
        `.cache/comc_set_catalog.json` to enable an efficient set-path mode later.
        """
        groups = self.client.groups()
        all_sets = select_sets(groups, self.settings, era)
        index = TcgIndex()
        self._ensure_index(all_sets, index)
        log.info("Broad sweep: %d TCG sets in '%s' index loaded; sweeping COMC browse.",
                 len(all_sets), era)

        page_cursor = CACHE_DIR / f"broad_{era}_page.txt"
        start_page = 1
        if resume and page_cursor.exists():
            try:
                start_page = max(1, int(page_cursor.read_text().strip()))
            except ValueError:
                start_page = 1

        best = BestDeals(self.settings.top_n)
        gate, thr = self.settings.min_match_confidence, self.settings.min_gross_margin
        deadline = (time.monotonic() + self.settings.max_run_seconds) if self.settings.max_run_seconds else None
        next_flush = time.time() + self.settings.scan_interval_s
        catalog = self._load_catalog()
        seen_listings = matched = 0

        try:
            with ComcScraper(self.settings) as scraper:
                for page_no, listings in scraper.iter_listings(
                    search_term=None, max_pages=self.settings.max_pages_per_set,
                    start_page=start_page,
                ):
                    for L in listings:
                        seen_listings += 1
                        self._harvest_slug(L, catalog)
                        if L.graded and not self.settings.comc_include_graded:
                            continue
                        if not self._condition_ok(L) or not self._variant_ok(L):
                            continue
                        deal = match(L, index, self.settings)
                        if deal:
                            matched += 1
                            deal.era = era
                            best.add(deal, gate, thr)
                    page_cursor.write_text(str(page_no + 1), encoding="utf-8")
                    if time.time() >= next_flush:
                        self.reporter.flush(best.qualifying(), era, best.low_conf())
                        self._save_catalog(catalog)
                        next_flush += self.settings.scan_interval_s
                    if self._stop or (deadline and time.monotonic() >= deadline):
                        log.info("Broad sweep budget/stop at page %d (%d seen, %d matched).",
                                 page_no, seen_listings, matched)
                        break
        except ComcBlockedError:
            log.error("Cloudflare blocked the plain COMC browse via Firecrawl — unusual "
                      "(the browse normally clears). Likely an account/egress-level block; "
                      "aborting to avoid burning credits.")
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)

        self._save_catalog(catalog)
        self.reporter.flush(best.qualifying(), era, best.low_conf())
        log.info("Broad sweep done: %d listings seen, %d matched to TCG, %d catalog sets.",
                 seen_listings, matched, len(catalog))
        return best

    # --- slug catalog (groundwork for an efficient set-path mode) --------
    def _catalog_path(self):
        return CACHE_DIR / "comc_set_catalog.json"

    def _load_catalog(self) -> dict:
        import json
        p = self._catalog_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_catalog(self, catalog: dict) -> None:
        import json
        p = self._catalog_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    def _condition_ok(self, listing) -> bool:
        """NM-only invariant: keep only NM-range conditions (COMC's g-band facet is
        ignored on set-path browse, so we enforce it here from the per-listing condition).
        An empty/unknown condition is dropped (conservative — don't compare unknown to NM)."""
        cond = (listing.condition or "").strip().lower()
        return cond in self.settings.comc_condition_allow

    def _variant_ok(self, listing) -> bool:
        """English-only: drop foreign-language sub-printings (Japanese/Korean/...) whose
        set string names another language — TCGCSV prices are the English product, so a
        JP/KR card vs the EN price is a false signal."""
        blob = f"{listing.set_hint or ''} {listing.raw_name or ''}".lower()
        return not any(v in blob for v in self.settings.comc_exclude_variants)

    @staticmethod
    def _harvest_slug(listing, catalog: dict) -> None:
        """Record the COMC (year, slug) for a listing's set, keyed by set_hint."""
        import re
        if not listing.set_hint or not listing.url:
            return
        m = re.search(r"/Cards/Pokemon/(\d{4})/([^/]+)/", listing.url)
        if not m:
            return
        key = listing.set_hint
        entry = catalog.get(key)
        if entry is None:
            catalog[key] = {"year": m.group(1), "slug": m.group(2), "count": 1}
        else:
            entry["count"] = entry.get("count", 0) + 1

    def run_targeted(self, era: str = "vintage", resume: bool = True) -> BestDeals:
        """Functional scan via COMC set-path browse using the curated slug catalog.

        Reads `comc_scanner/comc_set_slugs.json` (TCG set name -> {year, slug}); for each
        set in `era`'s TCG index that has a validated COMC slug, browses that set's
        listings by URL PATH (the Cloudflare-friendly route the text-search is not) and
        matches them. This is the efficient, useful-yield mode vs. the broad sweep.
        """
        slugs = self._load_slug_catalog()
        if not slugs:
            log.error("No COMC slug catalog (comc_scanner/comc_set_slugs.json); run the "
                      "slug-discovery step first. Nothing to scan in targeted mode.")
            return BestDeals(self.settings.top_n)

        groups = self.client.groups()
        all_sets = select_sets(groups, self.settings, era)
        by_norm = {normalize_set(ts.name): ts for ts in all_sets}
        amap = self._alias_map(all_sets)
        targets = []  # (TcgSet, year, slug)
        for tcg_name, info in slugs.items():
            # year may be "" for modern sets (their COMC path is a single segment with
            # the year embedded) — only slug is strictly required.
            if not info.get("validated") or not info.get("slug"):
                continue
            ts = by_norm.get(normalize_set(tcg_name)) or self._resolve_tset(tcg_name, amap)
            if ts is not None:
                targets.append((ts, str(info.get("year", "")), info["slug"]))
        if not targets:
            log.error("Slug catalog has %d entries but none intersect era '%s'.",
                      len(slugs), era)
            return BestDeals(self.settings.top_n)

        index = TcgIndex()
        self._ensure_index([t[0] for t in targets], index)
        best = BestDeals(self.settings.top_n)
        gate, thr = self.settings.min_match_confidence, self.settings.min_gross_margin
        deadline = (time.monotonic() + self.settings.max_run_seconds) if self.settings.max_run_seconds else None
        next_flush = time.time() + self.settings.scan_interval_s
        consecutive_blocked = 0

        # Resume cursor: index of the next target to scan, so a budget/stop mid-run does
        # not re-scan (and re-pay Firecrawl for) the sets already done.
        cursor_path = CACHE_DIR / f"targeted_{era}_idx.txt"
        start_idx = 0
        if resume and cursor_path.exists():
            try:
                start_idx = max(0, int(cursor_path.read_text().strip()))
            except ValueError:
                start_idx = 0
        if start_idx >= len(targets):
            start_idx = 0  # finished a full sweep last time; start over
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("Targeted scan: %d sets in era '%s' (resuming at index %d).",
                 len(targets), era, start_idx)

        try:
            with ComcScraper(self.settings) as scraper:
                for idx in range(start_idx, len(targets)):
                    ts, year, slug = targets[idx]
                    ctx = normalize_set(ts.name)
                    set_yielded = False
                    # Vintage WotC: "<year>/<slug>". Modern (SV/SWSH) COMC paths embed the
                    # year in a single segment (e.g. "2023_Pokemon_..._151_sv2a") — catalog
                    # entries store year="" and the full segment as slug.
                    era_path = f"{year}/{slug}" if year else slug
                    try:
                        for page_no, listings in scraper.iter_listings(
                            search_term=None, era_path=era_path,
                            max_pages=self.settings.max_pages_per_set,
                        ):
                            set_yielded = True
                            for L in listings:
                                if L.graded and not self.settings.comc_include_graded:
                                    continue
                                if not self._condition_ok(L) or not self._variant_ok(L):
                                    continue
                                deal = match(L, index, self.settings, context_set_key=ctx)
                                if deal:
                                    deal.era = ts.era
                                    best.add(deal, gate, thr)
                            if time.time() >= next_flush:
                                self.reporter.flush(best.qualifying(), era, best.low_conf())
                                next_flush += self.settings.scan_interval_s
                            if self._stop or (deadline and time.monotonic() >= deadline):
                                cursor_path.write_text(str(idx), encoding="utf-8")  # resume here
                                self.reporter.flush(best.qualifying(), era, best.low_conf())
                                log.info("Targeted budget/stop hit at set '%s' (idx %d).",
                                         ts.name, idx)
                                return best
                    except ComcBlockedError:
                        # A block AFTER yielding pages is a mid-set hiccup, not a hard block —
                        # don't count it against the consecutive-block circuit breaker.
                        if set_yielded:
                            consecutive_blocked = 0
                            log.warning("COMC set '%s' blocked mid-pagination; kept partial.",
                                        ts.name)
                        else:
                            consecutive_blocked += 1
                            log.warning("COMC set '%s' blocked (%d in a row).",
                                        ts.name, consecutive_blocked)
                            if consecutive_blocked >= 3:
                                log.error("Cloudflare blocked %d sets in a row; aborting to "
                                          "save credits.", consecutive_blocked)
                                cursor_path.write_text(str(idx), encoding="utf-8")
                                break
                        cursor_path.write_text(str(idx + 1), encoding="utf-8")
                        continue
                    if set_yielded:
                        consecutive_blocked = 0
                    cursor_path.write_text(str(idx + 1), encoding="utf-8")
                    log.info("Scanned set '%s' via slug '%s'.", ts.name, slug)
                    if self._stop:
                        break
                else:
                    cursor_path.write_text("0", encoding="utf-8")  # full sweep done; reset
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)

        self.reporter.flush(best.qualifying(), era, best.low_conf())
        log.info("Targeted scan done; %d qualifying deals.", len(best.qualifying()))
        return best

    def _load_slug_catalog(self) -> dict:
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent / "comc_set_slugs.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

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
