"""Client for the public TCGCSV mirror of TCGplayer data, with a daily on-disk cache.

Endpoints (verified):
  GET /tcgplayer/3/groups               -> sets for Pokemon (categoryId 3)
  GET /tcgplayer/3/{groupId}/products   -> products (name, extendedData[Number/Rarity/...])
  GET /tcgplayer/3/{groupId}/prices     -> prices (low/mid/high/market/directLow, subTypeName)
Data updates ~once/day; we cache a per-day snapshot and refetch at most once/day.
Politeness: >=150ms between requests, retry with backoff on 429/5xx.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .config import POKEMON_CATEGORY_ID, TCGCSV_BASE_URL, CACHE_DIR, Settings

_MIN_INTERVAL_S = 0.15
_MAX_RETRIES = 4


class TcgCsvClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cat = POKEMON_CATEGORY_ID
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": settings.http_user_agent, "Accept": "application/json"}
        )
        self._last_call = 0.0
        self._snapshot_date: str | None = None

    # --- low level -------------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
        self._last_call = time.monotonic()

    def _get(self, path: str) -> requests.Response:
        url = f"{TCGCSV_BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} for {url}")
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001 - retry transient failures
                last_exc = exc
                time.sleep(min(2 ** attempt, 16))
        raise RuntimeError(f"TCGCSV request failed after retries: {url}") from last_exc

    def _get_results(self, path: str) -> list[dict]:
        data = self._get(path).json()
        return data.get("results", []) if isinstance(data, dict) else []

    # --- snapshot dating -------------------------------------------------
    def snapshot_date(self) -> str:
        if self._snapshot_date:
            return self._snapshot_date
        date = time.strftime("%Y-%m-%d", time.gmtime())
        try:
            txt = self._get("/last-updated.txt").text
            m = re.search(r"\d{4}-\d{2}-\d{2}", txt)
            if m:
                date = m.group(0)
        except Exception:
            pass
        self._snapshot_date = date
        return date

    def _snapshot_dir(self) -> Path:
        d = CACHE_DIR / "tcgcsv" / self.snapshot_date()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- cached fetchers -------------------------------------------------
    def _cached(self, name: str, path: str, force: bool) -> list[dict]:
        fpath = self._snapshot_dir() / name
        if fpath.exists() and not force and not self.settings.tcgcsv_force_refresh:
            try:
                return json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                pass
        results = self._get_results(path)
        fpath.write_text(json.dumps(results), encoding="utf-8")
        return results

    def groups(self, force: bool = False) -> list[dict]:
        return self._cached("groups.json", f"/tcgplayer/{self.cat}/groups", force)

    def products(self, group_id: int, force: bool = False) -> list[dict]:
        return self._cached(
            f"products_{group_id}.json",
            f"/tcgplayer/{self.cat}/{group_id}/products",
            force,
        )

    def prices(self, group_id: int, force: bool = False) -> list[dict]:
        return self._cached(
            f"prices_{group_id}.json",
            f"/tcgplayer/{self.cat}/{group_id}/prices",
            force,
        )
