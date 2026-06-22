"""Fallback price source: TCGdex (api.tcgdex.net), adapted to the TCGCSV shape.

Por que existe (risco de fonte única): o scanner depende do tcgcsv.com como a
ÚNICA referência de preço. Se ele cair (404/timeout/rede), o scan inteiro trava.
O TCGdex publica o MESMO `marketPrice` do TCGplayer (e Cardmarket EUR de bônus),
exposto por carta JÁ COM o `productId` do TCGplayer — então dá pra reconstruir os
preços de um set quando o tcgcsv falha. NÃO é preço inventado nem estimativa: é o
mesmo número do TCGplayer, de outro espelho (honestidade de preço preservada).

Custo: o TCGdex só dá preço por CARTA (1 request/carta) — então isto é um
FALLBACK de emergência (lento), não a fonte primária. O resultado adaptado é
cacheado em disco por dia (mesmo padrão do tcgcsv_client).

Adaptação: `set_products_prices()` devolve listas `products`/`prices` no MESMO
formato do `tcgcsv_client`, pra alimentar `TcgIndex.add_group` sem tocar no índice
nem no resto do pipeline. Os campos de preço do TCGdex (lowPrice/midPrice/
highPrice/marketPrice/directLowPrice) têm os MESMOS nomes do TCGCSV — cópia direta.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .config import CACHE_DIR, Settings
from .normalize import normalize_set

TCGDEX_BASE = "https://api.tcgdex.net/v2/en"
_MIN_INTERVAL_S = 0.10
_MAX_RETRIES = 3
_PRICE_FIELDS = ("lowPrice", "midPrice", "highPrice", "marketPrice", "directLowPrice")

# Finish do TCGdex -> subTypeName do TCGplayer (o que o TcgIndex espera).
_FINISH_TO_SUBTYPE = {
    "normal": "Normal",
    "holofoil": "Holofoil",
    "reverse-holofoil": "Reverse Holofoil",
    "1st-edition": "1st Edition",
    "1st-edition-holofoil": "1st Edition Holofoil",
    "unlimited": "Unlimited",
    "unlimited-holofoil": "Unlimited Holofoil",
}


def _adapt_card(full: dict) -> tuple[dict, list[dict]] | None:
    """Carta completa do TCGdex -> (product, [price rows]) no formato do TCGCSV.

    Devolve None se a carta não tem preço TCGplayer (sem productId). Pula as
    chaves de metadado do bloco tcgplayer ('unit', 'updated') — só dicts com
    productId são finishes de verdade.
    """
    tcgplayer = (full.get("pricing") or {}).get("tcgplayer") or {}
    product_id: int | None = None
    price_rows: list[dict] = []
    for finish, data in tcgplayer.items():
        if not isinstance(data, dict) or data.get("productId") is None:
            continue
        try:
            product_id = int(data["productId"])  # mesmo productId nas finishes da carta
        except (TypeError, ValueError):
            continue  # productId não-numérico (improvável) — pula a finish, não quebra
        sub = _FINISH_TO_SUBTYPE.get(finish, finish.replace("-", " ").title())
        row = {"productId": product_id, "subTypeName": sub}
        for field in _PRICE_FIELDS:
            row[field] = data.get(field)
        price_rows.append(row)
    if product_id is None:
        return None

    image = full.get("image") or ""
    product = {
        "productId": product_id,
        "name": full.get("name", ""),
        "cleanName": full.get("name", ""),
        # URL canônica do produto no TCGplayer, derivada do productId REAL (mesma
        # que o tcgcsv aponta) — não é inventada, redireciona pro produto certo.
        "url": f"https://www.tcgplayer.com/product/{product_id}",
        "imageUrl": f"{image}/high.webp" if image else "",
        "extendedData": [
            {"name": "Number", "value": str(full.get("localId") or "")},
            {"name": "Rarity", "value": full.get("rarity") or ""},
        ],
    }
    return product, price_rows


class TcgdexClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": settings.http_user_agent, "Accept": "application/json"}
        )
        self._last_call = 0.0
        self._set_index: dict[str, str] | None = None  # nome normalizado -> set id

    # --- low level -------------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
        self._last_call = time.monotonic()

    def _get_json(self, path: str):
        """GET {base}{path} -> JSON. 404 -> None. Levanta RuntimeError se cair de vez."""
        url = f"{TCGDEX_BASE}{path}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=30)
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} for {url}")
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - retry transient failures
                last_exc = exc
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"TCGdex request failed after retries: {url}") from last_exc

    # --- set name -> tcgdex set id --------------------------------------
    def _resolve_set_id(self, set_name: str, abbreviation: str | None = None) -> str | None:
        if self._set_index is None:
            sets = self._get_json("/sets") or []
            idx: dict[str, str] = {}
            for s in sets:
                sid = s.get("id")
                if not sid:
                    continue
                idx.setdefault(normalize_set(s.get("name", "")), sid)
                abbr = s.get("abbreviation")
                if abbr:
                    idx.setdefault(normalize_set(abbr), sid)
            self._set_index = idx
        # Try the (code-stripped) name first, then the abbreviation — TCGCSV and
        # TCGdex set names can differ slightly (e.g. "Energies" vs "Energy").
        for key in (normalize_set(set_name), normalize_set(abbreviation or "")):
            if key and key in self._set_index:
                return self._set_index[key]
        return None

    # --- cache -----------------------------------------------------------
    def _cache_path(self, set_id: str) -> Path:
        date = time.strftime("%Y-%m-%d", time.gmtime())
        d = CACHE_DIR / "tcgdex" / date
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{set_id}.json"

    # --- public ----------------------------------------------------------
    def set_products_prices(
        self, set_name: str, abbreviation: str | None = None
    ) -> tuple[list[dict] | None, list[dict] | None]:
        """(products, prices) de um set no formato TCGCSV, ou (None, None).

        Resolve o set pelo nome (ou abreviação), baixa cada carta (1 request/carta)
        e adapta. None quando o set não existe no TCGdex ou nenhuma carta tem preço
        TCGplayer.
        """
        set_id = self._resolve_set_id(set_name, abbreviation)
        if not set_id:
            return None, None
        cache = self._cache_path(set_id)
        if cache.exists() and not self.settings.tcgcsv_force_refresh:
            try:
                blob = json.loads(cache.read_text(encoding="utf-8"))
                return blob.get("products"), blob.get("prices")
            except Exception:
                pass
        set_data = self._get_json(f"/sets/{set_id}")
        if not set_data:
            return None, None
        products: list[dict] = []
        prices: list[dict] = []
        for brief in set_data.get("cards", []) or []:
            cid = brief.get("id")
            if not cid:
                continue
            full = self._get_json(f"/cards/{cid}")
            if not full:
                continue
            adapted = _adapt_card(full)
            if adapted is None:
                continue
            product, rows = adapted
            products.append(product)
            prices.extend(rows)
        if products:
            cache.write_text(
                json.dumps({"products": products, "prices": prices}), encoding="utf-8"
            )
        return (products or None), (prices or None)
