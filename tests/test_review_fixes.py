"""Achados das revisões 2026-09-02: fonte PriceCharting falhando ≠ 'sem venda', cache não
guarda bloqueio, recência das vendas, título com duas notas, sanidade coluna×vendas,
contadores novos, um erro de listagem não derruba o run."""
import datetime as dt
from pathlib import Path

import pytest

from comc_scanner import pipeline as pl
from comc_scanner import pricecharting_client as pc
from comc_scanner.config import load_settings
from comc_scanner.grading import parse_grade
from comc_scanner.models import ComcListing
from comc_scanner.normalize import normalize_set
from comc_scanner.pricecharting_client import PcError, SalesRef
from comc_scanner.reporter import classify_row, funnel_lines, render_row_line
from comc_scanner.tcg_index import TcgIndex

SET = "SV: Scarlet & Violet 151"
CTX = normalize_set(SET)
SEARCH = (Path(__file__).parent / "fixtures" / "pc_search_charizard_ex_151.html").read_text(encoding="utf-8")


def _day(i):
    return (pc._today() - dt.timedelta(days=i)).isoformat()


def _sale(days_ago, price, title="Charizard ex 006 BGS 9.5 GEM MINT"):
    return {"date": _day(days_ago), "price": price, "title": title, "bucket": "x", "source": "ebay"}


# --- PriceCharting: recência, exclusividade de nota, erros de fonte -------------------

def test_recent_only_drops_sales_older_than_180_days():
    sales = [_sale(10, 50.0), _sale(179, 55.0), _sale(181, 60.0), _sale(900, 65.0)]
    assert [s["price"] for s in pc.recent_only(sales)] == [50.0, 55.0]
    assert pc.median_recent(pc.recent_only(sales)) == (None, 2)  # 2 recentes < 3 -> sem referência


def test_title_citing_two_grades_is_excluded():
    sales = [
        _sale(1, 500.0, "Charizard ex PSA 9 MINT (comps to PSA 10 sold $500!)"),
        _sale(2, 20.0, "Charizard ex PSA 9 MINT"),
        _sale(3, 0.0, "Charizard ex PSA 9 MINT"),  # preço zero não conta
    ]
    assert [s["price"] for s in pc.comparable_sales(sales, "PSA", 9.0)] == [20.0]
    assert pc.comparable_sales(sales, "PSA", 10.0) == []
    cgc = [_sale(1, 60.0, "Charizard CGC 10 Pristine"), _sale(2, 40.0, "Charizard CGC 10 Gem Mint"),
           _sale(3, 45.0, "Charizard CGC 10 (flawless, pristine surface)")]
    assert [s["price"] for s in pc.comparable_sales(cgc, "CGC", 10.0, "PRISTINE")] == [60.0]
    assert [s["price"] for s in pc.comparable_sales(cgc, "CGC", 10.0, "GEM")] == [40.0, 45.0]


class _Resp:
    headers = {}

    def __init__(self, body):
        self._b = body.encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _raise(exc):
    raise exc


def test_fetch_page_never_caches_block_or_empty_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "REQUEST_GAP_SECONDS", 0.0)
    block = "<html><head><title>Just a moment...</title></head><body>" + "x" * 5000 + "</body></html>"
    monkeypatch.setattr(pc.urllib.request, "urlopen", lambda req, timeout=30: _Resp(block))
    with pytest.raises(PcError):
        pc.fetch_page("https://www.pricecharting.com/game/x/y", cache_dir=str(tmp_path))
    assert not list(pc.today_cache_dir(tmp_path).glob("*.html"))  # nada cacheado
    monkeypatch.setattr(pc.urllib.request, "urlopen", lambda req, timeout=30: _Resp("<html></html>"))
    with pytest.raises(PcError):
        pc.fetch_page("https://www.pricecharting.com/game/x/z", cache_dir=str(tmp_path))
    monkeypatch.setattr(pc.urllib.request, "urlopen",
                        lambda req, timeout=30: _raise(pc.urllib.error.URLError("dns")))
    with pytest.raises(PcError):
        pc.fetch_page("https://www.pricecharting.com/game/x/w", cache_dir=str(tmp_path))


def test_page_without_any_table_is_a_source_error_not_no_sales(monkeypatch, tmp_path):
    page = "<html><body>" + "layout novo " * 500 + "</body></html>"
    monkeypatch.setattr(pc, "fetch_page",
                        lambda url, cache_dir=None: SEARCH if "search-products" in url else page)
    with pytest.raises(PcError):
        pc.graded_reference("Charizard ex", "6", SET, parse_grade("PSA", "10", ""),
                            cache_dir=str(tmp_path))


# --- pipeline: erro de fonte contado à parte; circuit breaker; sanidade ------------

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


def _slab(price, grade="PSA 10", grader="PSA"):
    L = ComcListing(raw_name="Charizard ex", price=price, url=f"https://www.comc.com/x/{price}",
                    set_hint="Pokemon Scarlet Violet - 151 sv2a - Base", number_hint="006",
                    condition=grade.split(" ")[1], item_id=f"c{price}")
    L.graded, L.grader, L.grade = True, grader, grade
    return L


def test_pc_error_is_counted_separately_and_trips_breaker(index, monkeypatch):
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: _raise(PcError("429")))
    sc = pl.Scanner(_settings())
    for i in range(pl.Scanner.PC_MAX_CONSECUTIVE_ERRORS):
        assert sc.process_listing(_slab(50.0 + i), index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["slab_pc_error"] == 5 and sc.stats["slab_no_reference"] == 0
    assert sc._pc_down is True
    # com a fonte "caída", nem tenta mais (não martela o site) e segue contando como erro
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: _raise(AssertionError("não devia chamar")))
    assert sc.process_listing(_slab(99.0), index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["slab_pc_error"] == 6


def _ref(price, n=4, liquidity="ok", window=180, column=None, label="vendas PSA 10 (n=4, 2026-05..2026-08)"):
    return SalesRef(price=price, n_sales=n, window_days=window, liquidity=liquidity,
                    url="https://pc/x", label=label, column_price=column)


def test_pc_error_counter_resets_after_success(index, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] % 2:
            raise PcError("timeout")
        return _ref(200.0)

    monkeypatch.setattr(pl, "graded_reference", flaky)
    sc = pl.Scanner(_settings())
    for i in range(8):  # 120..127 vs ref 200 = 36-40% (abaixo do teto de desconto extremo)
        sc.process_listing(_slab(120.0 + i), index, CTX, pl.KIND_SLAB)
    assert sc._pc_down is False and sc.stats["slab_pc_error"] == 4 and sc.stats["ok"] == 4


def test_exact_column_far_from_sales_median_is_match_review(index, monkeypatch):
    """A referência É a mediana de vendas (220); a coluna exata do PC (500) entra só como
    sanidade: >30% de distância → MATCH_REVIEW · coluna÷vendas."""
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: _ref(220.0, n=5, column=500.0))
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_slab(150.0), index, CTX, pl.KIND_SLAB)
    assert d is not None and d.tcg_reference == 220.0 and d.status == "MATCH_REVIEW"
    assert any(r.startswith("coluna÷vendas") for r in d.review_reasons)
    row = d.as_row()
    assert row["ref_column_price"] == 500.0 and row["ref_n_sales"] == 5


def test_classify_row_flags_slab_with_raw_reference_and_funnel_keeps_unknown_keys():
    status, reasons = classify_row({"confidence": 0.95, "price_field": "market",
                                    "ref_source": "tcgplayer", "listing_type": "PSA 10"})
    assert status == "MATCH_REVIEW" and "slab×ref-raw" in reasons
    lines = funnel_lines({"seen": 3, "listing_errors": 2, "novo_contador": 7})
    assert "Listagens com erro interno (puladas): 2" in lines
    assert lines[-1] == "outros: novo_contador=7"


def test_zero_comparable_sales_is_no_reference_never_a_deal(index, monkeypatch):
    """Caso real Luxray ex (grupo 1, 2026-09-02): coluna exata CGC 10 Pristine no PC mas
    ZERO vendas comparáveis → a fonte devolve None → sem referência, sem oportunidade
    (contador `slab_no_reference`), nunca MATCH_REVIEW com preço de coluna."""
    monkeypatch.setattr(pl, "graded_reference", lambda *a, **k: None)
    sc = pl.Scanner(_settings())
    assert sc.process_listing(_slab(69.25, "CGC 10 PRISTINE", "CGC"), index, CTX, pl.KIND_SLAB) is None
    assert sc.stats["slab_no_reference"] == 1 and sc.stats["ok"] == 0 and sc.stats["review"] == 0


def test_thin_sales_is_match_review_and_low_liquidity_is_only_a_note(index, monkeypatch):
    monkeypatch.setattr(pl, "graded_reference",
                        lambda *a, **k: _ref(200.0, n=2, liquidity="thin", window=365))
    sc = pl.Scanner(_settings())
    d = sc.process_listing(_slab(100.0), index, CTX, pl.KIND_SLAB)
    assert d is not None and d.status == "MATCH_REVIEW" and "vendas<3(n=2)" in d.review_reasons
    monkeypatch.setattr(pl, "graded_reference",
                        lambda *a, **k: _ref(200.0, n=4, liquidity="low", window=365))
    d2 = sc.process_listing(_slab(101.0), index, CTX, pl.KIND_SLAB)
    assert d2 is not None and d2.status == "OK" and d2.ref_liquidity == "low"
    assert "baixa-liquidez" in render_row_line(d2.as_row(), 1)


def test_missing_ref_n_sales_is_unknown_not_zero():
    """Payload antigo sem o campo ref_n_sales: contagem DESCONHECIDA — não vira
    `vendas<3`. Com n=2 explícito, vira."""
    row = {"confidence": 0.95, "price_field": "vendas PSA 10 (n=?)", "ref_source": "pricecharting-sales",
           "listing_type": "PSA 10", "tcg_reference": 99.99}
    status, reasons = classify_row(row)
    assert status == "OK" and not any(r.startswith("vendas<3") for r in reasons)
    row["ref_n_sales"] = 2
    assert classify_row(row) == ("MATCH_REVIEW", ["vendas<3(n=2)"])
