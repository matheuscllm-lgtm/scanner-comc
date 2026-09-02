"""Raw LP (operador 2026-09-02): entra SÓ com referência LP (≥3 vendas "LP"/"Lightly
Played" da mesma carta+variante); pré-filtro seguro pelo teto NM; nunca LP vs NM."""
from pathlib import Path

import pytest

from comc_scanner import pipeline as pl
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.normalize import normalize_set
from comc_scanner.pricecharting_client import PcError, SalesRef
from comc_scanner.tcg_index import TcgIndex

SET = "SV: Scarlet & Violet 151"
CTX = normalize_set(SET)


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def index():
    idx = TcgIndex()
    idx.add_group(99, SET, "SV3PT5", [
        {"productId": 1, "groupId": 99, "name": "Charizard ex - 006/165", "cleanName": "Charizard ex",
         "url": "https://www.tcgplayer.com/product/1",
         "extendedData": [{"name": "Number", "value": "006/165"}, {"name": "Rarity", "value": "Double Rare"}]},
    ], [{"productId": 1, "subTypeName": "Holofoil", "marketPrice": 100.0, "midPrice": None,
         "lowPrice": None, "highPrice": None, "directLowPrice": None}])
    return idx


def _raw(price, cond="LP"):
    return ComcListing(raw_name="Charizard ex", price=price, url=f"https://www.comc.com/x/{price}",
                       set_hint="Pokemon Scarlet Violet - 151 sv2a - Base", number_hint="006",
                       condition=cond, item_id=f"c{price}")


def _lp_ref(price, n=4, liquidity="ok", window=180):
    return SalesRef(price=price, n_sales=n, window_days=window, liquidity=liquidity,
                    url="https://pc/x", label=f"vendas LP (n={n}, 2026-05..2026-08)")


def test_lp_above_safe_prefilter_is_dropped_without_querying_source(index, monkeypatch):
    called = []
    monkeypatch.setattr(pl, "raw_condition_reference", lambda *a, **k: called.append(1) or None)
    sc = pl.Scanner(_settings())  # NM market 100 × (1 − 0.20) = 80 → teto
    assert sc.process_listing(_raw(80.01), index, CTX, pl.KIND_RAW, era="recent") is None
    assert sc.stats["lp_prefilter"] == 1 and called == []


def test_lp_without_lp_sales_has_no_reference(index, monkeypatch):
    monkeypatch.setattr(pl, "raw_condition_reference", lambda *a, **k: None)
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_raw(40.0), index, CTX, pl.KIND_RAW, era="recent") is None
    assert sc.stats["lp_no_reference"] == 1 and sc.stats["ok"] == 0


def test_lp_compares_only_against_lp_median_never_nm(index, monkeypatch):
    seen = {}

    def fake(name, number, set_label, condition="LP", cache_dir=None, variants=frozenset()):
        seen.update(name=name, number=number, condition=condition, variants=variants)
        return _lp_ref(60.0)

    monkeypatch.setattr(pl, "raw_condition_reference", fake)
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw(40.0), index, CTX, pl.KIND_RAW, era="recent")
    assert d is not None and d.status == "OK"
    assert d.tcg_reference == 60.0 and d.ref_source == "pricecharting-sales-lp"  # não os 100 NM
    assert d.listing_type == "Raw LP" and abs(d.margin - (60.0 - 40.0) / 60.0) < 1e-9
    assert seen["condition"] == "LP" and seen["number"] == "006/165" and seen["variants"] == frozenset()
    row = d.as_row()
    assert row["price_field"].startswith("vendas LP") and row["ref_url"] == "https://pc/x"


def test_lp_pc_error_is_counted_as_source_error(index, monkeypatch):
    def boom(*a, **k):
        raise PcError("429")
    monkeypatch.setattr(pl, "raw_condition_reference", boom)
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_raw(40.0), index, CTX, pl.KIND_RAW, era="recent") is None
    assert sc.stats["lp_pc_error"] == 1 and sc.stats["lp_no_reference"] == 0


def test_lp_disabled_and_other_played_conditions_stay_out(index, monkeypatch):
    monkeypatch.setattr(pl, "raw_condition_reference", lambda *a, **k: _lp_ref(60.0))
    sc = pl.Scanner(_settings(lp_with_reference=False))
    assert sc.process_listing(_raw(40.0), index, CTX, pl.KIND_RAW, era="recent") is None
    assert sc.stats["skip_condition"] == 1
    sc2 = pl.Scanner(_settings())
    for cond in ("MP", "HP", "Noted", "EX-NM"):
        assert sc2.process_listing(_raw(40.0, cond), index, CTX, pl.KIND_RAW, era="recent") is None
    assert sc2.stats["skip_condition"] == 4
    # WotC (era vintage) segue aceitando EX-NM contra o preço NM do TCGplayer
    d = sc2.process_listing(_raw(40.0, "EX-NM"), index, CTX, pl.KIND_RAW, era="vintage")
    assert d is not None and d.ref_source == "tcgplayer" and d.listing_type == "Raw EX-NM"


def test_listing_variants_feed_the_comparable_filter(index, monkeypatch):
    seen = {}
    monkeypatch.setattr(pl, "raw_condition_reference",
                        lambda *a, **k: seen.update(k) or _lp_ref(60.0))
    L = _raw(40.0)
    L.raw_name = "Charizard ex - Reverse Holo"
    pl.Scanner(_settings()).process_listing(L, index, CTX, pl.KIND_RAW, era="recent")
    assert seen["variants"] == frozenset({"reverse"})
