"""PriceCharting (offline): parse de preço por grade, busca e guardas de match."""
from pathlib import Path

from comc_scanner import pricecharting_client as pc

FIX = Path(__file__).parent / "fixtures"
PRODUCT = (FIX / "pc_product_charizard_ex_151.html").read_text(encoding="utf-8")
SEARCH = (FIX / "pc_search_charizard_ex_151.html").read_text(encoding="utf-8")


def test_parse_grade_prices_from_real_product_page():
    prices = pc.parse_grade_prices(PRODUCT)
    assert prices["PSA 10"] == 125.65
    assert prices["CGC 10 PRISTINE"] == 55.0
    assert prices["BGS 10"] == 163.0
    assert prices["PSA 9"] == 21.95
    assert prices["RAW"] == 8.05


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
    calls = []

    def fake_fetch(url, cache_dir=None):
        calls.append(url)
        return SEARCH if "search-products" in url else PRODUCT

    monkeypatch.setattr(pc, "fetch_page", fake_fetch)
    ref = pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151", "PSA 10",
                              cache_dir=str(tmp_path))
    assert ref is not None
    assert ref.price == 125.65 and ref.grade_key == "PSA 10"
    assert ref.url.endswith("/game/pokemon-scarlet-&-violet-151/charizard-ex-6")
    assert len(calls) == 2
    # grade sem coluna na página -> None (nunca inventa)
    assert pc.graded_reference("Charizard ex", "6", "SV: Scarlet & Violet 151", "TAG 10",
                               cache_dir=str(tmp_path)) is None


def test_cache_dir_is_scoped_to_today(tmp_path):
    d = pc.today_cache_dir(tmp_path)
    assert d.name == pc.today_stamp() and d.parent == tmp_path
