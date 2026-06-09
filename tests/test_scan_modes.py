"""Offline tests for the session-3 scan-mode logic (no network).

Covers the pieces that the live Firecrawl scan relies on but that are pure/unit-testable:
the set-path browse URL grammar, the NM-only condition filter, slug harvesting, and the
slug-catalog loader. These guard the headless functional path against regressions.
"""
from comc_scanner.comc_scraper import build_browse_url
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.pipeline import Scanner


def _settings(**over):
    from pathlib import Path
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


# --- set-path browse URL grammar -------------------------------------------

def test_set_path_browse_url_drops_rcomc_by_default():
    s = _settings()
    url = build_browse_url(s, era_path="1999/Pokemon_Base_Set_-_Base", page=2)
    assert url.startswith("https://www.comc.com/Cards/Pokemon/1999/Pokemon_Base_Set_-_Base,")
    assert ",rCOMC" not in url           # the vintage-killing filter is gone by default
    assert url.endswith(",i100,p2")
    assert ",aUngraded," in url and ",gEX-NM," in url


def test_seller_repo_opt_in_when_set():
    url = build_browse_url(_settings(comc_seller_repo="COMC"), era_path="1999/X")
    assert ",rCOMC," in url


def test_sort_defaults_to_highest_first_and_is_configurable():
    assert ",sh," in build_browse_url(_settings())                    # default: highest first
    assert ",sl," in build_browse_url(_settings(comc_sort="sl"))      # opt back to lowest


def test_graded_facet_flips_with_include_graded():
    assert ",aUngraded," in build_browse_url(_settings(comc_include_graded=False))
    assert ",aGraded," in build_browse_url(_settings(comc_include_graded=True))


# --- NM-only condition filter ----------------------------------------------

def _listing(cond):
    return ComcListing(raw_name="X", price=1.0, url="", condition=cond)


def test_condition_filter_keeps_nm_range_only():
    sc = Scanner(_settings())
    for ok in ("NM", "EX-NM", "Mint", "M", "near mint"):
        assert sc._condition_ok(_listing(ok)) is True, ok
    for bad in ("LP", "MP", "HP", "Noted", "Raw", "Poor", "Damaged", ""):
        assert sc._condition_ok(_listing(bad)) is False, bad


def test_condition_allowlist_is_configurable():
    sc = Scanner(_settings(comc_condition_allow=("nm",)))
    assert sc._condition_ok(_listing("NM")) is True
    assert sc._condition_ok(_listing("EX-NM")) is False  # tightened to strict NM


# --- slug harvest + catalog loader -----------------------------------------

def test_harvest_slug_extracts_year_and_slug_from_url():
    catalog = {}
    L = ComcListing(
        raw_name="Gary Oak", price=1.06, set_hint="Topps ...",
        url="https://www.comc.com/Cards/Pokemon/1999/Topps_Set_-_Base/TV8/Gary_Oak/4341265/Ungraded/COMC/EX-NM",
    )
    Scanner._harvest_slug(L, catalog)
    assert catalog["Topps ..."] == {"year": "1999", "slug": "Topps_Set_-_Base", "count": 1}
    Scanner._harvest_slug(L, catalog)  # second sighting increments count
    assert catalog["Topps ..."]["count"] == 2


def test_committed_slug_catalog_loads_and_is_well_formed():
    sc = Scanner(_settings())
    cat = sc._load_slug_catalog()
    validated = {k: v for k, v in cat.items()
                 if isinstance(v, dict) and v.get("validated")}
    assert len(validated) >= 15  # the WotC catalog the discovery pass produced
    for name, info in validated.items():
        assert info.get("year") and info.get("slug"), name
        assert "Pokemon" in info["slug"], name  # COMC WotC slugs start with Pokemon_
