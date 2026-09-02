"""Funil único do scanner (offline): raw NM + slabs, filtros, 20%, dedupe, status."""
from pathlib import Path

import pytest

from comc_scanner import pipeline as pl
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.pricecharting_client import GradedRef
from comc_scanner.tcg_index import TcgIndex

SET = "SV: Scarlet & Violet 151"
from comc_scanner.normalize import normalize_set

CTX = normalize_set(SET)


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _product(pid, name, number, rarity="Double Rare"):
    return {"productId": pid, "groupId": 99, "name": name, "cleanName": name,
            "url": f"https://www.tcgplayer.com/product/{pid}",
            "extendedData": [{"name": "Number", "value": number},
                             {"name": "Rarity", "value": rarity}]}


def _price(pid, market, mid=None, low=None, sub="Holofoil"):
    return {"productId": pid, "subTypeName": sub, "marketPrice": market,
            "midPrice": mid, "lowPrice": low, "highPrice": None, "directLowPrice": None}


@pytest.fixture
def index():
    idx = TcgIndex()
    idx.add_group(99, SET, "SV3PT5", [
        _product(1, "Charizard ex - 006/165", "006/165"),
        _product(2, "Pidgeotto - 017/165", "017/165", "Common"),
        _product(3, "Mewtwo - 150/165", "150/165"),
    ], [
        _price(1, 100.0), _price(2, 50.0), _price(3, None, mid=40.0),
    ])
    return idx


def _raw(name, number, price, cond="NM", set_hint="Pokemon Scarlet Violet - 151 sv2a - Base"):
    return ComcListing(raw_name=name, price=price, url=f"https://www.comc.com/x/{name}/{price}",
                       set_hint=set_hint, number_hint=number, condition=cond,
                       item_id=f"{name}{price}")


def _slab(name, number, price, grade, grader="PSA"):
    L = _raw(name, number, price, cond=grade.split(" ")[1])
    L.graded, L.grader, L.grade = True, grader, grade
    return L


def test_raw_nm_iconic_20pct_is_ok(index):
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw("Charizard ex", "006", 75.0), index, CTX, pl.KIND_RAW)
    assert d is not None and d.status == "OK"
    assert d.pokemon == "Charizard" and d.pokemon_rank == 1
    assert round(d.margin, 2) == 0.25 and d.ref_source == "tcgplayer"
    assert d.listing_type == "Raw NM"
    assert sc.stats["ok"] == 1


def test_discount_below_20_is_discarded(index):
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_raw("Charizard ex", "006", 85.0), index, CTX, pl.KIND_RAW) is None
    assert sc.stats["below_discount"] == 1
    sc2 = pl.Scanner(_settings(min_discount_percent=10))
    assert sc2.process_listing(_raw("Charizard ex", "006", 85.0), index, CTX, pl.KIND_RAW) is not None


def test_raw_filters_condition_language_price_iconic(index):
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_raw("Charizard ex", "006", 60.0, cond="EX-NM"),
                              index, CTX, pl.KIND_RAW) is None
    assert sc.process_listing(_raw("Charizard ex", "006", 60.0,
                                   set_hint="Pokemon Scarlet Violet - 151 sv2a - Base - Japanese"),
                              index, CTX, pl.KIND_RAW) is None
    assert sc.process_listing(_raw("Charizard ex", "006", 5.0), index, CTX, pl.KIND_RAW) is None
    assert sc.process_listing(_raw("Pidgeotto", "017", 20.0), index, CTX, pl.KIND_RAW) is None
    assert sc.stats["skip_condition"] == 1 and sc.stats["skip_language"] == 1
    assert sc.stats["skip_price_floor"] == 1 and sc.stats["skip_not_iconic"] == 1
    # --all-pokemon desliga o filtro
    sc2 = pl.Scanner(_settings(iconic_only=False))
    d = sc2.process_listing(_raw("Pidgeotto", "017", 20.0), index, CTX, pl.KIND_RAW)
    assert d is not None and d.pokemon == "" and d.pokemon_rank == 9999


def test_mid_fallback_price_is_match_review(index):
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw("Mewtwo", "150", 20.0), index, CTX, pl.KIND_RAW)
    assert d is not None and d.status == "MATCH_REVIEW" and "preço:mid" in d.review_reasons
    assert sc.stats["review"] == 1


def test_graded_listing_in_raw_pass_is_skipped(index):
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_slab("Charizard ex", "006", 50.0, "PSA 10"),
                              index, CTX, pl.KIND_RAW) is None
    assert sc.stats["skip_graded_in_raw"] == 1


def test_slab_uses_pricecharting_grade_price(index, monkeypatch):
    calls = []

    def fake_ref(name, number, set_label, pc_key, cache_dir=None):
        calls.append((name, number, set_label, pc_key))
        return GradedRef(price=125.65, grade_key=pc_key,
                         url="https://www.pricecharting.com/game/pokemon-scarlet-&-violet-151/charizard-ex-6")

    monkeypatch.setattr(pl, "graded_reference", fake_ref)
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_slab("Charizard ex", "006", 80.0, "PSA 10"), index, CTX, pl.KIND_SLAB)
    assert d is not None and d.status == "OK"
    assert d.tcg_reference == 125.65 and d.ref_source == "pricecharting"
    assert d.listing_type == "PSA 10" and d.price_field_used == "PSA 10"
    assert d.ref_url.startswith("https://www.pricecharting.com/")
    assert calls == [("Charizard ex - 006/165", "006/165", SET, "PSA 10")]
    row = d.as_row()
    assert row["ref_url"] == d.ref_url and row["tcg_url"].startswith("https://www.tcgplayer.com/")


def test_slab_out_of_scope_and_proxy_and_no_reference(index, monkeypatch):
    monkeypatch.setattr(pl, "graded_reference",
                        lambda *a, **k: GradedRef(price=100.0, grade_key=a[3], url="https://pc/x"))
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_slab("Charizard ex", "006", 50.0, "CGC 10 GEM", "CGC"),
                              index, CTX, pl.KIND_SLAB) is None
    assert sc.process_listing(_slab("Charizard ex", "006", 50.0, "PSA 8"),
                              index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["skip_grade_out_of_scope"] == 2
    d = sc.process_listing(_slab("Charizard ex", "006", 50.0, "BGS 9.5", "BGS"),
                           index, CTX, pl.KIND_SLAB)
    assert d is not None and d.status == "MATCH_REVIEW" and d.ref_source == "pricecharting-proxy"
    assert d.price_field_used == "GRADE 9.5"
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: None)
    assert sc.process_listing(_slab("Charizard ex", "006", 50.0, "PSA 10"),
                              index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["slab_no_reference"] == 1


def test_best_deals_dedupes_same_listing_and_ranks(index):
    sc = pl.Scanner(_settings())
    best = pl.BestDeals(top_n=50)
    L = _raw("Charizard ex", "006", 60.0)
    for _ in range(2):
        best.add(sc.process_listing(L, index, CTX, pl.KIND_RAW), gate=0.80, threshold=0.20)
    best.add(sc.process_listing(_raw("Charizard ex", "006", 70.0), index, CTX, pl.KIND_RAW),
             gate=0.80, threshold=0.20)
    q = best.qualifying()
    assert len(q) == 2
    assert q[0].listing.price == 60.0  # maior ROI primeiro
