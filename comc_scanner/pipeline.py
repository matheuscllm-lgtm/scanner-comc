"""Orquestração do scanner único COMC → referência de preço → funil → entrega.

Fluxo por set (catálogo ``comc_set_slugs.json``, agrupado em ``groups.py``):

    COMC set-path browse (2 passadas: cartas soltas ``aUngraded`` + slabs ``aGraded``)
    → funil ``process_listing`` (tipo/condição NM/idioma EN/piso US$/Pokémon icônico)
    → ``matcher.match`` (identifica a carta no TCGplayer; confiança 0-1)
    → referência: raw = TCGplayer market (tcgcsv/TCGdex); slab = PriceCharting por nota
    → desconto ≥ ``MIN_DISCOUNT_PERCENT`` → status OK / MATCH_REVIEW
    → ``BestDeals`` (dedupe) → ``Reporter.flush`` (JSON/CSV + tabela)

Sem estado entre dias: nenhum cursor de retomada; snapshot tcgcsv e cache
PriceCharting são do dia; cada run começa do zero (decisão do operador).
"""
from __future__ import annotations

import datetime
import json
import logging
import signal
import time
from collections import Counter
from pathlib import Path

from .comc_scraper import ComcAccessError, ComcBlockedError, ComcScraper
from .config import Settings
from .grading import Grade, pc_price_key
from .iconic import match_iconic
from .margin import gross_margin
from .matcher import match
from .models import Deal
from .normalize import normalize_set, set_aliases
from .pricecharting_client import graded_reference
from .ranking import sort_key
from .reporter import Reporter, classify_row
from .segments import TcgSet, select_sets
from .tcg_index import TcgIndex
from .tcgcsv_client import TcgCsvClient
from .tcgdex_client import TcgdexClient

log = logging.getLogger("comc_scanner.pipeline")

KIND_RAW = "raw"
KIND_SLAB = "slab"


class FunnelStats(Counter):
    """Contadores do funil (spec §13): quantas listagens entraram e por que saíram."""

    def bump(self, key: str) -> None:
        self[key] += 1


class BestDeals:
    """Deals aprovados (e os de confiança baixa), deduplicados por listagem."""

    def __init__(self, top_n: int):
        self.top_n = top_n
        self.best: dict[tuple, Deal] = {}
        self.low: dict[tuple, Deal] = {}

    @staticmethod
    def _key(deal: Deal) -> tuple:
        """Chave única: produto TCG + tipo (raw/nota) + listagem COMC (spec §12)."""
        ident = deal.listing.item_id or deal.listing.url or \
            f"{deal.listing.raw_name}:{round(deal.listing.price, 2)}"
        return (deal.product.product_id, deal.listing_type, ident)

    def add(self, deal: Deal, gate: float, threshold: float) -> None:
        if deal.margin < threshold:
            return
        bucket = self.best if deal.match_confidence >= gate else self.low
        key = self._key(deal)
        cur = bucket.get(key)
        if cur is None or deal.margin > cur.margin:
            bucket[key] = deal

    @staticmethod
    def _ranked(deals: list[Deal]) -> list[Deal]:
        return sorted(deals, key=lambda d: sort_key(d.as_row()))

    def qualifying(self) -> list[Deal]:
        return self._ranked(list(self.best.values()))

    def low_conf(self) -> list[Deal]:
        return self._ranked(list(self.low.values()))[: self.top_n]


def _grade_from_key(key: str | None) -> Grade | None:
    """'CGC 10 PRISTINE' → Grade (a chave normalizada gravada no listing)."""
    if not key:
        return None
    parts = key.split(" ")
    try:
        return Grade(grader=parts[0], value=float(parts[1]),
                     qualifier=parts[2] if len(parts) > 2 else "")
    except (IndexError, ValueError):
        return None


class Scanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = TcgCsvClient(settings)
        # Fallback price source (TCGdex) — used only if TCGCSV fails for a set.
        self._tcgdex = TcgdexClient(settings) if settings.tcgdex_fallback else None
        self.reporter = Reporter(settings)
        self.stats = FunnelStats()
        self._stop = False
        try:
            signal.signal(signal.SIGINT, self._on_signal)
            signal.signal(signal.SIGTERM, self._on_signal)
        except (ValueError, OSError):
            pass  # not in main thread

    def _on_signal(self, *_a) -> None:
        log.warning("Stop requested; will flush what was found so far.")
        self._stop = True

    # --- index helpers ---------------------------------------------------
    def _ensure_index(self, sets: list[TcgSet], index: TcgIndex) -> None:
        for ts in sets:
            if index.has_group(ts.group_id):
                continue
            products, prices = self._fetch_set_data(ts)
            if not products:
                continue  # no source could price this set; skip (already logged)
            index.add_group(ts.group_id, ts.name, ts.abbreviation, products, prices)

    def _fetch_set_data(self, ts: TcgSet) -> tuple[list[dict] | None, list[dict] | None]:
        """Set products/prices from TCGCSV, falling back to TCGdex on failure/empty."""
        try:
            products = self.client.products(ts.group_id)
            prices = self.client.prices(ts.group_id)
            if products and prices:
                return products, prices
            log.warning("TCGCSV returned no data for set '%s' (group %s); trying TCGdex.",
                        ts.name, ts.group_id)
        except RuntimeError as exc:
            log.warning("TCGCSV unavailable for set '%s' (%s); trying TCGdex fallback.",
                        ts.name, exc)
        if self._tcgdex is None:
            return None, None
        try:
            p2, pr2 = self._tcgdex.set_products_prices(ts.name, ts.abbreviation)
        except RuntimeError as exc:
            log.warning("TCGdex fallback also failed for set '%s' (%s).", ts.name, exc)
            return None, None
        if p2:
            log.warning("Set '%s' priced via TCGdex fallback (%d products) — TCGCSV was "
                        "unavailable; this set was SLOW (1 request/card).", ts.name, len(p2))
            return p2, pr2
        log.warning("No price source could provide set '%s'; skipping.", ts.name)
        return None, None

    def _alias_map(self, sets: list[TcgSet]) -> dict[str, TcgSet]:
        amap: dict[str, TcgSet] = {}
        for ts in sets:
            for a in set_aliases(ts.name) | {normalize_set(ts.abbreviation)}:
                if a:
                    amap.setdefault(a, ts)
        return amap

    # --- utilities -------------------------------------------------------
    def capture(self, url: str, out_path: str) -> None:
        """Save a rendered COMC page to disk (for offline selector tuning / fixtures)."""
        try:
            with ComcScraper(self.settings) as scraper:
                scraper.capture(url, out_path)
        except (ImportError, ComcAccessError) as exc:
            log.error("Capture unavailable: %s", exc)

    def warm_profile(self, wait_s: int = 30, url: str | None = None) -> bool:
        """Headful warm-up: clear Cloudflare once so the persistent profile stores the
        cf_clearance cookie. Re-run when the cookie expires (CF challenges again)."""
        self.settings.comc_headless = False
        try:
            with ComcScraper(self.settings) as scraper:
                ok = scraper.warm(url=url, wait_s=wait_s)
        except (ImportError, ComcAccessError) as exc:
            log.error("Warm-up unavailable: %s", exc)
            return False
        log.info("Profile dir: %s", self.settings.comc_profile_dir)
        return ok

    def _load_slug_catalog(self) -> dict:
        p = Path(__file__).resolve().parent / "comc_set_slugs.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def validate_slugs(self, revalidate: bool = False) -> dict[str, int]:
        """Live-validate catalog slugs still `validated: false` (page-1 scrape each).
        Returns {set_name: page-1 listing count} (-1 = Cloudflare block, 0 = empty)."""
        path = Path(__file__).resolve().parent / "comc_set_slugs.json"
        slugs = self._load_slug_catalog()
        pending = [
            (name, info) for name, info in slugs.items()
            if not name.startswith("_") and isinstance(info, dict) and info.get("slug")
            and (revalidate or not info.get("validated"))
        ]
        results: dict[str, int] = {}
        if not pending:
            log.info("Slug catalog: nothing pending validation.")
            return results
        log.info("Validating %d catalog slugs (one page-1 scrape each).", len(pending))
        today = datetime.date.today().isoformat()
        try:
            with ComcScraper(self.settings) as scraper:
                for name, info in pending:
                    year = str(info.get("year", ""))
                    era_path = f"{year}/{info['slug']}" if year else info["slug"]
                    count = 0
                    try:
                        for _page, listings in scraper.iter_listings(
                            search_term=None, era_path=era_path, max_pages=1,
                        ):
                            count = len(listings)
                            break
                    except ComcBlockedError:
                        log.warning("Slug '%s' (%s): Cloudflare block; left unvalidated.",
                                    name, era_path)
                        results[name] = -1
                        continue
                    results[name] = count
                    if count > 0:
                        info["validated"] = True
                        info["validated_at"] = today
                        info["page1_listings"] = count
                        log.info("Slug '%s' OK: %d listings on page 1.", name, count)
                    else:
                        log.warning("Slug '%s' (%s): 0 listings — slug likely wrong.",
                                    name, era_path)
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)
        path.write_text(json.dumps(slugs, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        ok = sum(1 for c in results.values() if c > 0)
        log.info("Slug validation done: %d/%d confirmed; catalog updated at %s.",
                 ok, len(pending), path)
        return results

    # --- filtros do funil --------------------------------------------------
    def _condition_ok(self, listing) -> bool:
        """NM-only (frota): condição da listagem tem que estar EXATAMENTE na allowlist
        (default só "nm"). Vazia/desconhecida → fora (nunca comparar com o preço NM)."""
        cond = (listing.condition or "").strip().lower()
        return cond in self.settings.comc_condition_allow

    def _variant_ok(self, listing) -> bool:
        """English-only: drop foreign-language sub-printings (Japanese/Korean/...)."""
        blob = f"{listing.set_hint or ''} {listing.raw_name or ''}".lower()
        return not any(v in blob for v in self.settings.comc_exclude_variants)

    def _price_ok(self, listing) -> bool:
        floor = self.settings.min_comc_price
        return floor <= 0 or listing.price >= floor

    def _chase_ok(self, product) -> bool:
        if not self.settings.chase_only:
            return True
        rarity = (product.rarity or "").strip().lower()
        return bool(rarity) and rarity not in self.settings.chase_exclude_rarities

    def _grade_ok(self, listing) -> bool:
        return bool(listing.grade) and listing.grade in self.settings.graded_allow

    def _slab_reference(self, deal: Deal) -> bool:
        """Troca a referência do slab pelo preço da NOTA no PriceCharting. False = sem
        referência confiável (o deal é descartado, nunca comparado com preço raw)."""
        grade = _grade_from_key(deal.listing.grade)
        if grade is None:
            return False
        pc_key, proxy = pc_price_key(grade)
        if not pc_key:
            return False
        ref = graded_reference(deal.product.name, deal.product.number, deal.product.set_name,
                               pc_key, cache_dir=self.settings.pc_cache_dir)
        if ref is None:
            return False
        deal.tcg_reference = ref.price
        deal.price_field_used = ref.grade_key
        deal.ref_source = "pricecharting-proxy" if proxy else "pricecharting"
        deal.ref_url = ref.url
        deal.margin = gross_margin(ref.price, deal.listing.price)
        return True

    def process_listing(self, listing, index: TcgIndex, ctx: str | None, kind: str,
                        stats: FunnelStats | None = None) -> Deal | None:
        """Funil completo de UMA listagem (spec §2-§7). Retorna o Deal aprovado
        (status OK ou MATCH_REVIEW) ou None; cada saída é contada em `stats`."""
        s = self.settings
        st = stats if stats is not None else self.stats
        st.bump("seen")
        if kind == KIND_RAW:
            if listing.graded:
                st.bump("skip_graded_in_raw")
                return None
            if not self._condition_ok(listing):
                st.bump("skip_condition")
                return None
        else:
            if not listing.graded:
                st.bump("skip_raw_in_slab")
                return None
            if not listing.grade:
                st.bump("skip_grade_unparsed")
                return None
            if not self._grade_ok(listing):
                st.bump("skip_grade_out_of_scope")
                return None
        if not self._variant_ok(listing):
            st.bump("skip_language")
            return None
        if not self._price_ok(listing):
            st.bump("skip_price_floor")
            return None
        hit = match_iconic(listing.raw_name)
        if s.iconic_only and hit is None:
            st.bump("skip_not_iconic")
            return None
        deal = match(listing, index, s, context_set_key=ctx)
        if deal is None:
            st.bump("match_failed")
            return None
        if not self._chase_ok(deal.product):
            st.bump("skip_rarity")
            return None
        hit = hit or match_iconic(deal.product.name)
        if s.iconic_only and hit is None:
            st.bump("skip_not_iconic")
            return None
        if hit is not None:
            deal.pokemon, deal.pokemon_rank = hit.name, hit.rank
        if kind == KIND_SLAB and not self._slab_reference(deal):
            st.bump("slab_no_reference")
            return None
        if deal.margin < s.min_gross_margin:
            st.bump("below_discount")
            return None
        status, reasons = classify_row(deal.as_row(), trust=s.trust_confidence)
        deal.status, deal.review_reasons = status, tuple(reasons)
        if deal.match_confidence < s.min_match_confidence:
            st.bump("low_confidence")
        elif status == "OK":
            st.bump("ok")
        else:
            st.bump("review")
        return deal

    # --- scan ----------------------------------------------------------------
    def _targets(self, era: str) -> list[tuple[TcgSet, str, str]]:
        slugs = self._load_slug_catalog()
        if not slugs:
            log.error("No COMC slug catalog (comc_scanner/comc_set_slugs.json).")
            return []
        groups = self.client.groups(force=self.settings.tcgcsv_force_refresh)
        all_sets = select_sets(groups, self.settings, era)
        by_norm = {normalize_set(ts.name): ts for ts in all_sets}
        amap = self._alias_map(all_sets)
        targets = []
        for tcg_name, info in slugs.items():
            if not isinstance(info, dict) or not info.get("validated") or not info.get("slug"):
                continue
            # EXACT name/alias match only (a containment fallback once paired WotC
            # "Base Set" with "SV01: Scarlet & Violet Base Set" — cross-era FP).
            ts = by_norm.get(normalize_set(tcg_name)) or amap.get(normalize_set(tcg_name))
            if ts is not None:
                targets.append((ts, str(info.get("year", "")), info["slug"]))
        return targets

    def run_scan(self, era: str, label: str, best: BestDeals | None = None) -> BestDeals:
        """Scan de todos os sets validados da era (respeitando `set_allowlist`), duas
        passadas por set (raw + slabs conforme `scan_raw`/`scan_slabs`). Sem cursor:
        cada run começa do zero e só usa dados do dia."""
        s = self.settings
        best = best or BestDeals(s.top_n)
        targets = self._targets(era)
        if not targets:
            log.error("Nenhum set validado intersecta a era '%s' / allowlist.", era)
            self.reporter.flush(best.qualifying(), label, best.low_conf(), stats=self.stats)
            return best
        index = TcgIndex()
        self._ensure_index([t[0] for t in targets], index)
        gate, thr = s.min_match_confidence, s.min_gross_margin
        deadline = (time.monotonic() + s.max_run_seconds) if s.max_run_seconds else None
        next_flush = time.time() + s.scan_interval_s
        passes = ([(KIND_RAW, False)] if s.scan_raw else []) + \
                 ([(KIND_SLAB, True)] if s.scan_slabs else [])
        log.info("Scan '%s': %d sets (era %s), passadas: %s, desconto mín. %d%%, "
                 "Pokémon icônicos: %s.", label, len(targets), era,
                 "+".join(k for k, _ in passes), s.min_discount_percent,
                 "só lista" if s.iconic_only else "todos")
        consecutive_blocked = 0
        try:
            with ComcScraper(s) as scraper:
                for ts, year, slug in targets:
                    ctx = normalize_set(ts.name)
                    era_path = f"{year}/{slug}" if year else slug
                    set_yielded = False
                    for kind, graded in passes:
                        try:
                            for _page, listings in scraper.iter_listings(
                                search_term=None, era_path=era_path,
                                max_pages=s.max_pages_per_set, graded=graded,
                            ):
                                set_yielded = True
                                for L in listings:
                                    deal = self.process_listing(L, index, ctx, kind)
                                    if deal:
                                        deal.era = ts.era
                                        best.add(deal, gate, thr)
                                if time.time() >= next_flush:
                                    self.reporter.flush(best.qualifying(), label,
                                                        best.low_conf(), stats=self.stats)
                                    next_flush += s.scan_interval_s
                                if self._stop or (deadline and time.monotonic() >= deadline):
                                    log.info("Budget/stop hit at set '%s' (%s).", ts.name, kind)
                                    self.reporter.flush(best.qualifying(), label,
                                                        best.low_conf(), stats=self.stats)
                                    return best
                        except ComcBlockedError:
                            if set_yielded:
                                consecutive_blocked = 0
                                log.warning("COMC set '%s' (%s) blocked mid-pagination; "
                                            "kept partial.", ts.name, kind)
                            else:
                                consecutive_blocked += 1
                                self.stats.bump("comc_errors")
                                log.warning("COMC set '%s' blocked (%d in a row).",
                                            ts.name, consecutive_blocked)
                                if consecutive_blocked >= 3:
                                    log.error("Cloudflare blocked %d sets in a row; aborting.",
                                              consecutive_blocked)
                                    self.reporter.flush(best.qualifying(), label,
                                                        best.low_conf(), stats=self.stats)
                                    return best
                    if set_yielded:
                        consecutive_blocked = 0
                    log.info("Scanned set '%s' via slug '%s'.", ts.name, slug)
                    if self._stop:
                        break
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)
            self.stats.bump("comc_errors")

        self.reporter.flush(best.qualifying(), label, best.low_conf(), stats=self.stats)
        log.info("Scan '%s' done; %d deals (%d OK, %d MATCH_REVIEW, %d low-confidence).",
                 label, len(best.qualifying()), self.stats["ok"], self.stats["review"],
                 self.stats["low_confidence"])
        return best
