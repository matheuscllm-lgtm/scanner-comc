"""PriceCharting (offline): parse de preço por grade, busca, guardas de match e
graded_reference ponta a ponta (vendas = referência; coluna exata = só informação)."""
import datetime as dt
from pathlib import Path

from comc_scanner import pricecharting_client as pc
from comc_scanner.grading import parse_grade

FIX = Path(__file__).parent / "fixtures"
PRODUCT = (FIX / "pc_product_charizard_ex_151.html").read_text(encoding="utf-8")
SEARCH = (FIX / "pc_search_charizard_ex_151.html").read_text(encoding="utf-8")
BASE = (FIX / "pc_product_charizard_base_4.html").read_text(encoding="utf-8")


def test_parse_grade_prices_from_real_product_page():
    prices = pc.parse_grade_prices(PRODUCT)
    assert prices["PSA 10"] == 125.65
    assert prices["CGC 10 PRISTINE"] == 55.0
    assert prices["BGS 10"] == 163.0
    assert prices["GRADE 9"] == 21.95  # bucket genérico (todas as certificadoras)
    assert prices["RAW"] == 8.05


def test_parse_grade_prices_from_base_set_page():
    prices = pc.parse_grade_prices(BASE)
    assert prices["PSA 10"] == 13156.09 and prices["BGS 10"] == 17103.0
    assert prices["BGS 10 BLACK"] == 85515.0 and prices["CGC 10 PRISTINE"] == 20800.0
    assert prices["CGC 10"] == 4597.84 and prices["GRADE 8"] == 1160.22
    assert "ACE 10" not in prices  # célula "-"


def test_search_paths_accept_absolute_hrefs_and_dedupe():
    paths = pc.search_card_paths(SEARCH)
    assert paths[0] == "/game/pokemon-scarlet-&-violet-151/charizard-ex-6"
    assert len(paths) == len(set(paths))
    assert any("japanese" in p for p in paths)


def test_choose_path_prefers_english_console_matching_set_and_number():
    paths = pc.search_card_paths(SEARCH)
    assert pc.choose_path(paths, "Charizard ex", "6", "SV: Scarlet & Violet 151") == \
        "/game/pokemon-scarlet-&-violet-151/charizard-ex-6"
    # set diferente -> None (nunca casa cross-set / outra língua)
    assert pc.choose_path(paths, "Charizard ex", "6", "SV: Paldean Fates") is None
    assert pc.choose_path(paths, "Charizard", "6", "SV: Scarlet & Violet 151") is None  # falta 'ex'


def test_console_and_slug_guards():
    p = "/game/pokemon-base-set/charizard-4"
    assert pc.console_matches(p, "Base Set")
    assert not pc.console_matches("/game/pokemon-japanese-base-set/charizard-4", "Base Set")
    assert pc.slug_matches(p, "Charizard", "4/102")
    assert not pc.slug_matches("/game/pokemon-base-set/dark-charizard-4", "Charizard", "4")


def test_graded_reference_end_to_end_with_stubbed_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "_today", lambda: dt.date(2026, 9, 2))  # dia da captura
    calls = []

    def fake_fetch(url, cache_dir=None):
        calls.append(url)
        return SEARCH if "search-products" in url else PRODUCT

    monkeypatch.setattr(pc, "fetch_page", fake_fetch)
    args = ("Charizard ex", "6", "SV: Scarlet & Violet 151")
    ref = pc.graded_reference(*args, parse_grade("PSA", "10", ""), cache_dir=str(tmp_path))
    assert isinstance(ref, pc.SalesRef)
    # referência = mediana das vendas "PSA 10"; a coluna PSA 10 ($125.65) vai só como informação
    assert ref.liquidity == "ok" and ref.window_days == 180 and ref.n_sales >= 3
    assert ref.price != 125.65 and ref.column_price == 125.65
    assert ref.label.startswith("vendas PSA 10 (n=")
    assert ref.url.endswith("/game/pokemon-scarlet-&-violet-151/charizard-ex-6")
    assert len(calls) == 2
    ref9 = pc.graded_reference(*args, parse_grade("PSA", "9", ""), cache_dir=str(tmp_path))
    # "Grade 9" é bucket genérico -> nem referência nem informação; vendas "PSA 9" mandam
    assert ref9.liquidity == "ok" and ref9.n_sales >= 3 and ref9.column_price is None
    assert ref9.label.startswith("vendas PSA 9 (n=")
    # BGS 9.5: só 2 vendas, ambas com mais de 365 dias -> None (nunca "Grade 9.5" como proxy)
    assert pc.graded_reference(*args, parse_grade("BGS", "9_5", ""), cache_dir=str(tmp_path)) is None


def test_graded_reference_none_when_search_has_no_match(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "fetch_page", lambda url, cache_dir=None: SEARCH)
    assert pc.graded_reference("Charizard", "4/102", "Base Set", parse_grade("PSA", "10", ""),
                               cache_dir=str(tmp_path)) is None


def test_cache_dir_is_scoped_to_today(tmp_path):
    d = pc.today_cache_dir(tmp_path)
    assert d.name == pc.today_stamp() and d.parent == tmp_path
