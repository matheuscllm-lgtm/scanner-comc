"""Orquestração do scanner único COMC → referência de preço → funil → entrega.

Fluxo por set (catálogo ``comc_set_slugs.json``, agrupado em ``groups.py``):

    COMC set-path browse (2 passadas: cartas soltas ``aUngraded`` + slabs ``aGraded``)
    → funil ``process_listing`` (tipo/condição NM/idioma EN/piso US$/Pokémon icônico)
    → ``matcher.match`` (identifica a carta no TCGplayer; confiança 0-1)
    → referência: raw NM = TCGplayer market (tcgcsv/TCGdex; EX-NM vai para revisão sem
      preço); raw LP = mediana de
      vendas LP (PriceCharting, ≥3, nunca vs NM); slab = mediana de vendas concluídas da
      MESMA certificadora+nota+variante (PriceCharting; coluna/nota vizinha nunca é referência)
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
from .grading import Grade
from .iconic import match_iconic
from .margin import gross_margin
from .matcher import match
from .models import Deal
from .normalize import normalize_set, set_aliases
from .pricecharting_client import (PcError, graded_reference, product_page_url,
                                   raw_condition_reference, raw_plausibility,
                                   variant_tokens)
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

    def add(self, deal: Deal, gate: float, threshold: float) -> bool:
        """True = listagem NOVA; False = duplicata (mesma listagem vista de novo, ex.
        paginação com empate de preço) — o chamador conta em `dedup_dropped` para o
        funil bater com a tabela."""
        if deal.margin < threshold:
            return False
        bucket = self.best if deal.match_confidence >= gate else self.low
        key = self._key(deal)
        cur = bucket.get(key)
        if cur is None:
            bucket[key] = deal
            return True
        if deal.margin > cur.margin:
            bucket[key] = deal
        return False

    @staticmethod
    def _ranked(deals: list[Deal]) -> list[Deal]:
        return sorted(deals, key=lambda d: sort_key(d.as_row()))

    def qualifying(self) -> list[Deal]:
        return self._ranked(list(self.best.values()))

    def low_conf(self) -> list[Deal]:
        return self._ranked(list(self.low.values()))[: self.top_n or None]


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
        self._pc_errors = 0      # falhas SEGUIDAS do PriceCharting
        self._pc_down = False    # ≥PC_MAX_CONSECUTIVE_ERRORS → slabs suspensos no run
        self.aborted = False     # run interrompido (browser fechado / COMC inacessível)
        self._pc_link_errors = 0  # falhas SEGUIDAS do link [referência] (cosmético)
        self._pc_link_down = False  # ≥PC_LINK_MAX_ERRORS → só o link é suspenso
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

    def _load_slug_catalog(self, path: Path | None = None) -> dict:
        p = path or (Path(__file__).resolve().parent / "comc_set_slugs.json")
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.error("Catálogo de slugs CORROMPIDO/ilegível (%s): %s", p, exc)
                return {}
        return {}

    MIN_OWN_SET_SHARE = 0.8  # página 1 tem de ser do PRÓPRIO set (subsets dele contam)

    _KEY_STRONG = frozenset({"pokemon", "the", "and", "tcg"})
    _KEY_WEAK = frozenset({"base", "set"})      # sufixo/edição genéricos ("… - Base")
    _KEY_SERIES = ("ex", "xy", "sm", "swsh", "sv")
    _KEY_ALIAS = (("sm", frozenset({"sun", "moon"})), ("swsh", frozenset({"sword", "shield"})),
                  ("sv", frozenset({"scarlet", "violet"})))

    @classmethod
    def _alias(cls, toks: set[str]) -> set[str]:
        for sigla, extenso in cls._KEY_ALIAS:
            if sigla in toks:
                toks = (toks - {sigla}) | set(extenso)  # "SM Base Set" ↔ "Sun  Moon - Base"
        return toks

    @classmethod
    def _tokens(cls, text: str, alias: bool = True) -> set[str]:
        import re as _re
        import unicodedata
        t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
        t = t.replace("&", " ").replace("-", " ").replace(":", " ").replace("_", " ")
        toks = set(_re.findall(r"[a-z0-9]+", t)) - cls._KEY_STRONG
        return cls._alias(toks) if alias else toks

    @classmethod
    def _set_key(cls, text: str) -> tuple[frozenset[str], bool]:
        """(chave, exata). Chave = tokens distintivos do nome do set. Quando o nome só tem
        palavras genéricas/de série ("Base Set", "XY Base Set", "SM Base Set") ou só
        dígitos ("Base Set 2"), a comparação é EXATA (núcleo do hint == chave), senão
        {base} casaria qualquer slug "…_-_Base" de uma categoria-pai (review PR B)."""
        import re as _re
        toks = cls._tokens(text, alias=False)  # decisão sobre as siglas originais
        series_re = _re.compile(r"(" + "|".join(cls._KEY_SERIES) + r")\d*")
        distinct = {w for w in toks - cls._KEY_WEAK if not series_re.fullmatch(w)}
        if distinct and not all(w.isdigit() for w in distinct):
            return frozenset(cls._alias(distinct)), False
        return frozenset(cls._alias(toks - cls._KEY_WEAK)), True

    @classmethod
    def _hint_tokens(cls, text: str) -> set[str]:
        """Tokens do `set_hint` da listagem (mesma normalização/aliases da chave)."""
        return cls._tokens(text)

    @classmethod
    def own_set_share(cls, set_name: str, listings) -> float:
        """Fração das listagens cujo `set_hint` é do próprio set: chave ⊆ hint (subsets
        do set — Reverse Foil, idioma — contam; OUTRO set não); nomes genéricos exigem
        núcleo do hint (sem base/set) IGUAL à chave."""
        key, exact = cls._set_key(set_name)
        if not listings:
            return 0.0
        if exact:
            hits = sum(1 for L in listings if (cls._hint_tokens(L.set_hint) - cls._KEY_WEAK) == set(key))
        else:
            hits = sum(1 for L in listings if key <= cls._hint_tokens(L.set_hint))
        return hits / len(listings)

    def validate_slugs(self, revalidate: bool = False,
                       catalog_path: Path | None = None) -> dict[str, int]:
        """Live-validate catalog slugs still `validated: false` (page-1 scrape each).
        Returns {set_name: page-1 listing count} (-1 = Cloudflare block, 0 = empty).
        Só valida se ≥MIN_OWN_SET_SHARE da página 1 for do próprio set: slug errado ou
        acentuado cai numa categoria-pai da COMC (ano inteiro) e mistura sets."""
        path = catalog_path or (Path(__file__).resolve().parent / "comc_set_slugs.json")
        slugs = self._load_slug_catalog(path)
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
                    page1: list = []
                    try:
                        for _page, listings in scraper.iter_listings(
                            search_term=None, era_path=era_path, max_pages=1,
                        ):
                            count = len(listings)
                            page1 = list(listings)
                            break
                    except ComcBlockedError:
                        log.warning("Slug '%s' (%s): Cloudflare block; left unvalidated.",
                                    name, era_path)
                        results[name] = -1
                        continue
                    results[name] = count
                    share = round(self.own_set_share(name, page1), 2)
                    info["page1_own_share"] = share
                    if count > 0 and share >= self.MIN_OWN_SET_SHARE:
                        info["validated"] = True
                        info["validated_at"] = today
                        info["page1_listings"] = count
                        log.info("Slug '%s' OK: %d listings on page 1 (%.0f%% do próprio set).",
                                 name, count, share * 100)
                    elif count > 0:
                        info["validated"] = False
                        info.pop("validated_at", None)   # metadados do sucesso antigo saem
                        info.pop("page1_listings", None)
                        log.warning("Slug '%s' (%s): %d listagens mas só %.0f%% do próprio set — "
                                    "categoria-pai da COMC; slug NÃO validado.",
                                    name, era_path, count, share * 100)
                    else:
                        log.warning("Slug '%s' (%s): 0 listings — slug likely wrong.",
                                    name, era_path)
        except ComcAccessError as exc:
            log.error("COMC access blocked: %s", exc)
        path.write_text(json.dumps(slugs, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        ok = sum(1 for name, c in results.items()
                 if c > 0 and slugs.get(name, {}).get("validated") is True)
        log.info("Slug validation done: %d/%d confirmed; catalog updated at %s.",
                 ok, len(pending), path)
        return results

    # --- filtros do funil --------------------------------------------------
    def _condition_ok(self, listing, era: str = "") -> bool:
        """Condição por igualdade: só "nm" (em todas as eras, política 2026-09-06 — EX-NM
        vai para a revisão sem preço presumido, mesmo que um .env antigo a liste).
        Vazia/desconhecida → fora (nunca comparar com o preço NM)."""
        cond = (listing.condition or "").strip().lower()
        allow = (self.settings.comc_condition_allow_vintage if era == "vintage"
                 else self.settings.comc_condition_allow)
        return cond == "nm" and cond in allow

    def _variant_ok(self, listing) -> bool:
        """English-only: drop foreign-language sub-printings (Japanese/Korean/...)."""
        blob = f"{listing.set_hint or ''} {listing.raw_name or ''}".lower()
        return not any(v in blob for v in self.settings.comc_exclude_variants)

    def _price_ok(self, listing) -> bool:
        floor = self.settings.min_comc_price
        return floor <= 0 or listing.price >= floor

    def _price_ceiling_ok(self, listing) -> bool:
        """Teto de orçamento por carta (`--max-price`); 0 desliga. Corta ANTES da
        consulta ao PriceCharting (1 request/carta)."""
        cap = self.settings.max_comc_price
        return cap <= 0 or listing.price <= cap

    def _chase_ok(self, product) -> bool:
        if not self.settings.chase_only:
            return True
        rarity = (product.rarity or "").strip().lower()
        return bool(rarity) and rarity not in self.settings.chase_exclude_rarities

    def _grade_ok(self, listing) -> bool:
        return bool(listing.grade) and listing.grade in self.settings.graded_allow

    PC_MAX_CONSECUTIVE_ERRORS = 5
    PC_LINK_MAX_ERRORS = 3  # breaker PRÓPRIO do link (nunca derruba slabs/LP)

    @staticmethod
    def _listing_variants(listing) -> frozenset[str]:
        """Tokens de variante da listagem COMC (reverse, 1st, shadowless, promo…). A venda
        comparável precisa ter EXATAMENTE o mesmo conjunto — nunca associação aproximada
        silenciosa entre variantes."""
        blob = " ".join(p for p in (listing.raw_name, listing.description,
                                    listing.grade_label, listing.set_hint) if p)
        return variant_tokens(blob)

    def _pc_guarded(self, fn, *args, **kwargs):
        """Chama a fonte PriceCharting sob o circuit breaker.

        Retorna ("ok", ref) | ("no_reference", None) (a carta não tem vendas comparáveis
        suficientes — decisão da fonte, não erro) | ("pc_error", None) (a FONTE falhou:
        rede/bloqueio/layout — contado à parte, nunca confundido com "sem venda")."""
        if self._pc_down:
            return "pc_error", None
        try:
            ref = fn(*args, **kwargs)
        except PcError as exc:
            self._pc_errors += 1
            log.warning("PriceCharting falhou (%d seguidas): %s", self._pc_errors, exc)
            if self._pc_errors >= self.PC_MAX_CONSECUTIVE_ERRORS:
                self._pc_down = True
                log.error("PriceCharting: %d falhas seguidas — referências de vendas suspensas "
                          "neste run (slabs e raw LP NÃO são avaliados a partir daqui).",
                          self._pc_errors)
            return "pc_error", None
        self._pc_errors = 0
        return ("ok", ref) if ref is not None else ("no_reference", None)

    @staticmethod
    def _apply_sales_ref(deal: Deal, ref, source: str) -> None:
        """Troca a referência do deal pela mediana de vendas (slab ou LP). Só aqui um
        deal muda de referência; a comparação final usa exclusivamente esta mediana."""
        deal.tcg_reference = ref.price
        deal.price_field_used = ref.label
        deal.ref_source = source
        deal.ref_url = ref.url
        deal.ref_sales_median = ref.price
        deal.ref_n_sales = ref.n_sales
        deal.ref_liquidity = ref.liquidity
        deal.ref_window_days = ref.window_days
        deal.ref_column_price = ref.column_price
        deal.margin = gross_margin(ref.price, deal.listing.price)

    def _slab_reference(self, deal: Deal) -> str:
        """Referência do slab = mediana de vendas concluídas da MESMA carta, variante,
        certificadora, nota e subcategoria (PriceCharting agrega; coluna exata e bucket
        genérico NUNCA são referência). Retorna "ok" | "no_reference" | "pc_error" |
        "malformed"; só "ok" muta o deal. Um slab nunca é comparado com preço raw."""
        grade = _grade_from_key(deal.listing.grade)
        if grade is None:
            log.error("Slab com nota ilegível: %r (%s)", deal.listing.grade, deal.listing.url)
            return "malformed"
        outcome, ref = self._pc_guarded(
            graded_reference, deal.product.name, deal.product.number, deal.product.set_name,
            grade, cache_dir=self.settings.pc_cache_dir,
            variants=self._listing_variants(deal.listing))
        if outcome == "ok":
            self._apply_sales_ref(deal, ref, "pricecharting-sales")
        return outcome

    def _lp_reference(self, deal: Deal) -> str:
        """Referência de carta solta LP = mediana de ≥3 vendas explicitamente LP/Lightly
        Played da mesma carta e variante (nunca o preço NM). "ok" | "no_reference" |
        "pc_error"."""
        outcome, ref = self._pc_guarded(
            raw_condition_reference, deal.product.name, deal.product.number,
            deal.product.set_name, "LP", cache_dir=self.settings.pc_cache_dir,
            variants=self._listing_variants(deal.listing))
        if outcome == "ok":
            self._apply_sales_ref(deal, ref, "pricecharting-sales-lp")
        return outcome

    def _raw_plausibility(self, deal: Deal, st: FunnelStats) -> None:
        """Teste de plausibilidade da referência raw NM (operador, 2026-09-06): mediana
        de ≥3 vendas de carta SOLTA da mesma carta/variante no PriceCharting, guardada
        SÓ como sinal (`raw_sales_*`); `classify_row` manda para MATCH_REVIEW quando o
        TCGplayer market diverge >40% dela. O preço NUNCA é trocado. Só roda quando a
        página da carta já foi resolvida para o link (mesma busca; +1 request cacheado).
        Falha da fonte é contada e ignorada — nunca derruba slabs/LP nem o run."""
        try:
            ref = raw_plausibility(deal.product.name, deal.product.number, deal.product.set_name,
                                   cache_dir=self.settings.pc_cache_dir,
                                   variants=self._listing_variants(deal.listing))
        except PcError as exc:
            st.bump("raw_plausibility_error")
            log.warning("PriceCharting (plausibilidade raw) falhou: %s", exc)
            return
        if ref is None:
            st.bump("raw_plausibility_missing")
            return
        deal.raw_sales_median, deal.raw_sales_n, deal.raw_sales_label = ref.price, ref.n_sales, ref.label
        st.bump("raw_plausibility_ok")

    def _is_lp(self, listing) -> bool:
        return self.settings.lp_with_reference and \
            (listing.condition or "").strip().lower() == "lp"

    def process_listing(self, listing, index: TcgIndex, ctx: str | None, kind: str,
                        stats: FunnelStats | None = None, era: str = "") -> Deal | None:
        """Funil completo de UMA listagem (spec §2-§7). Retorna o Deal aprovado
        (status OK ou MATCH_REVIEW) ou None; cada saída é contada em `stats`."""
        s = self.settings
        st = stats if stats is not None else self.stats
        st.bump("seen")
        lp_candidate = False
        condition_review = kind == KIND_RAW and not listing.graded and (listing.condition or "").strip().lower() == "ex-nm"
        if kind == KIND_RAW:
            if listing.graded:
                st.bump("skip_graded_in_raw")
                return None
            if not self._condition_ok(listing, era):
                # LP só segue no funil para buscar a SUA referência (vendas LP); nunca
                # é comparada com o preço NM.
                if condition_review:
                    pass  # sem preço NM/LP: vai para revisão após os filtros básicos
                elif self._is_lp(listing):
                    lp_candidate = True
                else:
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
        if not self._price_ceiling_ok(listing):
            st.bump("skip_price_ceiling")
            return None
        hit = match_iconic(listing.raw_name)
        if s.iconic_only and hit is None:
            st.bump("skip_not_iconic")
            return None
        if condition_review:
            st.bump("condition_review")
            self.reporter.add_unpriced(listing, "EX-NM: condição exige revisão; sem referência equivalente")
            return None
        deal = match(listing, index, s, context_set_key=ctx)
        if deal is None:
            st.bump("match_failed")
            self.reporter.add_unpriced(listing, "carta/variante sem identificação segura no catálogo")
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
        if kind == KIND_SLAB:
            outcome = self._slab_reference(deal)
            if outcome != "ok":
                self.reporter.add_unpriced(listing, "slab: " + outcome)
                st.bump({"no_reference": "slab_no_reference", "pc_error": "slab_pc_error",
                         "malformed": "slab_grade_malformed"}[outcome])
                return None
        elif lp_candidate:
            # Pré-filtro SEGURO (operador): a referência NM do TCGplayer é só um TETO —
            # LP vale menos que NM, então `preço > NM × (1 − desconto mín.)` já elimina
            # sem consultar a fonte. A comparação final usa SÓ a referência LP.
            cap = deal.tcg_reference * (1.0 - s.min_gross_margin)
            if deal.tcg_reference <= 0 or deal.listing.price > cap:
                st.bump("lp_prefilter")
                return None
            outcome = self._lp_reference(deal)
            if outcome != "ok":
                self.reporter.add_unpriced(listing, "LP: " + outcome)
                st.bump({"no_reference": "lp_no_reference", "pc_error": "lp_pc_error"}[outcome])
                return None
        if deal.margin < s.min_gross_margin:
            st.bump("below_discount")
            return None
        if deal.ref_source == "tcgplayer":
            # Link [referência] da carta solta = página do PriceCharting (mais informativa:
            # vendas eBay, gráfico, PSA 10/9) — só para deals aprovados (1-2 requests cada).
            # O PREÇO continua o TCGplayer market; sem página/erro → link do TCGplayer.
            # Breaker PRÓPRIO: falha do link (cosmético) nunca suspende slabs/LP.
            url = None
            if self._pc_link_down:
                st.bump("pc_link_error")
            else:
                try:
                    url = product_page_url(deal.product.name, deal.product.number,
                                           deal.product.set_name, cache_dir=s.pc_cache_dir)
                except PcError as exc:
                    self._pc_link_errors += 1
                    st.bump("pc_link_error")
                    log.warning("PriceCharting (link) falhou (%d seguidas): %s", self._pc_link_errors, exc)
                    if self._pc_link_errors >= self.PC_LINK_MAX_ERRORS:
                        self._pc_link_down = True
                        log.error("PriceCharting (link): %d falhas seguidas — links [referência] "
                                  "das cartas soltas caem no TCGplayer daqui em diante.",
                                  self._pc_link_errors)
                else:
                    self._pc_link_errors = 0
                    if url:
                        deal.ref_url = url
                    else:
                        st.bump("pc_link_missing")
            if url and s.raw_plausibility:
                self._raw_plausibility(deal, st)
        status, reasons = classify_row(deal.as_row(), trust=s.trust_confidence,
                                       extreme_pct=s.extreme_discount_percent)
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
        selected = {t[0].group_id for t in targets}
        missing = [ts.name for ts in all_sets if ts.group_id not in selected]
        self.reporter.coverage[era] = {"selected_sets": [t[0].name for t in targets], "without_validated_path": missing}
        if missing:
            log.warning("Cobertura parcial do catálogo: %d sets sem caminho COMC validado.", len(missing))
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
                        english_seen = 0  # listagens em inglês vistas nesta passada
                        try:
                            for _page, listings in scraper.iter_listings(
                                search_term=None, era_path=era_path,
                                max_pages=s.max_pages_per_set, graded=graded,
                            ):
                                set_yielded = True
                                for L in listings:
                                    if self._variant_ok(L):
                                        english_seen += 1
                                    try:
                                        deal = self.process_listing(L, index, ctx, kind, era=ts.era)
                                    except Exception:  # noqa: BLE001 — 1 listagem não derruba o run
                                        self.stats.bump("listing_errors")
                                        log.exception("Listagem falhou e foi pulada: %s", L.url)
                                        continue
                                    if deal:
                                        deal.era = ts.era
                                        if not best.add(deal, gate, thr):
                                            self.stats.bump("dedup_dropped")
                                if time.time() >= next_flush:
                                    self.reporter.flush(best.qualifying(), label,
                                                        best.low_conf(), stats=self.stats)
                                    next_flush += s.scan_interval_s
                                # `--max-english`: o corte conta só listagens INGLESAS
                                # válidas (as japonesas descartadas não contam) — sem a
                                # flag, varre até a última página.
                                if s.max_english_per_set and english_seen >= s.max_english_per_set:
                                    self.stats.bump("sets_capped_max_english")
                                    log.info("Set '%s' (%s): %d listagens inglesas — teto "
                                             "--max-english atingido.", ts.name, kind, english_seen)
                                    break
                                if self._stop or (deadline and time.monotonic() >= deadline):
                                    log.info("Budget/stop hit at set '%s' (%s).", ts.name, kind)
                                    return best
                        except ComcBlockedError:
                            if set_yielded:
                                consecutive_blocked = 0
                                self.stats.bump("comc_partial_sets")
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
                                    return best
                    if set_yielded:
                        consecutive_blocked = 0
                    log.info("Scanned set '%s' via slug '%s'.", ts.name, slug)
                    if self._stop:
                        break
        except ComcAccessError as exc:
            # Browser fechado / COMC inacessível: o run ABORTA (sets restantes não foram
            # varridos) — contador próprio, distinto do bloqueio Cloudflare por set.
            log.error("Scan '%s' ABORTADO — COMC inacessível: %s", label, exc)
            self.stats.bump("comc_aborted")
            self.aborted = True
        finally:
            # SEMPRE grava o que foi encontrado (inclusive em erro inesperado): o JSON
            # `_latest` nunca fica desatualizado em silêncio.
            self.reporter.flush(best.qualifying(), label, best.low_conf(), stats=self.stats)
            log.info("Scan '%s': %d deals (%d OK, %d MATCH_REVIEW, %d low-confidence, "
                     "%d erros de listagem, %d erros PriceCharting).",
                     label, len(best.qualifying()), self.stats["ok"], self.stats["review"],
                     self.stats["low_confidence"], self.stats["listing_errors"],
                     self.stats["slab_pc_error"])
        return best
