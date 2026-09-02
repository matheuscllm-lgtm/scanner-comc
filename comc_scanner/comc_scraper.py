"""COMC listing scraper.

COMC is behind a Cloudflare managed challenge (a plain HTTP GET returns 403), so we
drive a real Chromium via Playwright, optionally seeded with the user's session
cookie, navigate the verified comma-faceted browse URLs, and parse the rendered HTML.

Browse-URL grammar (verified), e.g.:
  https://www.comc.com/Cards/Pokemon,=evolving+skies,sl,fb,aUngraded,rCOMC,gEX-NM,i100,p3
  sl=sort lowest price, fb=Buy-It-Now, aUngraded=exclude graded, g<band>=condition,
  i<n>=items/page, p<n>=page, ,=<term>=text search.

COMC's listing DOM was reverse-engineered from real captured browse pages (2026-06-08).
Each result on a `/Cards/Pokemon,...` browse page renders as a `<div class="carddata">`
block whose card-detail link encodes everything we need in its path:

    /Cards/Pokemon/<year>/<Set_Name>/<Number>/<Card_Name>/<id>/<Graded>/<Source>/<Condition>
    e.g. /Cards/Pokemon/1999/Topps_..._Series_1_-_Base/TV8/Gary_Oak/4341265/Ungraded/COMC/EX-NM

`parse_page` tries schema.org JSON-LD first (used by the synthetic test fixture); real
pages carry no JSON-LD, so it falls through to `_parse_dom`, which segments the page into
carddata blocks and reads the set/number/name/condition from the detail URL plus the
price and quantity from the `listprice`/`qty` markup. Validate against a saved page with
`parse-file --html` / `dry-run --html`.
"""
from __future__ import annotations

import html as _html
import json
import logging
import random
import re
import time
import urllib.parse
import urllib.robotparser
from pathlib import Path
from typing import Iterator

from .config import CACHE_DIR, Settings
from .grading import parse_grade
from .models import ComcListing
from .normalize import detect_graded

log = logging.getLogger("comc_scanner.comc")

COMC_BASE = "https://www.comc.com"
# A normal desktop browser UA. NB: COMC's robots.txt allows "*" but blocks AI-training
# crawlers (GPTBot, CCBot, ClaudeBot, ...). Never set the UA to one of those tokens.
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class ComcAccessError(RuntimeError):
    """Raised when COMC access is disallowed (e.g. by robots.txt)."""


class ComcBlockedError(RuntimeError):
    """Raised when Cloudflare keeps blocking a COMC page after the retries."""


def _import_playwright():
    """Prefer patchright (stealth fork — better Cloudflare evasion); fall back to playwright."""
    try:
        from patchright.sync_api import sync_playwright  # type: ignore
        return sync_playwright, "patchright"
    except Exception:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright, "playwright"


def robots_allowed(target_url: str, user_agent: str = BROWSER_UA) -> tuple[bool, str]:
    """Check COMC robots.txt for `user_agent`. Fails open (allowed) if it can't be read."""
    import requests  # lazy: keep the parse-only path free of the requests dependency

    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = requests.get(
            f"{COMC_BASE}/robots.txt", headers={"User-Agent": user_agent}, timeout=15
        )
        resp.raise_for_status()
        rp.parse(resp.text.splitlines())
    except Exception as exc:  # noqa: BLE001 - don't block scanning on a robots fetch error
        return True, f"robots.txt not read ({exc}); proceeding"
    allowed = rp.can_fetch(user_agent, target_url)
    return allowed, ("allowed by robots.txt" if allowed else "DISALLOWED by robots.txt")


_PRICE_RE = re.compile(r"\$\s?([0-9][0-9,]*\.?[0-9]{0,2})")
_NUM_RE = re.compile(r"#\s?([A-Za-z]*\d[\w/]*)")
# A bare collector number anywhere in a title, e.g. "4/102", "021/128", "TG12/TG30".
_BARE_NUM_RE = re.compile(r"\b([A-Za-z]{0,3}\d+/[A-Za-z]{0,3}\d+)\b")


def _extract_number(text: str) -> str | None:
    m = _NUM_RE.search(text or "")
    if m:
        return m.group(1)
    m = _BARE_NUM_RE.search(text or "")
    return m.group(1) if m else None


def build_browse_url(
    settings: Settings, search_term: str | None = None,
    era_path: str | None = None, page: int = 1, items: int = 100,
    graded: bool = False,
) -> str:
    """Browse URL. `graded=True` = vitrine de SLABS (`aGraded`, sem facet de banda —
    a nota vem do path de cada listing); `False` = cartas soltas (`aUngraded`)."""
    path = "/Cards/Pokemon"
    if era_path:
        path += "/" + urllib.parse.quote(era_path)
    segments: list[str] = []
    if search_term:
        segments.append("=" + urllib.parse.quote_plus(search_term))
    segments.append(settings.comc_sort or "sh")  # sort: sh=highest first, sl=lowest
    segments.append("fb")  # Buy-It-Now only
    segments.append("aGraded" if graded else "aUngraded")
    # Seller-repository filter. `rCOMC` (COMC's RCR consignment repo) is ESSENTIALLY EMPTY
    # for vintage WotC ungraded — restricting to it makes the scanner find nothing. Default
    # to no r-filter so all seller repos (rOther/rCOMC_CCG/...) are seen. Set
    # COMC_SELLER_REPO=COMC to opt back in.
    if settings.comc_seller_repo:
        segments.append("r" + settings.comc_seller_repo)
    if settings.comc_condition_band and not graded:
        segments.append("g" + settings.comc_condition_band)
    segments.append(f"i{items}")
    segments.append(f"p{page}")
    return f"{COMC_BASE}{path}," + ",".join(segments)


def _to_float(price_text: str) -> float | None:
    m = _PRICE_RE.search(price_text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _listing_from_fields(
    name: str, price: float, url: str, set_hint: str | None = None,
    number_hint: str | None = None, condition: str = "", quantity: int = 1,
    seller: str | None = None, image_url: str | None = None,
) -> ComcListing:
    graded, grader = detect_graded(f"{condition} {name}")
    if not number_hint:
        number_hint = _extract_number(name)
    return ComcListing(
        raw_name=name.strip(), price=price, url=url, set_hint=set_hint,
        number_hint=number_hint, condition=condition.strip(), graded=graded,
        grader=grader, quantity=quantity, seller=seller, image_url=image_url,
    )


def _parse_jsonld(html: str) -> list[ComcListing]:
    """Parse schema.org Product/Offer JSON-LD blocks if COMC emits them."""
    out: list[ComcListing] = []
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, flags=re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict) or it.get("@type") not in ("Product", "Offer"):
                continue
            offer = it.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            price = offer.get("price") if isinstance(offer, dict) else None
            url = it.get("url") or (offer.get("url") if isinstance(offer, dict) else "") or ""
            if it.get("name") and price:
                try:
                    out.append(_listing_from_fields(it["name"], float(price), url))
                except (TypeError, ValueError):
                    continue
    return out


# --- Real COMC browse-page DOM (reverse-engineered 2026-06-08) --------------
# Each result is a `<div class="carddata">` block. The card-detail link in it carries
# the set/number/name/condition in its path; price and stock live in the listprice markup.
_CARDDATA_SPLIT = re.compile(r'<div\s+class="carddata"\s*>', re.IGNORECASE)
# .../<year>/<set>/<number>/<name>/<id>/<Ungraded|Graded>/<source>/<condition>
# Host is optional: Firecrawl's rawHtml carries absolute URLs, but a live browser's
# serialized DOM (Playwright/patchright page.content()) uses RELATIVE hrefs (/Cards/...).
_DETAIL_URL_RE = re.compile(
    r'href="((?:https?://(?:www\.)?comc\.com)?/Cards/Pokemon/'
    r'([^"/]+)/([^"]+?)/([^"/]+)/([^"/]+)/(\d+)/(Ungraded|Graded)/([^"/]+)/([^"/]+))"',
    re.IGNORECASE,
)
_DESC_RE = re.compile(r'<div\s+class="description"\s*>\s*(.*?)\s*</div>', re.DOTALL | re.IGNORECASE)
# Título do listing: `<h3 class="title"><a ...>Pidgeotto [PSA 9 MINT]</a></h3>` — em slabs o
# colchete traz empresa + nota + qualificador ("CGC 10 Pristine" vs "CGC 10 Gem Mint").
_TITLE_RE = re.compile(r'<h3\s+class="title"\s*>.*?<a[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TITLE_GRADE_RE = re.compile(r"\[([^\]]+)\]\s*$")
_QTY_RE = re.compile(r'<div\s+class="qty"\s*>\s*(\d+)\s+from', re.IGNORECASE)
_LISTPRICE_RE = re.compile(r'class="listprice', re.IGNORECASE)


def _clean(text: str) -> str:
    """Decode HTML entities + collapse whitespace from a snippet of inner HTML."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _deslug(segment: str) -> str:
    """A COMC URL path segment -> human text ('Gary_Oak' / 'Farfetch%27d' -> 'Farfetch'd')."""
    return _html.unescape(urllib.parse.unquote(segment or "")).replace("_", " ").strip()


def _parse_dom(html: str) -> list[ComcListing]:
    """Parse a real COMC browse page into listings (one per `carddata` block)."""
    out: list[ComcListing] = []
    blocks = _CARDDATA_SPLIT.split(html)
    if len(blocks) <= 1:
        return _parse_dom_loose(html)  # unfamiliar layout: best-effort fallback
    for block in blocks[1:]:
        m = _DETAIL_URL_RE.search(block)
        if not m:
            continue
        url, _year, set_seg, number_seg, name_seg, item_id, graded_seg, src_seg, cond_seg = m.groups()
        if url.startswith("/"):  # relative href (live-browser DOM) -> absolute
            url = COMC_BASE + url
        # Price: the first $-amount in the listprice region (falls back to first in block).
        lp = _LISTPRICE_RE.search(block)
        price = _to_float(block[lp.end():] if lp else block)
        if price is None:
            continue
        qty_m = _QTY_RE.search(block)
        name = _deslug(name_seg)
        set_hint = _deslug(set_seg)
        condition = _deslug(cond_seg)  # e.g. "EX-NM"
        listing = _listing_from_fields(
            name, price, url, set_hint=set_hint, number_hint=_deslug(number_seg),
            condition=condition, quantity=int(qty_m.group(1)) if qty_m else 1,
        )
        listing.item_id = item_id
        # The URL says Ungraded/Graded explicitly; trust it over keyword sniffing.
        if graded_seg.lower() == "graded":
            listing.graded = True
            # Slab: `/Graded/<grader>/<nota>` no path + `[CGC 10 Pristine]` no título.
            title_m = _TITLE_RE.search(block)
            title = _clean(title_m.group(1)) if title_m else ""
            grade = parse_grade(src_seg, cond_seg, title)
            if grade is not None:
                listing.grader = grade.grader
                listing.grade = grade.key
            label_m = _TITLE_GRADE_RE.search(title)
            listing.grade_label = label_m.group(1) if label_m else title
        desc = _DESC_RE.search(block)
        if desc:  # carries set + printing/edition signal (1st Ed / Unlimited / Holo)
            listing.description = _clean(desc.group(1))
        out.append(listing)
    return out


def _parse_dom_loose(html: str) -> list[ComcListing]:
    """Fallback for an unrecognized layout: any /Cards/ anchor with a $price nearby."""
    out: list[ComcListing] = []
    for m in re.finditer(r'<a[^>]+href="([^"]*/Cards/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        href, inner = m.group(1), _clean(m.group(2))
        price = _to_float(inner)
        if price is None:
            continue
        name = re.sub(r"\$\s?[0-9].*$", "", inner).strip()
        url = href if href.startswith("http") else COMC_BASE + href
        out.append(_listing_from_fields(name or inner, price, url))
    return out


def parse_page(html: str) -> list[ComcListing]:
    listings = _parse_jsonld(html)
    if listings:
        return listings
    return _parse_dom(html)


def parse_html_file(path: str | Path) -> list[ComcListing]:
    """Parse a saved COMC page (for validating selectors offline)."""
    return parse_page(Path(path).read_text(encoding="utf-8"))


def listings_from_json(path: str | Path) -> list[ComcListing]:
    """Load synthetic listings for dry-run (list of dicts with ComcListing fields)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["listings"] if isinstance(data, dict) else data
    out: list[ComcListing] = []
    for d in items:
        out.append(ComcListing(
            raw_name=d["raw_name"], price=float(d["price"]), url=d.get("url", ""),
            set_hint=d.get("set_hint"), number_hint=d.get("number_hint"),
            condition=d.get("condition", ""), graded=bool(d.get("graded", False)),
            grader=d.get("grader"), quantity=int(d.get("quantity", 1)),
            seller=d.get("seller"), image_url=d.get("image_url"),
        ))
    return out


class ComcScraper:
    """Fetches and parses COMC browse pages.

    Two transports, selected by `settings.comc_fetch_mode`:
      - "firecrawl" (default): headless via Firecrawl's stealth proxy — no local browser,
        no login, no cookies. Clears the Cloudflare challenge from a stealth egress.
      - "playwright": a local Chromium (optionally seeded with `COMC_SESSION_COOKIE`).
        Lazily imported so the package works without a browser installed.

    Either way, `iter_listings`/`capture` hand the rendered HTML to `parse_page`.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw = None
        self._browser = None
        self._context = None
        self._state_path = CACHE_DIR / "browser_state.json"

    def __enter__(self) -> "ComcScraper":
        # Good-faith robots.txt check before fetching from COMC (either transport).
        allowed, reason = robots_allowed(build_browse_url(self.settings, page=1), BROWSER_UA)
        log.info("COMC robots.txt: %s", reason)
        if not allowed:
            raise ComcAccessError(
                "COMC robots.txt disallows this user-agent/path; aborting scan."
            )

        # COMC's Cloudflare Turnstile is only auto-solved by a HEADFUL real-Chrome browser;
        # headless never clears it (cf_clearance is bound to the headful fingerprint). So
        # force headful in playwright mode — on a server this renders to a virtual display,
        # still fully automated (patchright solves the challenge, no human needed).
        if self.settings.comc_headless:
            log.info("COMC needs a headful browser to clear Cloudflare; forcing headful.")
            self.settings.comc_headless = False
        sync_playwright, engine = _import_playwright()
        log.info("COMC fetch mode: playwright (%s, headful).", engine)
        profile_dir = Path(self.settings.comc_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        # Clear stale single-instance locks left by an unclean prior shutdown — otherwise a
        # `channel="chrome"` launch fails and silently falls back to (CF-blocked) chromium.
        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                (profile_dir / lock).unlink()
            except OSError:
                pass
        self._pw = sync_playwright().start()
        # Persistent context keeps Cloudflare's cf_clearance cookie across runs.
        kw = dict(user_data_dir=str(profile_dir), headless=self.settings.comc_headless)
        if engine == "patchright":
            # patchright auto-solves the Cloudflare Turnstile ONLY with its defaults intact:
            # real Chrome channel, NO user_agent override, NO automation args, no_viewport.
            # (Verified: headful real-Chrome patchright clears COMC's challenge.)
            kw["no_viewport"] = True
            try:
                self._context = self._pw.chromium.launch_persistent_context(channel="chrome", **kw)
            except Exception as exc:  # Chrome not installed -> patched chromium
                log.warning("Chrome channel unavailable (%s); using chromium.", exc)
                self._context = self._pw.chromium.launch_persistent_context(**kw)
        else:
            kw.update(user_agent=BROWSER_UA, locale="en-US",
                      viewport={"width": 1366, "height": 900},
                      args=["--disable-blink-features=AutomationControlled"])
            self._context = self._pw.chromium.launch_persistent_context(**kw)
        self._seed_cookies()
        self._warm_up()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._context and self._context.close()  # persistent profile auto-saves
        except Exception:
            pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    def warm(self, url: str | None = None, wait_s: int = 30) -> bool:
        """Navigate (headful) so Cloudflare clears and the profile stores cf_clearance.

        Returns True if a real COMC results shell was seen. Keeps the page open `wait_s`
        seconds so a managed-challenge / Turnstile can finish (auto or operator-solved).
        """
        url = url or build_browse_url(self.settings, page=1)
        page = self._context.new_page()
        try:
            page.goto(COMC_BASE + "/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)  # let CF's managed challenge settle on the home page
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(max(1, wait_s) * 1000)
            html = page.content()
            ok = ("searchResultsStats" in html) or ("cardexplorer" in html)
            log.info("Warm-up %s (%d bytes) on %s",
                     "OK — Cloudflare cleared, profile saved" if ok
                     else "did NOT confirm a results page (CF may need a manual solve)",
                     len(html), url)
            return ok
        finally:
            page.close()

    def _fetch_html(self, url: str, solve_timeout_s: int = 60) -> str:
        """Return rendered HTML for `url` via the active transport.

        For playwright, polls while a Cloudflare Turnstile is still in progress — patchright
        auto-solves it (headful) within tens of seconds on a cold profile; once cf_clearance
        is cached the first read already has the page, so there's no wait.
        """
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = page.content()
            # Poll until a real results shell appears — catches the Cloudflare interstitial
            # AND any transient pre-render state (the first set-path hit after warm-up can
            # still be mid-challenge). A genuine empty page still carries searchResultsStats,
            # so this won't spin on it.
            waited = 0
            while (waited < solve_timeout_s
                   and "searchResultsStats" not in html and "cardexplorer" not in html):
                page.wait_for_timeout(3000)
                waited += 3
                html = page.content()
            return html
        finally:
            page.close()

    def _seed_cookies(self) -> None:
        raw = self.settings.comc_session_cookie
        if not raw:
            return
        cookies = []
        for part in raw.split(";"):
            if "=" in part:
                name, _, value = part.strip().partition("=")
                cookies.append({"name": name, "value": value, "domain": ".comc.com", "path": "/"})
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not seed COMC cookies: %s", exc)

    def _warm_up(self) -> None:
        """Navigate home and wait out any Cloudflare Turnstile (patchright auto-solves it,
        ~tens of seconds on a cold/expired profile) BEFORE the first real fetch — otherwise
        the first set comes back empty while CF is still solving. Fast no-op when the
        profile's cf_clearance is still valid."""
        page = self._context.new_page()
        try:
            page.goto(COMC_BASE + "/", wait_until="domcontentloaded", timeout=60000)
            waited = 0
            while waited < 80 and "Just a moment" in page.content():
                page.wait_for_timeout(3000)
                waited += 3
            if waited:
                log.info("Cloudflare cleared after ~%ds warm-up.", waited)
        except Exception as exc:  # noqa: BLE001
            log.warning("COMC warm-up navigation failed: %s", exc)
        finally:
            page.close()

    def capture(self, url: str, out_path: str | Path) -> Path:
        """Fetch `url` and save the rendered HTML, for offline selector tuning."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._fetch_html(url), encoding="utf-8")
        log.info("Saved rendered HTML to %s (%d bytes)", out, out.stat().st_size)
        return out

    def iter_listings(
        self, search_term: str | None, max_pages: int = 0, start_page: int = 1,
        era_path: str | None = None, graded: bool = False,
    ) -> Iterator[tuple[int, list[ComcListing]]]:
        """Yield (page_number, listings) for each COMC page until empty / max_pages.

        `era_path` (e.g. "1999/Pokemon_Base_Set_-_Base_-_Unlimited") browses a specific
        set by URL path — the Cloudflare-friendly route that the faceted text-search is
        not. A persistent Cloudflare block (ComcBlockedError, after the fetcher's own
        retries) ends this set's iteration rather than crashing the whole scan.
        """
        n = 0
        page_no = start_page
        while True:
            if max_pages and n >= max_pages:
                break
            url = build_browse_url(
                self.settings, search_term=search_term, era_path=era_path, page=page_no,
                graded=graded,
            )
            try:
                listings = parse_page(self._fetch_html(url))
            except ComcBlockedError:
                # Distinct from a genuine empty page: let the caller count consecutive
                # blocks and trip a circuit breaker (avoids burning credits on a hard block).
                raise
            except Exception as exc:  # noqa: BLE001 — one set must not kill the sweep
                log.warning("COMC page %s failed (%s); stopping this set.", page_no, exc)
                break
            if not listings:
                break
            yield page_no, listings
            n += 1
            page_no += 1
            time.sleep(self.settings.comc_request_delay_s + random.uniform(0, 2.0))
