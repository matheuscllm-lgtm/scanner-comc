"""PriceCharting — vendas concluídas: parse de TODOS os baldes com dedupe, comparáveis
exatos (certificadora+nota+subcategoria+variante), vendas LP com referência LP própria e
janelas 180 (ok) / 365 (low) / 1–2 vendas (thin) / nada (None).

Fixtures reais: ``pc_product_charizard_base_4.html`` (Charizard 4/102 Base Set, capturada
2026-09-02: 375 vendas em 19 divs, 6 títulos LP, 16 PSA 8) e ``pc_product_charizard_ex_151``.
``_today`` é congelado no dia da captura para as janelas de recência não envelhecerem."""
import dataclasses
import datetime as dt
import re
from pathlib import Path

import pytest

from comc_scanner import pricecharting_client as pc
from comc_scanner.grading import parse_grade

FIX = Path(__file__).parent / "fixtures"
PRODUCT = (FIX / "pc_product_charizard_ex_151.html").read_text(encoding="utf-8")
SEARCH = (FIX / "pc_search_charizard_ex_151.html").read_text(encoding="utf-8")
BASE = (FIX / "pc_product_charizard_base_4.html").read_text(encoding="utf-8")
CAPTURE_DAY = dt.date(2026, 9, 2)
BASE_SEARCH = ('<a href="https://www.pricecharting.com/game/pokemon-base-set/charizard-4">x</a>'
               '<a href="https://www.pricecharting.com/game/pokemon-japanese-base-set/charizard-4">x</a>')


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(pc, "_today", lambda: CAPTURE_DAY)


def _sale(date, price, title, sale_id=None):
    return {"date": date, "price": price, "title": title, "bucket": "x", "source": "ebay",
            "sale_id": sale_id or f"{abs(hash((date, price, title)))}"}


def _day(i):
    """Data ISO de `i` dias atrás (relativa a pc._today, que os testes podem congelar)."""
    return (pc._today() - dt.timedelta(days=i)).isoformat()


# --- parse_sales: todos os baldes, dedupe, título limpo ----------------------------------

def test_parse_sales_scans_every_bucket_of_real_page_and_dedupes():
    sales = pc.parse_sales(BASE)
    assert len(sales) == 375  # 19 divs completed-auctions-*, ids únicos
    assert pc.parse_graded_sales is pc.parse_sales  # alias de compatibilidade
    assert {"date", "price", "title", "bucket", "source", "sale_id"} <= set(sales[0])
    assert len({(s["source"], s["sale_id"]) for s in sales}) == 375
    buckets = {s["bucket"] for s in sales}
    assert {"completed-auctions-used", "completed-auctions-graded", "completed-auctions-grade-three",
            "completed-auctions-loose-and-manual"} <= buckets
    assert all(s["date"] and s["price"] > 0 and s["title"] for s in sales)
    assert all("Time Warp" not in s["title"] and "to see photos" not in s["title"]
               and not s["title"].startswith("OK ") for s in sales)
    assert sales[0]["title"] == "Pokémon 1999 Base Set Charizard #4/102 Unlimited Holo 4/102"
    assert sales[0]["sale_id"] == "407171673042" and sales[0]["source"] == "ebay"


def test_parse_sales_old_fixture_has_more_rows_than_three_buckets():
    sales = pc.parse_sales(PRODUCT)
    assert len(sales) == 215
    psa9 = pc.comparable_sales(sales, "PSA", 9.0)
    assert len(psa9) >= 3 and all("PSA 9" in s["title"].upper() for s in psa9)
    assert len(pc.comparable_sales(sales, "BGS", 9.5)) < pc.MIN_COMPARABLE_SALES


def _row(sale_id, date, title, price, source="ebay", with_tour=True):
    tour = ('<td class="image"><div class="tour">Time Warp shows photos of completed sales.<br>'
            '<a class="tour-link" href="/x">>Subscribe</a> ($6/month) to see photos. '
            '<a class="done" href="#">OK</a></div></td>') if with_tour else ""
    return (f'<tr id="{source}-{sale_id}"><td class="date">{date}</td>{tour}'
            f'<td class="title"><a href="https://ebay/{sale_id}">{title}</a> [eBay]</td>'
            f'<td class="numeric"><span class="js-price">${price:.2f}</span></td></tr>')


def test_parse_sales_dedupes_rows_repeated_across_combined_divs():
    page = ('<div class="completed-auctions-used"><table>'
            + _row(1, "2026-08-01", "Charizard LP", 300.0) + _row(2, "2026-08-02", "Charizard NM", 400.0)
            + '</table></div><div class="completed-auctions-loose-and-box"><table>'
            + _row(1, "2026-08-01", "Charizard LP", 300.0) + _row(3, "2026-08-03", "Charizard PSA 9", 900.0)
            + '</table></div><div class="completed-auctions-grade-three"></div>')
    sales = pc.parse_sales(page)
    assert [(s["sale_id"], s["bucket"]) for s in sales] == [
        ("1", "completed-auctions-used"), ("2", "completed-auctions-used"),
        ("3", "completed-auctions-loose-and-box")]
    assert [s["title"] for s in sales] == ["Charizard LP", "Charizard NM", "Charizard PSA 9"]
    assert sales[0]["price"] == 300.0 and sales[0]["date"] == "2026-08-01"


def test_parse_sales_title_fallback_without_title_cell_strips_boilerplate():
    page = ('<div class="completed-auctions-used"><table><tr id="ebay-9"><td class="date">2026-08-01</td>'
            '<td>Time Warp shows photos of completed sales. <a>>Subscribe</a> ($6/month) to see photos. '
            '<a>OK</a> Charizard ex 006 BGS 9.5 GEM MINT</td>'
            '<td><span class="js-price">$80.00</span></td></tr></table></div>')
    (s,) = pc.parse_sales(page)
    assert "Time Warp" not in s["title"] and "OK" not in s["title"]
    assert "Charizard ex 006 BGS 9.5 GEM MINT" in s["title"]


# --- variant_tokens ---------------------------------------------------------------------

@pytest.mark.parametrize("text,tokens", [
    ("Charizard 1st Edition Holo", {"1st"}),
    ("First Edition Shadowless Charizard", {"1st", "shadowless"}),
    ("Reverse Holo Staff Prerelease Cosmos foil", {"reverse", "staff", "prerelease", "cosmos"}),
    ("Pre-Release promo", {"prerelease", "promo"}),
    ("Pikachu Wizards Black Star Promos", {"promo"}),   # set no plural = mesmo token do título
    ("Misprint error card signed autograph", {"error", "signed"}),
    ("Autographed by artist", {"signed"}),
    ("1999 Pokemon Base Set Charizard 4/102 Unlimited Holo Rare", set()),
    ("Charizard Non-Shadowless Unlimited", set()),   # "non-shadowless" = unlimited, não é variante
    ("Firstborn Reverser Staffing Errors", set()),   # palavras inteiras apenas
    ("", set()),
])
def test_variant_tokens(text, tokens):
    got = pc.variant_tokens(text)
    assert isinstance(got, frozenset) and got == frozenset(tokens)


# --- comparable_sales: certificadora+nota exatas, subcategoria, variante ----------------

def test_comparable_sales_exact_grader_and_grade_only():
    sales = [
        _sale("2026-08-01", 50.0, "Charizard ex 006 BGS 9.5 GEM MINT"),
        _sale("2026-08-02", 55.0, "Charizard ex BGS 9.5"),
        _sale("2026-08-03", 70.0, "Charizard ex BGS 9 MINT"),          # nota errada
        _sale("2026-08-04", 65.0, "Charizard ex TAG 9.5"),              # certificadora errada
        _sale("2026-08-05", 30.0, "Charizard ex BGS 9.5 Japanese"),     # idioma
        _sale("2026-08-06", 60.0, "Charizard ex CGC 10 Pristine"),
        _sale("2026-08-07", 40.0, "Charizard ex CGC 10 Gem Mint"),
        _sale("2026-08-08", 52.0, "Charizard ex Beckett 9.5"),          # Beckett = BGS
    ]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 9.5)] == [50.0, 55.0, 52.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "CGC", 10.0, "PRISTINE")] == [60.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "CGC", 10.0, "GEM")] == [40.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 9.0)] == [70.0]


def test_bgs10_and_bgs10_black_label_are_exclusive():
    sales = [
        _sale("2026-08-01", 5000.0, "Charizard BGS 10 Black Label"),
        _sale("2026-08-02", 4800.0, "Charizard BLACK LABEL BGS 10 PRISTINE"),
        _sale("2026-08-03", 1500.0, "Charizard BGS 10 PRISTINE"),
        _sale("2026-08-04", 1400.0, "Charizard BGS 10 gold label"),
        _sale("2026-08-05", 900.0, "Charizard Black Star Promo BGS 10"),  # "black star" ≠ label
    ]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 10.0, "BLACK")] == [5000.0, 4800.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 10.0, "")] == [1500.0, 1400.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 10.0, "", variants={"promo"})] == [900.0]


def test_comparable_sales_requires_equal_variant_set():
    sales = [
        _sale("2026-08-01", 3000.0, "Charizard 1st Edition PSA 9"),
        _sale("2026-08-02", 300.0, "Charizard PSA 9 Unlimited"),
        _sale("2026-08-03", 6000.0, "Charizard 1st Edition Shadowless PSA 9"),
    ]
    assert [s["price"] for s in pc.comparable_sales(sales, "PSA", 9.0)] == [300.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "PSA", 9.0, variants=frozenset({"1st"}))] == [3000.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "PSA", 9.0, variants={"1st", "shadowless"})] == [6000.0]
    assert pc.comparable_sales(sales, "PSA", 9.0, variants={"reverse"}) == []


def test_psa8_comparables_in_base_set_fixture():
    sales = pc.parse_sales(BASE)
    psa8 = pc.comparable_sales(sales, "PSA", 8.0)
    assert len(psa8) >= pc.MIN_COMPARABLE_SALES
    assert all(re.search(r"\bPSA\s*-?\s*8\b", s["title"], re.I) for s in psa8)
    assert all("promo" not in s["title"].lower() for s in psa8)  # Celebrations Metal PROMO ≠ 4/102
    assert len(pc.comparable_sales(sales, "BGS", 9.5)) >= pc.MIN_COMPARABLE_SALES
    assert pc.comparable_sales(sales, "BGS", 10.0) == []   # coluna BGS 10 existe, venda nenhuma


# --- lp_sales -------------------------------------------------------------------------

def test_lp_sales_accepts_lp_or_lightly_played_only_without_other_signals():
    ok = [
        _sale("2026-08-01", 300.0, "Charizard 4/102 Base Set Holo LP"),
        _sale("2026-08-02", 310.0, "Charizard 4/102 Base Set Holo (LP) Ungraded"),
        _sale("2026-08-03", 320.0, "Charizard Lightly Played Holo"),
        _sale("2026-08-04", 330.0, "Charizard Holo Rare, LP +!"),
        _sale("2026-08-05", 340.0, "Charizard Lightly-Played WOTC"),
    ]
    bad = [
        _sale("2026-08-06", 900.0, "Charizard PSA 9 LP"),                 # nota
        _sale("2026-08-07", 400.0, "Charizard NM/LP"),                    # outra condição
        _sale("2026-08-08", 250.0, "Charizard LP/MP"),
        _sale("2026-08-09", 260.0, "Charizard Holo Played"),              # "Played" solto
        _sale("2026-08-10", 270.0, "Charizard LP Lightly Played Played"),  # "played" fora do LP
        _sale("2026-08-11", 280.0, "Charizard Holo Unlimited"),           # sem condição
        _sale("2026-08-12", 290.0, "Charizard LP Japanese"),
        _sale("2026-08-13", 295.0, "Charizard Lightly Played Near Mint"),
        _sale("2026-08-14", 296.0, "Charizard LP HP"),
        _sale("2026-08-15", 297.0, "Charizard LP Damaged"),
        _sale("2026-08-16", 298.0, "Charizard DMG LP"),
        _sale("2026-08-17", 299.0, "Charizard LP Moderately Played"),
        _sale("2026-08-18", 301.0, "Charizard Heavily Played LP"),
        _sale("2026-08-19", 0.0, "Charizard LP"),                         # preço zero
        _sale("2026-08-20", 302.0, "Charizard LP PSA ready"),             # certificadora solta
        _sale("2026-08-21", 303.0, "Charizard 1st Edition LP"),           # variante ≠ listagem
    ]
    got = pc.lp_sales(ok + bad)
    assert [s["price"] for s in got] == [300.0, 310.0, 320.0, 330.0, 340.0]
    assert [s["price"] for s in pc.lp_sales(ok + bad, variants={"1st"})] == [303.0]


def test_lp_sales_in_base_set_fixture():
    lp = pc.lp_sales(pc.parse_sales(BASE))
    assert len(lp) >= pc.MIN_COMPARABLE_SALES
    assert all("LP" in s["title"].upper() and s["price"] > 0 for s in lp)
    assert not any("LP/MP" in s["title"] for s in lp)
    assert not any(pc._ANY_GRADE_RE.search(s["title"]) for s in lp)


# --- sales_reference: janelas ok / low / thin / None -------------------------------------

def test_median_requires_three_sales_and_uses_recent_window():
    assert pc.median_recent([_sale("2026-08-01", 10.0, "x"), _sale("2026-08-02", 20.0, "x")]) == (None, 2)
    sales = [_sale(f"2026-08-{d:02d}", float(d), "x") for d in range(1, 16)]  # 15 vendas
    med, n = pc.median_recent(sales)
    assert n == 10 and med == 10.5  # 10 mais recentes: 6..15 -> mediana 10.5


def test_constants_match_operator_windows():
    assert (pc.SALES_MAX_AGE_DAYS, pc.SALES_LOW_LIQUIDITY_MAX_AGE_DAYS) == (180, 365)
    assert (pc.MIN_COMPARABLE_SALES, pc.SALES_WINDOW) == (3, 10)


def test_sales_ref_is_frozen_and_aliased():
    ref = pc.SalesRef(price=1.0, n_sales=3, window_days=180, liquidity="ok", url="u", label="l")
    assert ref.column_price is None
    assert pc.GradedRef is pc.SalesRef
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.price = 2.0


def test_sales_reference_ok_within_180_days():
    comps = [_sale(_day(10), 100.0, "x"), _sale(_day(20), 90.0, "x"), _sale(_day(30), 120.0, "x")]
    ref = pc.sales_reference(comps, "https://pc/x", "PSA 9")
    assert (ref.price, ref.n_sales, ref.window_days, ref.liquidity) == (100.0, 3, 180, "ok")
    assert ref.url == "https://pc/x" and ref.column_price is None
    assert re.fullmatch(r"vendas PSA 9 \(n=3, \d{4}-\d{2}\.\.\d{4}-\d{2}\)", ref.label)
    assert ref.label.endswith(f"{_day(30)[:7]}..{_day(10)[:7]})")


def test_sales_reference_low_liquidity_when_three_only_within_365_days():
    comps = [_sale(_day(10), 100.0, "x"), _sale(_day(200), 90.0, "x"), _sale(_day(300), 120.0, "x")]
    ref = pc.sales_reference(comps, "u", "BGS 9.5")
    assert (ref.price, ref.n_sales, ref.window_days, ref.liquidity) == (100.0, 3, 365, "low")
    assert ref.label.startswith("vendas BGS 9.5 (n=3, ")


def test_sales_reference_thin_for_one_or_two_sales_unless_disallowed():
    comps = [_sale(_day(10), 100.0, "x"), _sale(_day(200), 90.0, "x")]
    ref = pc.sales_reference(comps, "u", "TAG 9.5")
    assert (ref.price, ref.n_sales, ref.window_days, ref.liquidity) == (95.0, 2, 365, "thin")
    assert pc.sales_reference(comps, "u", "LP", allow_thin=False) is None
    one = pc.sales_reference(comps[:1], "u", "TAG 9.5")
    assert (one.price, one.n_sales, one.liquidity) == (100.0, 1, "thin")


def test_sales_reference_none_when_no_sales_within_365_days():
    assert pc.sales_reference([], "u", "PSA 10") is None
    old = [_sale(_day(400), 100.0, "x"), _sale(_day(500), 90.0, "x"), _sale(_day(600), 120.0, "x")]
    assert pc.sales_reference(old, "u", "PSA 10") is None
    assert pc.sales_reference(old, "u", "PSA 10", allow_thin=False) is None


def test_sales_reference_median_of_ten_most_recent_but_counts_all_in_window():
    comps = [_sale(_day(i), float(i), "x") for i in range(1, 16)]  # 15 vendas em 180 dias
    ref = pc.sales_reference(comps, "u", "PSA 8")
    assert ref.price == 5.5 and ref.n_sales == 15 and ref.liquidity == "ok"  # mediana de 1..10


# --- graded_reference / raw_condition_reference (fetch stubado) ---------------------------

def _page_with_sales(prices, label="BGS 9.5 GEM MINT", table="completed-auctions-box-only",
                     columns='<tr><td>Grade 9.5</td><td>$25.00</td></tr><tr><td>TAG 10</td><td>$77.00</td></tr>'):
    rows = "".join(_row(i, _day(i), f"Charizard ex 006 {label}", p) for i, p in enumerate(prices, 1))
    return (f'<div id="full-prices"><table>{columns}</table></div>'
            f'<div class="{table}"><table>{rows}</table></div>')


def _stub_fetch(monkeypatch, page, search=SEARCH):
    monkeypatch.setattr(pc, "fetch_page",
                        lambda url, cache_dir=None: search if "search-products" in url else page)


def test_graded_reference_uses_sales_median_never_generic_bucket(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((80.0, 90.0, 100.0, 300.0)))
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("BGS", "9_5", ""), cache_dir=str(tmp_path))
    assert isinstance(ref, pc.SalesRef)
    assert (ref.price, ref.n_sales, ref.window_days, ref.liquidity) == (95.0, 4, 180, "ok")
    assert ref.label.startswith("vendas BGS 9.5 (n=4, ")
    assert ref.column_price is None  # "Grade 9.5" (25.00) é bucket genérico: nem informação
    assert ref.url.endswith("/game/pokemon-scarlet-&-violet-151/charizard-ex-6")


def test_graded_reference_two_sales_is_thin_not_proxy(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((80.0, 90.0), label="TAG 9.5"))
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("TAG", "9_5", ""), cache_dir=str(tmp_path))
    assert (ref.price, ref.n_sales, ref.liquidity, ref.window_days) == (85.0, 2, "thin", 365)
    assert ref.column_price is None and not hasattr(ref, "is_proxy")


def test_graded_reference_never_returns_column_without_sales(monkeypatch, tmp_path):
    """Caso Luxray: a coluna TAG 10 existe ($77) mas há 0 vendas TAG 10 -> None."""
    _stub_fetch(monkeypatch, _page_with_sales(()))
    assert pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                               parse_grade("TAG", "10", ""), cache_dir=str(tmp_path)) is None


def test_graded_reference_attaches_exact_column_as_information_only(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((70.0, 75.0, 80.0), label="TAG 10"))
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("TAG", "10", ""), cache_dir=str(tmp_path))
    assert ref.price == 75.0 and ref.column_price == 77.0 and ref.liquidity == "ok"
    assert ref.label.startswith("vendas TAG 10 (n=3, ")


def test_graded_reference_black_label_needs_black_in_titles(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((1500.0, 1400.0, 1450.0), label="BGS 10 PRISTINE",
                                              columns='<tr><td>BGS 10</td><td>$1,600.00</td></tr>'
                                                      '<tr><td>BGS 10 Black</td><td>$9,000.00</td></tr>'))
    black = parse_grade("BGS", "10", "X [BGS 10 Black Label]")
    assert pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151", black,
                               cache_dir=str(tmp_path)) is None
    gold = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                               parse_grade("BGS", "10", "X [BGS 10]"), cache_dir=str(tmp_path))
    assert gold.price == 1450.0 and gold.column_price == 1600.0
    assert gold.label.startswith("vendas BGS 10 (n=3, ")


def test_graded_reference_passes_variants_to_comparables(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((10.0, 11.0, 12.0), label="1st Edition PSA 9"))
    args = ("Charizard ex", "6", "SV: Scarlet & Violet 151", parse_grade("PSA", "9", ""))
    assert pc.graded_reference(*args, cache_dir=str(tmp_path)) is None
    ref = pc.graded_reference(*args, cache_dir=str(tmp_path), variants=frozenset({"1st"}))
    assert ref.price == 11.0 and ref.n_sales == 3


def test_graded_reference_on_real_base_set_page(monkeypatch, tmp_path, frozen_today):
    _stub_fetch(monkeypatch, BASE, search=BASE_SEARCH)
    psa8 = pc.graded_reference("Charizard", "4/102", "Base Set", parse_grade("PSA", "8", ""),
                               cache_dir=str(tmp_path))
    assert psa8.url == "https://www.pricecharting.com/game/pokemon-base-set/charizard-4"
    assert psa8.liquidity == "ok" and psa8.n_sales >= 3 and psa8.window_days == 180
    assert psa8.column_price is None  # não há coluna "PSA 8" (Grade 8 é genérica)
    assert 1300.0 <= psa8.price <= 1600.0
    psa10 = pc.graded_reference("Charizard", "4/102", "Base Set", parse_grade("PSA", "10", ""),
                                cache_dir=str(tmp_path))
    assert psa10.liquidity == "ok" and psa10.column_price == 13156.09
    # coluna BGS 10 ($17,103) e BGS 10 Black ($85,515) existem, mas 0 vendas -> None
    assert pc.graded_reference("Charizard", "4/102", "Base Set", parse_grade("BGS", "10", ""),
                               cache_dir=str(tmp_path)) is None
    assert pc.graded_reference("Charizard", "4/102", "Base Set",
                               parse_grade("BGS", "10", "[BGS 10 Black Label]"), cache_dir=str(tmp_path)) is None


def test_raw_condition_reference_lp_on_real_base_set_page(monkeypatch, tmp_path, frozen_today):
    _stub_fetch(monkeypatch, BASE, search=BASE_SEARCH)
    ref = pc.raw_condition_reference("Charizard", "4/102", "Base Set", cache_dir=str(tmp_path))
    assert isinstance(ref, pc.SalesRef)
    assert (ref.price, ref.n_sales, ref.window_days, ref.liquidity) == (463.4, 5, 180, "ok")
    assert ref.label == "vendas LP (n=5, 2026-08..2026-09)" and ref.column_price is None
    assert ref.url.endswith("/game/pokemon-base-set/charizard-4")
    assert pc.raw_condition_reference("Charizard", "4/102", "Base Set", cache_dir=str(tmp_path),
                                      variants={"1st"}) is None


def test_raw_condition_reference_requires_three_lp_sales(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, _page_with_sales((300.0, 320.0), label="Holo LP"))
    assert pc.raw_condition_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                                      cache_dir=str(tmp_path)) is None  # 2 vendas: LP exige ≥3
    _stub_fetch(monkeypatch, _page_with_sales((300.0, 320.0, 310.0), label="Holo LP"))
    ref = pc.raw_condition_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                                     cache_dir=str(tmp_path))
    assert (ref.price, ref.n_sales, ref.liquidity) == (310.0, 3, "ok")


def test_raw_condition_reference_only_supports_lp(tmp_path):
    with pytest.raises(ValueError):
        pc.raw_condition_reference("Charizard", "4", "Base Set", condition="NM", cache_dir=str(tmp_path))


def test_product_page_none_without_match_and_pc_error_without_tables(monkeypatch, tmp_path):
    _stub_fetch(monkeypatch, "<html><body>" + "layout novo " * 500 + "</body></html>")
    assert pc._product_page("Charizard", "4", "Base Set", str(tmp_path)) is None  # busca 151 não casa
    with pytest.raises(pc.PcError):
        pc._product_page("Charizard ex", "6", "SV: Scarlet & Violet 151", str(tmp_path))
    with pytest.raises(pc.PcError):
        pc.raw_condition_reference("Charizard ex", "6", "SV: Scarlet & Violet 151", cache_dir=str(tmp_path))
    _stub_fetch(monkeypatch, PRODUCT)
    url, page = pc._product_page("Charizard ex", "6", "SV: Scarlet & Violet 151", str(tmp_path))
    assert url.endswith("/charizard-ex-6") and page is PRODUCT


def test_variant_tokens_exclude_non_comparable_products():
    """Ruído real da página do Charizard 4/102: "2021 Celebrations Metal UPC PSA 8" é OUTRO
    produto (metal, Classic Collection). Reimpressões/jumbo/custom/réplica também nunca
    são comparáveis com a carta da listagem (que não tem esses tokens)."""
    assert pc.variant_tokens("Charizard 4/102 2021 Celebrations Metal UPC PSA 8") == {"metal", "classic"}
    assert pc.variant_tokens("Charizard Classic Collection 4/102 PSA 10") == {"classic"}
    assert pc.variant_tokens("Charizard Jumbo oversized card") == {"jumbo"}
    for junk in ("custom Charizard", "Charizard replica", "Charizard proxy card",
                 "Charizard reprint", "fake Charizard"):
        assert pc.variant_tokens(junk) == {"custom"}, junk
    sales = [_sale("2026-08-01", 5.0, "Charizard 4/102 2021 Celebrations Metal UPC PSA 8"),
             _sale("2026-08-02", 1400.0, "1999 Pokemon Base Set Charizard 4/102 Holo PSA 8")]
    assert [x["price"] for x in pc.comparable_sales(sales, "PSA", 8.0)] == [1400.0]


def test_bgs10_black_label_in_sale_titles_needs_label_context_not_card_name():
    """Review PR A: "Black Kyurem" tem "black" no NOME da carta — não é etiqueta preta.
    Só "Black Label"/"BGS 10 Black" identificam a subcategoria."""
    sales = [_sale("2026-08-01", 300.0, "2013 Black Kyurem EX Plasma Freeze BGS 10 PRISTINE"),
             _sale("2026-08-02", 900.0, "Black Kyurem EX BGS 10 Black Label"),
             _sale("2026-08-03", 850.0, "Black Kyurem EX BGS 10 BLACK"),
             _sale("2026-08-04", 320.0, "Black Kyurem EX BGS 10 Gold Label")]
    assert [x["price"] for x in pc.comparable_sales(sales, "BGS", 10.0, "")] == [300.0, 320.0]
    assert [x["price"] for x in pc.comparable_sales(sales, "BGS", 10.0, "BLACK")] == [900.0, 850.0]


def test_parse_sales_stops_at_the_end_of_each_sales_table():
    """Review PR A: linhas <tr id="ebay-N"> fora das tabelas de vendas (carrossel de
    itens parecidos no rodapé) nunca entram como venda da carta."""
    row = ('<tr id="ebay-1"><td class="date">2026-08-01</td><td class="title">Charizard PSA 10</td>'
           '<td><span class="js-price">$100.00</span></td></tr>')
    junk = ('<tr id="ebay-999"><td class="date">2026-08-02</td><td class="title">Other card PSA 10</td>'
            '<td><span class="js-price">$5.00</span></td></tr>')
    body = ('<div class="completed-auctions-manual-only"><table>' + row + '</table></div>'
            '<div class="similar"><table>' + junk + '</table></div>')
    assert [x["sale_id"] for x in pc.parse_sales(body)] == ["1"]
