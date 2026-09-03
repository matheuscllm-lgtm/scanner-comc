"""Parse de páginas REAIS de slabs da COMC (capturadas 2026-09-02, `aGraded`)."""
from collections import Counter
from pathlib import Path

from comc_scanner.comc_scraper import build_browse_url, parse_html_file
from comc_scanner.config import Settings

FIX = Path(__file__).parent / "fixtures"


def test_graded_151_page_parses_all_listings_with_grades():
    L = parse_html_file(FIX / "comc_graded_151_capture.html")
    assert len(L) == 77 and all(x.graded for x in L)
    keys = Counter(x.grade for x in L)
    assert keys["CGC 10 PRISTINE"] == 23 and keys["CGC 10 GEM"] == 20
    assert keys["PSA 10"] == 9 and keys["PSA 9"] == 3 and keys["BGS 9.5"] == 3
    assert all(x.grader for x in L) and all(x.grade_label for x in L)


def test_graded_base_set_page_has_vintage_psa_slabs():
    L = parse_html_file(FIX / "comc_graded_base_capture.html")
    assert len(L) == 58 and all(x.graded for x in L)
    pidgeotto = next(x for x in L if x.raw_name == "Pidgeotto")
    assert pidgeotto.grade == "PSA 9" and pidgeotto.grade_label == "PSA 9 MINT"
    assert pidgeotto.price == 121.09 and pidgeotto.item_id == "4340358"
    assert pidgeotto.url.endswith("/Graded/PSA/9")


def test_ungraded_capture_has_no_grades():
    L = parse_html_file(FIX / "comc_real_capture.html")
    assert all(not x.graded and x.grade is None for x in L)


def test_browse_url_graded_facet_and_no_band():
    s = Settings()
    raw = build_browse_url(s, era_path="1999/Pokemon_Base_Set_-_Base")
    slab = build_browse_url(s, era_path="1999/Pokemon_Base_Set_-_Base", graded=True)
    assert ",aUngraded," in raw and ",gEX-NM," in raw
    assert ",aGraded," in slab and ",gEX-NM," not in slab


def test_graded_base_set_page_slabs_against_new_allowlist():
    """Allowlist 2026-09-02: PSA 8 e CGC 9 (presentes na captura Base) entram; PSA 7,
    SGC 8.5 e MNT 8.5 continuam fora. A allowlist NÃO filtra o parse — só o pipeline."""
    from comc_scanner.grading import DEFAULT_GRADED_ALLOW

    keys = Counter(x.grade for x in parse_html_file(FIX / "comc_graded_base_capture.html"))
    assert keys["PSA 8"] >= 1 and keys["CGC 9"] >= 1 and keys["PSA 9"] >= 1
    assert {"PSA 8", "CGC 9", "PSA 9"} <= DEFAULT_GRADED_ALLOW
    assert keys["PSA 7"] >= 1 and keys["SGC 8.5"] >= 1 and keys["MNT 8.5"] >= 1
    assert not {"PSA 7", "SGC 8.5", "MNT 8.5"} & DEFAULT_GRADED_ALLOW


def test_ebay_auction_tile_never_contaminates_the_next_listing():
    """Captura real 2026-09-02 (Evolving Skies, slabs): um tile de LEILÃO eBay promovido
    (Umbreon V, "3d left", link /Promotions/eBay_Auction/…, US$15,50) não tem link /Cards/;
    o parser roubava o link-imagem do tile seguinte (Sylveon VMAX PSA 10, US$341,10) e
    entregava o Sylveon a US$15,50 (falso positivo de 83% no diagnóstico)."""
    from comc_scanner.comc_scraper import _parse_dom
    html = (FIX / "comc_graded_evs_auction_capture.html").read_text(encoding="utf-8")
    listings = _parse_dom(html)
    sylveon = [L for L in listings if "Sylveon_VMAX/17626375" in L.url and L.grade == "PSA 10"]
    assert len(sylveon) == 1 and sylveon[0].price == 341.10
    assert not any(L.price == 15.50 for L in listings)  # o leilão não vira listagem
    assert all("/Cards/Pokemon/" in L.url for L in listings)
