"""Sinalização (2026-09-06): plausibilidade raw NM e desconto extremo → MATCH_REVIEW,
sem trocar o preço. Offline."""
from pathlib import Path

from comc_scanner import pipeline as pl
from comc_scanner import pricecharting_client as pc
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.normalize import normalize_set
from comc_scanner.reporter import (EXTREME_DISCOUNT_PERCENT, RAW_SALES_DEVIATION_MAX,
                                   classify_row, render_rows_table)
from comc_scanner.tcg_index import TcgIndex
from comc_summary import build_markdown, split_buckets

FIX = Path(__file__).parent / "fixtures"
BASE = (FIX / "pc_product_charizard_base_4.html").read_text(encoding="utf-8")
SET = "SV: Scarlet & Violet 151"
CTX = normalize_set(SET)


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


# --- ungraded_sales / raw_plausibility ----------------------------------------

def test_ungraded_sales_excludes_graded_and_foreign_keeps_any_condition():
    sales = [
        {"title": "Charizard 4/102 Base Set NM", "price": 300.0, "date": "2026-08-01"},
        {"title": "Charizard 4/102 LP", "price": 200.0, "date": "2026-08-02"},
        {"title": "Charizard 4/102 MP played", "price": 120.0, "date": "2026-08-03"},
        {"title": "Charizard 4/102 PSA 8", "price": 900.0, "date": "2026-08-04"},
        {"title": "Charizard 4/102 CGC", "price": 500.0, "date": "2026-08-05"},
        {"title": "Charizard Japanese 4/102", "price": 50.0, "date": "2026-08-06"},
        {"title": "Charizard 1st Edition 4/102", "price": 5000.0, "date": "2026-08-07"},
        {"title": "Charizard 4/102", "price": 0.0, "date": "2026-08-08"},
    ]
    out = pc.ungraded_sales(sales)
    assert [s["price"] for s in out] == [300.0, 200.0, 120.0]  # NM/LP/MP entram; nota, JP, 1st, 0 não
    assert [s["price"] for s in pc.ungraded_sales(sales, frozenset({"1st"}))] == [5000.0]


def test_ungraded_sales_in_real_base_set_fixture_are_plenty():
    comps = pc.ungraded_sales(pc.parse_sales(BASE))
    assert len(comps) >= 20
    assert all(not pc._ANY_GRADE_RE.search(s["title"]) for s in comps)


def test_raw_plausibility_is_median_of_loose_sales_never_thin(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "_product_page", lambda *a, **k: ("https://pc/x", BASE))
    ref = pc.raw_plausibility("Charizard", "004/102", "Base Set", cache_dir=str(tmp_path))
    if ref is not None:  # fixture pode ter envelhecido além de 365 dias
        assert ref.n_sales >= 3 and ref.price > 0 and ref.label.startswith("vendas raw")
    monkeypatch.setattr(pc, "sales_reference", lambda comps, url, what, allow_thin=True: ("thin" if allow_thin else None))
    assert pc.raw_plausibility("Charizard", "004/102", "Base Set", cache_dir=str(tmp_path)) is None


def test_raw_plausibility_none_without_page(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "_product_page", lambda *a, **k: None)
    assert pc.raw_plausibility("X", "1", "Base Set", cache_dir=str(tmp_path)) is None


# --- classify_row -------------------------------------------------------------------

def test_classify_flags_tcg_vs_raw_sales_divergence_only_for_tcgplayer_source():
    base = {"confidence": 0.95, "price_field": "market", "ref_source": "tcgplayer",
            "tcg_reference": 868.56}
    assert classify_row({**base, "raw_sales_median": 329.0}) == ("MATCH_REVIEW", ["TCG÷vendas-raw(329.00)"])
    assert classify_row({**base, "raw_sales_median": 600.0}) == ("OK", [])   # 31% < 40%
    assert classify_row({**base, "raw_sales_median": None}) == ("OK", [])
    assert classify_row({**base, "raw_sales_median": "abc"}) == ("OK", [])
    slab = {**base, "ref_source": "pricecharting-sales", "price_field": "vendas PSA 9 (n=5)",
            "ref_n_sales": 5, "raw_sales_median": 10.0}
    assert classify_row(slab) == ("OK", [])  # plausibilidade raw não se aplica a slab
    assert RAW_SALES_DEVIATION_MAX == 0.40


def test_classify_flags_extreme_discount_but_never_drops():
    row = {"confidence": 0.95, "price_field": "market", "margin_pct": 75.0}
    assert classify_row(row) == ("MATCH_REVIEW", [f"desconto-extremo(≥{EXTREME_DISCOUNT_PERCENT}%)"])
    assert classify_row({**row, "margin_pct": 59.99}) == ("OK", [])
    assert classify_row(row, extreme_pct=80) == ("OK", [])
    assert classify_row(row, extreme_pct=0) == ("OK", [])  # 0 desliga
    assert EXTREME_DISCOUNT_PERCENT == 60


def test_reasons_compose_and_render_in_status_cell():
    row = {"confidence": 0.85, "price_field": "mid", "ref_source": "tcgplayer",
           "tcg_reference": 100.0, "raw_sales_median": 40.0, "margin_pct": 70.0,
           "comc_price": 30.0, "card_number": "Charizard 4/102", "set": "Base Set"}
    status, reasons = classify_row(row)
    assert status == "MATCH_REVIEW"
    assert reasons == ["confiança<0.90", "preço:mid", "TCG÷vendas-raw(40.00)", "desconto-extremo(≥60%)"]
    line = render_rows_table([row]).splitlines()[2]
    assert "TCG÷vendas-raw(40.00)" in line and "desconto-extremo" in line


# --- pipeline -----------------------------------------------------------------------

def _index():
    idx = TcgIndex()
    idx.add_group(99, SET, "SV3PT5", [
        {"productId": 1, "groupId": 99, "name": "Charizard ex - 006/165", "cleanName": "Charizard ex",
         "url": "https://www.tcgplayer.com/product/1",
         "extendedData": [{"name": "Number", "value": "006/165"}, {"name": "Rarity", "value": "Double Rare"}]},
    ], [{"productId": 1, "subTypeName": "Holofoil", "marketPrice": 100.0, "midPrice": None,
         "lowPrice": None, "highPrice": None, "directLowPrice": None}])
    return idx


def _raw(price):
    return ComcListing(raw_name="Charizard ex", price=price, url=f"https://www.comc.com/x/{price}",
                       set_hint="Pokemon Scarlet Violet - 151 sv2a - Base", number_hint="006",
                       condition="NM", item_id=f"c{price}")


def test_pipeline_records_plausibility_and_reviews_divergence(monkeypatch):
    monkeypatch.setattr(pl, "product_page_url", lambda *a, **k: "https://pc/charizard-ex-6")
    monkeypatch.setattr(pl, "raw_plausibility",
                        lambda *a, **k: pc.SalesRef(price=40.0, n_sales=6, window_days=180,
                                                    liquidity="ok", url="https://pc/x",
                                                    label="vendas raw (n=6, 2026-03..2026-08)"))
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW)
    assert d is not None
    assert d.tcg_reference == 100.0 and d.ref_source == "tcgplayer"   # preço NÃO mudou
    assert d.raw_sales_median == 40.0 and d.raw_sales_n == 6
    assert d.status == "MATCH_REVIEW" and "TCG÷vendas-raw(40.00)" in d.review_reasons
    assert sc.stats["raw_plausibility_ok"] == 1 and sc.stats["review"] == 1
    assert d.as_row()["raw_sales_label"].startswith("vendas raw")


def test_pipeline_plausibility_agreement_keeps_ok_and_missing_is_counted(monkeypatch):
    monkeypatch.setattr(pl, "product_page_url", lambda *a, **k: "https://pc/charizard-ex-6")
    monkeypatch.setattr(pl, "raw_plausibility",
                        lambda *a, **k: pc.SalesRef(price=95.0, n_sales=4, window_days=180,
                                                    liquidity="ok", url="u", label="vendas raw (n=4)"))
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW).status == "OK"
    monkeypatch.setattr(pl, "raw_plausibility", lambda *a, **k: None)
    sc2 = pl.Scanner(_settings())
    d = sc2.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW)
    assert d.status == "OK" and d.raw_sales_median is None
    assert sc2.stats["raw_plausibility_missing"] == 1


def test_pipeline_plausibility_error_is_counted_and_never_blocks(monkeypatch):
    def boom(*a, **k):
        raise pc.PcError("down")
    monkeypatch.setattr(pl, "product_page_url", lambda *a, **k: "https://pc/charizard-ex-6")
    monkeypatch.setattr(pl, "raw_plausibility", boom)
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW)
    assert d is not None and d.status == "OK"
    assert sc.stats["raw_plausibility_error"] == 1 and sc._pc_down is False


def test_pipeline_plausibility_skipped_without_page_or_when_disabled(monkeypatch):
    called = []
    monkeypatch.setattr(pl, "raw_plausibility", lambda *a, **k: called.append(1) or None)
    sc = pl.Scanner(_settings())  # conftest: product_page_url -> None
    sc.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW)
    monkeypatch.setattr(pl, "product_page_url", lambda *a, **k: "https://pc/x")
    sc2 = pl.Scanner(_settings(raw_plausibility=False))
    sc2.process_listing(_raw(75.0), _index(), CTX, pl.KIND_RAW)
    assert called == []


def test_pipeline_extreme_discount_goes_to_review_not_dropped():
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_raw(30.0), _index(), CTX, pl.KIND_RAW)  # 70% de desconto
    assert d is not None and d.status == "MATCH_REVIEW"
    assert "desconto-extremo(≥60%)" in d.review_reasons and sc.stats["review"] == 1
    sc2 = pl.Scanner(_settings(extreme_discount_percent=0))
    assert sc2.process_listing(_raw(30.0), _index(), CTX, pl.KIND_RAW).status == "OK"


# --- entrega ------------------------------------------------------------------------

def _payload(rows, **over):
    p = {"scope": "grupo3", "generated_utc": "x", "min_discount_percent": 20, "min_comc_price": 10,
         "graded_allow": [], "iconic_only": False, "trust_confidence": 0.90,
         "extreme_discount_percent": 60, "top_n": 0, "count": len(rows), "funnel": {},
         "deals": rows, "low_confidence": []}
    p.update(over)
    return p


def _row(**over):
    r = {"margin_pct": 62.1, "roi_pct": 164.0, "comc_price": 329.0, "tcg_reference": 868.56,
         "spread_abs": 539.56, "pokemon": "Charizard", "card_number": "Charizard 004/102",
         "set": "Base Set", "listing_type": "Raw NM", "price_field": "market",
         "ref_source": "tcgplayer", "confidence": 0.95, "raw_sales_median": 329.0,
         "comc_url": "https://www.comc.com/x", "tcg_url": "https://www.tcgplayer.com/product/1"}
    r.update(over)
    return r


def test_summary_uses_run_extreme_threshold_and_flags_raw_divergence():
    ok, review, _ = split_buckets(_payload([_row()]))
    assert not ok and len(review) == 1
    md = build_markdown(_payload([_row()]), group=3)
    assert "TCG÷vendas-raw(329.00)" in md and "desconto-extremo(≥60%)" in md
    assert "868.56" in md  # preço de referência intacto
    ok2, review2, _ = split_buckets(_payload([_row(raw_sales_median=800.0)], extreme_discount_percent=0))
    assert len(ok2) == 1 and not review2  # run com teto desligado + sem divergência → OK
    ok3, _, _ = split_buckets(_payload([_row(raw_sales_median=800.0, margin_pct=62.1)]))
    assert not ok3  # JSON do run com teto 60 → revisão
