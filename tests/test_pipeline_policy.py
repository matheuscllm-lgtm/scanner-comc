"""Políticas do operador (2026-09-02): condição por era, teto de orçamento, referência por vendas."""
from pathlib import Path

import pytest

from comc_scanner import pipeline as pl
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.normalize import normalize_set
from comc_scanner.pricecharting_client import SalesRef
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


def _raw(price, cond="NM"):
    return ComcListing(raw_name="Charizard ex", price=price, url=f"https://www.comc.com/x/{price}",
                       set_hint="Pokemon Scarlet Violet - 151 sv2a - Base", number_hint="006",
                       condition=cond, item_id=f"c{price}")


def _slab(price, grade, grader="PSA"):
    L = _raw(price, cond=grade.split(" ")[1])
    L.graded, L.grader, L.grade = True, grader, grade
    return L


def test_condition_allowlist_depends_on_era(index):
    sc = pl.Scanner(_settings())
    assert sc._condition_ok(_raw(60.0, "EX-NM"), era="vintage") is True
    assert sc._condition_ok(_raw(60.0, "EX-NM"), era="recent") is False
    assert sc._condition_ok(_raw(60.0, "EX-NM"), era="") is False
    assert sc._condition_ok(_raw(60.0, "NM"), era="vintage") is True
    assert sc._condition_ok(_raw(60.0, "LP"), era="vintage") is False
    sc.process_listing(_raw(60.0, "EX-NM"), index, CTX, pl.KIND_RAW, era="recent")
    assert sc.stats["skip_condition"] == 1
    assert sc.process_listing(_raw(60.0, "EX-NM"), index, CTX, pl.KIND_RAW, era="vintage") is not None


def test_price_ceiling_cuts_before_reference_lookup(index, monkeypatch):
    called = []
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: called.append(1) or None)
    sc = pl.Scanner(_settings(max_comc_price=100.0))
    assert sc.process_listing(_slab(150.0, "PSA 10"), index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["skip_price_ceiling"] == 1 and called == []
    assert pl.Scanner(_settings())._price_ceiling_ok(_raw(9999.0)) is True  # 0 = sem teto


def test_slab_sales_median_reference_can_be_ok(index, monkeypatch):
    monkeypatch.setattr(pl, "graded_reference",
                        lambda *a, **k: SalesRef(price=95.0, n_sales=4, window_days=180,
                                                 liquidity="ok", url="https://pc/x",
                                                 label="vendas BGS 9.5 (n=4, 2026-04..2026-08)"))
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_slab(60.0, "BGS 9.5", "BGS"), index, CTX, pl.KIND_SLAB)
    assert d is not None and d.status == "OK" and d.ref_source == "pricecharting-sales"
    assert d.as_row()["price_field"] == "vendas BGS 9.5 (n=4, 2026-04..2026-08)"


def test_slab_without_comparable_sales_is_dropped_never_proxied(index, monkeypatch):
    """Sem ≥1 venda da MESMA certificadora+nota a fonte devolve None: nenhum bucket
    genérico ("Grade 9.5") ou nota vizinha vira referência — nem para triagem."""
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: None)
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_slab(15.0, "TAG 9.5", "TAG"), index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["slab_no_reference"] == 1 and sc.stats["review"] == 0


