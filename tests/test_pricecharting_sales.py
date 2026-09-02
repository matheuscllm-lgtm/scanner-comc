"""PriceCharting — vendas concluídas por certificadora+nota (mediana ≥3) e política de referência."""
from pathlib import Path

from comc_scanner import pricecharting_client as pc
from comc_scanner.grading import parse_grade

FIX = Path(__file__).parent / "fixtures"
PRODUCT = (FIX / "pc_product_charizard_ex_151.html").read_text(encoding="utf-8")
SEARCH = (FIX / "pc_search_charizard_ex_151.html").read_text(encoding="utf-8")


def _sale(date, price, title):
    return {"date": date, "price": price, "title": title, "bucket": "x", "source": "ebay"}


def test_parse_graded_sales_from_real_page():
    sales = pc.parse_graded_sales(PRODUCT)
    assert len(sales) >= 60
    assert all(s["date"] and s["price"] > 0 and s["title"] for s in sales)
    psa9 = pc.comparable_sales(sales, "PSA", 9.0)
    assert len(psa9) >= 3 and all("PSA 9" in s["title"].upper() for s in psa9)
    assert not pc.comparable_sales(sales, "BGS", 9.5)  # nenhuma venda BGS 9.5 nesta página


def test_comparable_sales_exact_grader_and_grade_only():
    sales = [
        _sale("2026-08-01", 50.0, "Charizard ex 006 BGS 9.5 GEM MINT"),
        _sale("2026-08-02", 55.0, "Charizard ex BGS 9.5"),
        _sale("2026-08-03", 70.0, "Charizard ex BGS 9 MINT"),          # nota errada
        _sale("2026-08-04", 65.0, "Charizard ex TAG 9.5"),              # certificadora errada
        _sale("2026-08-05", 30.0, "Charizard ex BGS 9.5 Japanese"),     # idioma
        _sale("2026-08-06", 60.0, "Charizard ex CGC 10 Pristine"),
        _sale("2026-08-07", 40.0, "Charizard ex CGC 10 Gem Mint"),
    ]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 9.5)] == [50.0, 55.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "CGC", 10.0, "PRISTINE")] == [60.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "CGC", 10.0, "GEM")] == [40.0]
    assert [s["price"] for s in pc.comparable_sales(sales, "BGS", 9.0)] == [70.0]


def test_median_requires_three_sales_and_uses_recent_window():
    assert pc.median_recent([_sale("2026-08-01", 10.0, "x"), _sale("2026-08-02", 20.0, "x")]) == (None, 2)
    sales = [_sale(f"2026-08-{d:02d}", float(d), "x") for d in range(1, 16)]  # 15 vendas
    med, n = pc.median_recent(sales)
    assert n == 10 and med == 10.5  # 10 mais recentes: 6..15 -> mediana 10.5


def _page_with_sales(prices, label="BGS 9.5 GEM MINT", table="completed-auctions-box-only"):
    rows = "".join(
        f'<tr id="ebay-{i}"><td class="date">2026-08-{i:02d}</td><td>Charizard ex 006 {label}</td>'
        f'<td><span class="js-price">${p:.2f}</span></td></tr>' for i, p in enumerate(prices, 1))
    return ('<div id="full-prices"><table><tr><td>Grade 9.5</td><td>$25.00</td></tr>'
            '<tr><td>TAG 10</td><td>$77.00</td></tr></table></div>'
            f'<div class="{table}"><table>{rows}</table></div>')


def test_graded_reference_uses_sales_median_when_no_exact_column(monkeypatch, tmp_path):
    page = _page_with_sales((80.0, 90.0, 100.0, 300.0))
    monkeypatch.setattr(pc, "fetch_page",
                        lambda url, cache_dir=None: SEARCH if "search-products" in url else page)
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("BGS", "9_5", ""), cache_dir=str(tmp_path))
    assert ref is not None and ref.method == "sales" and ref.n_sales == 4
    assert ref.price == 95.0 and ref.grade_key == "vendas BGS 9.5 (n=4)"


def test_graded_reference_falls_back_to_generic_bucket_only_as_proxy(monkeypatch, tmp_path):
    page = _page_with_sales((80.0, 90.0))  # só 2 vendas -> insuficiente
    monkeypatch.setattr(pc, "fetch_page",
                        lambda url, cache_dir=None: SEARCH if "search-products" in url else page)
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("TAG", "9_5", ""), cache_dir=str(tmp_path))
    assert ref is not None and ref.method == "proxy" and ref.is_proxy
    assert ref.price == 25.0 and ref.grade_key == "GRADE 9.5" and ref.n_sales == 0


def test_tag_10_is_an_exact_column(monkeypatch, tmp_path):
    page = _page_with_sales(())
    monkeypatch.setattr(pc, "fetch_page",
                        lambda url, cache_dir=None: SEARCH if "search-products" in url else page)
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151",
                              parse_grade("TAG", "10", ""), cache_dir=str(tmp_path))
    assert ref is not None and ref.method == "column" and ref.price == 77.0
