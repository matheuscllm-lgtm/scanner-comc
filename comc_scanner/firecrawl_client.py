"""Firecrawl `/v2/scrape` transport for fetching COMC pages headlessly.

COMC sits behind a Cloudflare managed challenge, so a plain GET returns 403 and a
headless sandbox gets challenged. Firecrawl's `proxy: stealth` renders the page from a
residential/stealth egress and clears the challenge — the same route that unblocked OLX
in the sealed scanner. This lets the scanner run with NO local browser / login / cookies.

Stdlib-only (urllib) so the package keeps its minimal-deps footprint. Reads the API key
from `FIRECRAWL_API_KEY`. The Cloudflare interstitial is intermittent (it cleared on the
plain browse URL first try but challenged a faceted search URL ~3x in a row during
calibration), so `get_html` retries specifically on a detected challenge with backoff,
and raises `ComcBlockedError` only after exhausting retries — it never fabricates data.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("comc_scanner.firecrawl")

FIRECRAWL_V2 = "https://api.firecrawl.dev/v2/scrape"
# Transient HTTP codes worth retrying. 402 (no credits) and real 4xx are not retried.
_RETRYABLE = (408, 429, 500, 502, 503, 504)


class ComcBlockedError(RuntimeError):
    """COMC returned a Cloudflare challenge even via the stealth proxy (not a bug)."""


def is_comc_challenge(html: str) -> bool:
    """True when `html` is a Cloudflare interstitial rather than a real COMC results page.

    A genuine COMC browse page always carries the results shell (`id="cardexplorer"` /
    `searchResultsStats`) — even a zero-result page does. The challenge page carries
    neither and typically the Cloudflare `challenge-platform` script or "Just a moment".
    """
    if not html:
        return True
    if "cardexplorer" in html or "searchResultsStats" in html:
        return False  # real results shell present (possibly with 0 listings)
    return True  # no results shell -> challenge / error interstitial


def post_scrape(
    url: str, *, api_key: str, proxy: str = "stealth", country: str = "US",
    languages: tuple[str, ...] = ("en-US",), wait_ms: int = 12000,
    timeout: int = 180, retries: int = 2,
) -> dict:
    """POST to Firecrawl `/v2/scrape` asking for `rawHtml`; return the raw JSON envelope.

    Retries only the transient HTTP codes and connection errors with linear backoff.
    """
    payload = {
        "url": url,
        "formats": ["rawHtml"],
        "location": {"country": country, "languages": list(languages)},
        "proxy": proxy,
        "onlyMainContent": False,
        "waitFor": wait_ms,
    }
    req = urllib.request.Request(
        FIRECRAWL_V2,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, http.client.RemoteDisconnected,
                ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


def extract_raw_html(envelope: dict) -> str:
    """Validate the Firecrawl envelope and return `rawHtml` (raises on failure/empty)."""
    if not envelope.get("success", True):
        raise RuntimeError(f"Firecrawl failed: {envelope.get('error') or envelope}")
    data = envelope.get("data", envelope)
    html = data.get("rawHtml") or data.get("html") or ""
    if not html:
        raise RuntimeError("Firecrawl returned empty HTML (no rawHtml).")
    return html


class ComcFirecrawlFetcher:
    """Fetches rendered COMC HTML via Firecrawl, retrying the intermittent CF challenge."""

    def __init__(
        self, api_key: str | None = None, *, proxy: str = "stealth",
        wait_ms: int = 12000, timeout: int = 180, http_retries: int = 2,
        block_retries: int = 3,
    ):
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set; cannot fetch COMC via Firecrawl. "
                "Set it in the environment or .env, or use COMC_FETCH_MODE=playwright."
            )
        self.proxy = proxy
        self.wait_ms = wait_ms
        self.timeout = timeout
        self.http_retries = http_retries
        self.block_retries = block_retries

    def get_html(self, url: str) -> str:
        """Return rendered COMC HTML; raise ComcBlockedError if CF won't clear."""
        for attempt in range(self.block_retries + 1):
            envelope = post_scrape(
                url, api_key=self.api_key, proxy=self.proxy, wait_ms=self.wait_ms,
                timeout=self.timeout, retries=self.http_retries,
            )
            html = extract_raw_html(envelope)
            if not is_comc_challenge(html):
                return html
            if attempt < self.block_retries:
                wait = 5 * (attempt + 1)
                log.warning("COMC Cloudflare challenge (try %d/%d); retrying in %ds…",
                            attempt + 1, self.block_retries, wait)
                time.sleep(wait)
        raise ComcBlockedError(
            "COMC Cloudflare challenge persisted across retries via Firecrawl stealth proxy."
        )

    def close(self) -> None:
        pass
