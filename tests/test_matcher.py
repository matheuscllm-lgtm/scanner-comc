"""Offline tests for the matcher and reference-price logic (synthetic index)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comc_scanner.config import Settings  # noqa: E402
from comc_scanner.matcher import match  # noqa: E402
from comc_scanner.models import ComcListing  # noqa: E402
from comc_scanner.tcg_index import TcgIndex  # noqa: E402


def _index() -> TcgIndex:
    products = [
        {"productId": 1, "name": "Charizard", "cleanName": "Charizard", "url": "u1",
         "extendedData": [{"name": "Number", "value": "004/102"}, {"name": "Rarity", "value": "Holo Rare"}]},
        {"productId": 2, "name": "Charizard (Black Dot Error)", "cleanName": "Charizard error", "url": "u2",
         "extendedData": [{"name": "Number", "value": "004/102"}]},
        {"productId": 3, "name": "Blastoise", "cleanName": "Blastoise", "url": "u3",
         "extendedData": [{"name": "Number", "value": "002/102"}, {"name": "Rarity", "value": "Holo Rare"}]},
        {"productId": 4, "name": "Pikachu", "cleanName": "Pikachu", "url": "u4",
         "extendedData": [{"name": "Number", "value": "060/064"}]},
    ]
    prices = [
        {"productId": 1, "subTypeName": "Holofoil", "lowPrice": 500, "midPrice": 550,
         "highPrice": 700, "marketPrice": 600, "directLowPrice": None},
        {"productId": 2, "subTypeName": "Holofoil", "lowPrice": 1000, "midPrice": None,
         "highPrice": None, "marketPrice": None, "directLowPrice": None},
        {"productId": 3, "subTypeName": "Holofoil", "lowPrice": 180, "midPrice": 190,
         "highPrice": 250, "marketPrice": 200, "directLowPrice": None},
        # Pikachu only has 1st Edition / Unlimited variants (WotC style)
        {"productId": 4, "subTypeName": "1st Edition", "lowPrice": 25, "midPrice": 28,
         "highPrice": 40, "marketPrice": 30, "directLowPrice": None},
        {"productId": 4, "subTypeName": "Unlimited", "lowPrice": 5, "midPrice": 6,
         "highPrice": 10, "marketPrice": 7, "directLowPrice": None},
    ]
    idx = TcgIndex()
    idx.add_group(604, "Base Set", "BS", products, prices)
    return idx


def test_tier1_exact_and_margin():
    idx, s = _index(), Settings()
    L = ComcListing(raw_name="Blastoise", price=50.0, url="x", set_hint="Base Set",
                    number_hint="2/102", condition="EX-NM")
    deal = match(L, idx, s, context_set_key="base set")
    assert deal is not None
    assert deal.match_confidence == 0.95
    assert deal.tcg_reference == 200.0           # Holofoil market
    assert abs(deal.margin - 0.75) < 1e-9        # (200-50)/200


def test_tier1_disambiguation_by_name():
    idx, s = _index(), Settings()
    L = ComcListing(raw_name="Charizard Holo", price=100.0, url="x", set_hint="Base Set",
                    number_hint="4/102", condition="EX-NM")
    deal = match(L, idx, s, context_set_key="base set")
    assert deal is not None
    assert deal.product.product_id == 1          # picked real Charizard, not the error variant
    assert deal.match_confidence == 0.90
    assert deal.tcg_reference == 600.0


def test_conservative_subtype_fallback():
    idx, s = _index(), Settings()
    L = ComcListing(raw_name="Pikachu", price=1.0, url="x", set_hint="Base Set",
                    number_hint="60/64", condition="EX-NM")
    deal = match(L, idx, s, context_set_key="base set")
    assert deal is not None
    assert deal.sub_type_used == "Unlimited"     # cheaper than 1st Edition
    assert deal.tcg_reference == 7.0


def test_unresolvable_set_returns_none():
    idx, s = _index(), Settings()
    L = ComcListing(raw_name="Whatever", price=1.0, url="x", set_hint="Not A Set",
                    number_hint="9/9", condition="EX-NM")
    assert match(L, idx, s, context_set_key=None) is None


def test_no_number_strong_name_tier3():
    idx, s = _index(), Settings()
    L = ComcListing(raw_name="Blastoise", price=10.0, url="x", set_hint="Base Set",
                    condition="EX-NM")
    deal = match(L, idx, s, context_set_key="base set")
    assert deal is not None
    assert deal.match_confidence == 0.70
    assert deal.product.name == "Blastoise"
