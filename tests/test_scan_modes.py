"""Offline tests: gramática da URL de browse, filtros NM/EN/piso/raridade, catálogo."""
from pathlib import Path

from comc_scanner.comc_scraper import build_browse_url
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.pipeline import Scanner


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_set_path_browse_url_drops_rcomc_by_default():
    url = build_browse_url(_settings(), era_path="1999/Pokemon_Base_Set_-_Base", page=2)
    assert url.startswith("https://www.comc.com/Cards/Pokemon/1999/Pokemon_Base_Set_-_Base,")
    assert ",rCOMC" not in url and url.endswith(",i100,p2")
    assert ",aUngraded," in url and ",gEX-NM," in url


def test_seller_repo_opt_in_when_set():
    assert ",rCOMC," in build_browse_url(_settings(comc_seller_repo="COMC"), era_path="1999/X")


def test_sort_defaults_to_highest_first_and_is_configurable():
    assert ",sh," in build_browse_url(_settings())
    assert ",sl," in build_browse_url(_settings(comc_sort="sl"))


def test_graded_facet_is_an_explicit_parameter():
    assert ",aUngraded," in build_browse_url(_settings())
    assert ",aGraded," in build_browse_url(_settings(), graded=True)


def _listing(cond):
    return ComcListing(raw_name="X", price=1.0, url="", condition=cond)


def test_condition_filter_is_strict_nm_by_default():
    sc = Scanner(_settings())
    assert sc._condition_ok(_listing("NM")) is True
    assert sc._condition_ok(_listing("nm")) is True
    for bad in ("EX-NM", "Mint", "LP", "MP", "HP", "Noted", "Raw", "Poor", "Damaged", "", "10"):
        assert sc._condition_ok(_listing(bad)) is False, bad


def test_condition_allowlist_is_configurable():
    sc = Scanner(_settings(comc_condition_allow=("nm", "ex-nm")))
    assert sc._condition_ok(_listing("EX-NM")) is True


def test_variant_filter_drops_foreign_language_printings():
    sc = Scanner(_settings())
    en = ComcListing(raw_name="Pikachu", price=1.0, url="",
                     set_hint="Pokemon Scarlet Violet - 151 sv2a - Base")
    kr = ComcListing(raw_name="Pikachu", price=1.0, url="",
                     set_hint="Pokemon Scarlet Violet - 151 sv2a - Base - Korean")
    jp = ComcListing(raw_name="Art Rare - Squirtle", price=1.0, url="",
                     set_hint="Pokemon Scarlet Violet - 151 sv2a - Base - Japanese")
    assert sc._variant_ok(en) is True and sc._variant_ok(kr) is False and sc._variant_ok(jp) is False


def test_price_floor_defaults_to_10_usd_and_zero_disables():
    sc = Scanner(_settings())
    assert sc._price_ok(ComcListing(raw_name="X", price=9.99, url="")) is False
    assert sc._price_ok(ComcListing(raw_name="X", price=10.00, url="")) is True
    sc0 = Scanner(_settings(min_comc_price=0.0))
    assert sc0._price_ok(ComcListing(raw_name="X", price=0.25, url="")) is True


def test_min_discount_default_is_20_percent():
    assert _settings().min_gross_margin == 0.20


def test_graded_allowlist_default():
    sc = Scanner(_settings())
    ok = ComcListing(raw_name="X", price=50.0, url="", graded=True, grade="PSA 10")
    bad = ComcListing(raw_name="X", price=50.0, url="", graded=True, grade="CGC 10 GEM")
    assert sc._grade_ok(ok) is True and sc._grade_ok(bad) is False


def _product(rarity):
    from comc_scanner.models import TcgProduct
    return TcgProduct(product_id=1, group_id=1, set_name="S", name="N", clean_name="n",
                      rarity=rarity)


def test_chase_filter_off_by_default_and_drops_bulk_when_on():
    assert Scanner(_settings())._chase_ok(_product("Common")) is True
    sc = Scanner(_settings(chase_only=True))
    for bulk in ("Common", "Uncommon", "Rare", "rare", "", None):
        assert sc._chase_ok(_product(bulk)) is False, bulk
    for chase in ("Illustration Rare", "Special Illustration Rare", "Ultra Rare", "Holo Rare"):
        assert sc._chase_ok(_product(chase)) is True, chase


def test_committed_slug_catalog_loads_and_is_well_formed():
    cat = Scanner(_settings())._load_slug_catalog()
    validated = {k: v for k, v in cat.items() if isinstance(v, dict) and v.get("validated")}
    assert len(validated) >= 15
    for name, info in validated.items():
        assert info.get("slug") and "year" in info and "Pokemon" in info["slug"], name
