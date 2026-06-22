"""Offline tests for the TCGdex price fallback (no network).

Cover the pure adapter (TCGdex card JSON -> TCGCSV-shaped products/prices), the
set-name resolution, the integration with the real TcgIndex, and the pipeline's
fallback selection (TCGCSV down -> TCGdex). All HTTP is stubbed.
"""
from pathlib import Path
from types import SimpleNamespace

from comc_scanner.config import load_settings
from comc_scanner.pipeline import Scanner
from comc_scanner.tcg_index import TcgIndex
from comc_scanner.tcgdex_client import TcgdexClient, _adapt_card


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


# --- the pure adapter -------------------------------------------------------
def _full_card(local="022", rarity="Special Illustration Rare", pid=675834):
    return {
        "id": f"me02.5-{local}",
        "localId": local,
        "name": "Mega Charizard Y ex",
        "rarity": rarity,
        "image": "https://assets.tcgdex.net/en/me/me02.5/022",
        "pricing": {
            "tcgplayer": {
                "unit": "USD",                       # metadado — deve ser ignorado
                "updated": "2026-06-21T22:59:03Z",   # metadado — deve ser ignorado
                "holofoil": {
                    "productId": pid, "lowPrice": 7.08, "midPrice": 9.4,
                    "highPrice": 92.3, "marketPrice": 8.94, "directLowPrice": None,
                },
            },
            "cardmarket": {"avg": 5.03, "trend": 5.06},
        },
    }


def test_adapt_card_builds_tcgcsv_shape():
    product, prices = _adapt_card(_full_card())
    assert product["productId"] == 675834
    assert product["url"] == "https://www.tcgplayer.com/product/675834"
    ext = {e["name"]: e["value"] for e in product["extendedData"]}
    assert ext == {"Number": "022", "Rarity": "Special Illustration Rare"}
    assert len(prices) == 1                       # 'unit'/'updated' não viram preço
    row = prices[0]
    assert row["productId"] == 675834
    assert row["subTypeName"] == "Holofoil"       # finish mapeada
    assert row["marketPrice"] == 8.94 and row["lowPrice"] == 7.08


def test_adapt_card_maps_reverse_finish_and_titlecases_unknown():
    card = _full_card()
    card["pricing"]["tcgplayer"]["reverse-holofoil"] = {
        "productId": 675834, "marketPrice": 12.0,
    }
    card["pricing"]["tcgplayer"]["some-new-finish"] = {
        "productId": 675834, "marketPrice": 1.0,
    }
    _, prices = _adapt_card(card)
    subs = {p["subTypeName"] for p in prices}
    assert "Reverse Holofoil" in subs            # mapeada explicitamente
    assert "Some New Finish" in subs             # desconhecida -> title-case


def test_adapt_card_none_when_no_tcgplayer_price():
    card = _full_card()
    card["pricing"] = {"cardmarket": {"avg": 5.0}}   # só Cardmarket, sem tcgplayer
    assert _adapt_card(card) is None


def test_adapt_card_skips_non_numeric_productid_without_crashing():
    # productId não-numérico não pode estourar (ValueError escaparia do fallback).
    card = _full_card()
    card["pricing"]["tcgplayer"]["holofoil"]["productId"] = "not-a-number"
    assert _adapt_card(card) is None                 # única finish ruim -> None, sem crash


def test_adapt_card_skips_only_the_bad_finish():
    card = _full_card()
    card["pricing"]["tcgplayer"]["normal"] = {"productId": "xyz", "marketPrice": 1.0}
    product, prices = _adapt_card(card)              # holofoil (boa) ainda resolve
    assert product["productId"] == 675834
    assert all(p["productId"] == 675834 for p in prices)   # 'normal' ruim foi pulada


# --- set resolution + whole-set fetch (HTTP stubbed) ------------------------
class _StubTcgdex(TcgdexClient):
    """TcgdexClient with _get_json replaced by an in-memory fixture router."""

    def __init__(self, settings, sets, set_cards, cards, tmp: Path):
        super().__init__(settings)
        self._fix_sets = sets
        self._fix_set_cards = set_cards
        self._fix_cards = cards
        self._tmp = tmp

    def _get_json(self, path: str):
        if path == "/sets":
            return self._fix_sets
        if path.startswith("/sets/"):
            return self._fix_set_cards.get(path.split("/sets/")[1])
        if path.startswith("/cards/"):
            return self._fix_cards.get(path.split("/cards/")[1])
        return None

    def _cache_path(self, set_id: str) -> Path:
        return self._tmp / f"{set_id}.json"


def _stub(tmp: Path):
    sets = [{"id": "sv08", "name": "Surging Sparks", "abbreviation": "SSP"}]
    set_cards = {"sv08": {"id": "sv08", "name": "Surging Sparks",
                          "cards": [{"id": "sv08-001"}, {"id": "sv08-238"}]}}
    cards = {
        "sv08-001": _full_card(local="001", rarity="Common", pid=111),
        "sv08-238": _full_card(local="238", rarity="Special Illustration Rare", pid=222),
    }
    return _StubTcgdex(_settings(), sets, set_cards, cards, tmp)


def test_set_products_prices_resolves_and_adapts(tmp_path):
    client = _stub(tmp_path)
    products, prices = client.set_products_prices("Surging Sparks")
    assert products and len(products) == 2
    assert {p["productId"] for p in products} == {111, 222}
    assert all("marketPrice" in row for row in prices)


def test_set_products_prices_feeds_real_index(tmp_path):
    """The adapted output must be consumable by the real TcgIndex unchanged."""
    client = _stub(tmp_path)
    products, prices = client.set_products_prices("Surging Sparks")
    index = TcgIndex()
    index.add_group(99, "Surging Sparks", "SSP", products, prices)
    card = index.cards_by_product[222]
    ref = index.reference_price(card)
    assert ref is not None
    price, sub, field = ref
    assert price == 8.94 and field == "market"      # market->mid->low; market present
    # and it joins by collector number (TCGdex localId "238" -> key "238")
    assert ("surging sparks", "238") in index.by_set_number


def test_set_products_prices_unknown_set_returns_none(tmp_path):
    client = _stub(tmp_path)
    assert client.set_products_prices("No Such Set 9000") == (None, None)


# --- pipeline fallback selection --------------------------------------------
class _DownClient:
    def products(self, gid): raise RuntimeError("tcgcsv down")
    def prices(self, gid): raise RuntimeError("tcgcsv down")


class _EmptyClient:
    def products(self, gid): return []
    def prices(self, gid): return []


class _OkClient:
    def products(self, gid):
        return [{"productId": 1, "name": "X", "extendedData": [{"name": "Number", "value": "1"}]}]
    def prices(self, gid):
        return [{"productId": 1, "subTypeName": "Holofoil", "marketPrice": 50.0}]


class _FakeTcgdex:
    def __init__(self, data):
        self.data = data
        self.called = False
    def set_products_prices(self, name, abbreviation=None):
        self.called = True
        return self.data


_TS = SimpleNamespace(group_id=1, name="Surging Sparks", abbreviation="SSP")
_FALLBACK = ([{"productId": 9, "name": "Y", "extendedData": [{"name": "Number", "value": "9"}]}],
             [{"productId": 9, "subTypeName": "Holofoil", "marketPrice": 99.0}])


def test_fetch_uses_tcgcsv_when_up_and_skips_fallback():
    sc = Scanner(_settings())
    sc.client = _OkClient()
    sc._tcgdex = _FakeTcgdex(_FALLBACK)
    products, prices = sc._fetch_set_data(_TS)
    assert products[0]["productId"] == 1          # TCGCSV data
    assert sc._tcgdex.called is False             # fallback NOT consulted


def test_fetch_falls_back_to_tcgdex_when_tcgcsv_raises():
    sc = Scanner(_settings())
    sc.client = _DownClient()
    sc._tcgdex = _FakeTcgdex(_FALLBACK)
    products, prices = sc._fetch_set_data(_TS)
    assert sc._tcgdex.called is True
    assert products[0]["productId"] == 9          # TCGdex fallback data
    assert prices[0]["marketPrice"] == 99.0


def test_fetch_falls_back_when_tcgcsv_empty():
    sc = Scanner(_settings())
    sc.client = _EmptyClient()
    sc._tcgdex = _FakeTcgdex(_FALLBACK)
    products, _ = sc._fetch_set_data(_TS)
    assert sc._tcgdex.called is True and products[0]["productId"] == 9


def test_fetch_returns_none_when_both_fail():
    sc = Scanner(_settings())
    sc.client = _DownClient()
    sc._tcgdex = _FakeTcgdex((None, None))
    assert sc._fetch_set_data(_TS) == (None, None)


def test_fetch_no_fallback_when_disabled():
    sc = Scanner(_settings(tcgdex_fallback=False))
    sc.client = _DownClient()
    assert sc._tcgdex is None                      # not constructed when disabled
    assert sc._fetch_set_data(_TS) == (None, None)
