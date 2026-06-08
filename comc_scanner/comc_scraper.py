"""COMC listing scraper.

COMC is behind a Cloudflare managed challenge (a plain HTTP GET returns 403), so we
drive a real Chromium via Playwright, optionally seeded with the user's session
cookie, navigate the verified comma-faceted browse URLs, and parse the rendered HTML.

Browse-URL grammar (verified), e.g.:
  https://www.comc.com/Cards/Pokemon,=evolving+skies,sl,fb,aUngraded,rCOMC,gEX-NM,i100,p3
  sl=sort lowest price, fb=Buy-It-Now, aUngraded=exclude graded, g<band>=condition,
  i<n>=items/page, p<n>=page, ,=<term>=text search.

NOTE: COMC's exact listing DOM is not publicly documented. `_parse_page` tries a
JSON-LD path first, then a heuristic DOM scrape. Validate/adjust the selectors against
a real saved page (see `parse_html_file` and the `dry-run` flow) before trusting live
output.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Iterator

from .config import CACHE_DIR, Settings
from .models import ComcListing
from .normalize import detect_graded

log = logging.getLogger("comc_scanner.comc")

COMC_BASE = "https://www.comc.com"
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
) -> str:
    path = "/Cards/Pokemon"
    if era_path:
        path += "/" + urllib.parse.quote(era_path)
    segments: list[str] = []
    if search_term:
        segments.append("=" + urllib.parse.quote_plus(search_term))
    segments.append("sl")  # sort: lowest price first
    segments.append("fb")  # Buy-It-Now only
    segments.append("aGraded" if settings.comc_include_graded else "aUngraded")
    segments.append("rCOMC")  # COMC-noted condition source
    if settings.comc_condition_band:
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


def _parse_dom(html: str) -> list[ComcListing]:
    """Heuristic DOM scrape. Tune the selectors against a real COMC page."""
    try:
        from selectolax.parser import HTMLParser  # type: ignore
    except Exception:
        return _parse_dom_stdlib(html)

    tree = HTMLParser(html)
    out: list[ComcListing] = []
    # COMC item links generally point at /Cards/.../<id> with the price rendered nearby.
    for node in tree.css("a[href*='/Cards/']"):
        href = node.attributes.get("href", "") or ""
        text = node.text(strip=True)
        if not text or "$" not in text:
            continue
        price = _to_float(text)
        if price is None:
            continue
        name = re.sub(r"\$\s?[0-9].*$", "", text).strip()
        num_m = _NUM_RE.search(text)
        url = href if href.startswith("http") else COMC_BASE + href
        out.append(_listing_from_fields(
            name or text, price, url, number_hint=num_m.group(1) if num_m else None,
        ))
    return out


def _parse_dom_stdlib(html: str) -> list[ComcListing]:
    """Last-resort parser using only the stdlib (no selectolax)."""
    out: list[ComcListing] = []
    for m in re.finditer(r'<a[^>]+href="([^"]*/Cards/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        href, inner = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        inner = re.sub(r"\s+", " ", inner).strip()
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
    """Playwright-backed scraper. Lazily imports Playwright so the rest of the
    package works without a browser installed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw = None
        self._browser = None
        self._context = None
        self._state_path = CACHE_DIR / "browser_state.json"

    def __enter__(self) -> "ComcScraper":
        from playwright.sync_api import sync_playwright  # type: ignore

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.settings.comc_headless)
        ctx_kwargs = {
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "locale": "en-US",
            "viewport": {"width": 1366, "height": 900},
        }
        if self._state_path.exists():
            ctx_kwargs["storage_state"] = str(self._state_path)
        self._context = self._browser.new_context(**ctx_kwargs)
        self._seed_cookies()
        try:
            from playwright_stealth import stealth_sync  # type: ignore

            stealth_sync(self._context)
        except Exception:
            pass
        self._warm_up()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._context:
                self._context.storage_state(path=str(self._state_path))
        except Exception:
            pass
        for closer in (self._context, self._browser):
            try:
                closer and closer.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

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
        page = self._context.new_page()
        try:
            page.goto(COMC_BASE + "/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)  # give Cloudflare time to clear
            self._context.storage_state(path=str(self._state_path))
        except Exception as exc:  # noqa: BLE001
            log.warning("COMC warm-up navigation failed: %s", exc)
        finally:
            page.close()

    def iter_listings(
        self, search_term: str | None, max_pages: int = 0, start_page: int = 1,
    ) -> Iterator[tuple[int, list[ComcListing]]]:
        """Yield (page_number, listings) for each COMC page until empty / max_pages."""
        page = self._context.new_page()
        try:
            n = 0
            page_no = start_page
            while True:
                if max_pages and n >= max_pages:
                    break
                url = build_browse_url(self.settings, search_term=search_term, page=page_no)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1500)
                    listings = parse_page(page.content())
                except Exception as exc:  # noqa: BLE001
                    log.warning("COMC page %s failed (%s); stopping this set.", page_no, exc)
                    break
                if not listings:
                    break
                yield page_no, listings
                n += 1
                page_no += 1
                time.sleep(self.settings.comc_request_delay_s + random.uniform(0, 2.0))
        finally:
            page.close()
