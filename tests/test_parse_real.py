"""Tests against a REAL captured COMC browse page (offline, no network).

`tests/fixtures/comc_real_capture.html` is a genuine 100-result COMC browse page
(`/Cards/Pokemon,sh,fb,aUngraded,rCOMC,gEX-NM,i100,p1`) captured 2026-06-08. It locks
in the reverse-engineered listing DOM so a future COMC markup change fails loudly here.

The page is dominated by 1999 Topps / Bandai / Topsun products, which are NOT in the
Pokémon TCG (TCGCSV) database — so it also guards the matcher against the false-positive
class where a non-TCG set string used to resolve to a random TCG set via a short code.
"""
from pathlib import Path

from comc_scanner.comc_scraper import parse_html_file
from comc_scanner.normalize import set_contains

FIXTURE = Path(__file__).parent / "fixtures" / "comc_real_capture.html"


def _listings():
    return parse_html_file(FIXTURE)


def test_parses_full_page_of_listings():
    listings = _listings()
    assert len(listings) == 100  # the `i100` page renders exactly 100 results


def test_every_listing_has_the_fields_matching_needs():
    listings = _listings()
    # set_hint + number_hint are what the matcher keys on; without them nothing matches.
    assert all(L.set_hint for L in listings)
    assert all(L.number_hint for L in listings)
    assert all(L.condition for L in listings)
    assert all(L.price > 0 for L in listings)
    assert all(L.url.startswith("https://www.comc.com/Cards/") for L in listings)
    assert all(L.item_id and L.item_id.isdigit() for L in listings)


def test_known_first_card_extracted_exactly():
    first = _listings()[0]
    assert first.raw_name == "Gary Oak"
    assert first.number_hint == "TV8"
    assert first.condition == "EX-NM"
    assert first.price == 1.06
    assert first.quantity == 8          # "8 from" in the qty markup
    assert first.item_id == "4341265"
    assert "Topps" in first.set_hint
    assert first.graded is False        # URL path segment says "Ungraded"


def test_quantity_defaults_to_one_when_single_copy():
    # 73 of the 100 carry an "N from" multi-seller count; the rest are single copies.
    listings = _listings()
    assert any(L.quantity == 1 for L in listings)
    assert any(L.quantity > 1 for L in listings)


def test_description_carries_set_and_printing_signal():
    listings = _listings()
    assert all(L.description for L in listings)
    assert "#" in listings[0].description  # e.g. "...Series 1 - [Base]... #TV8"


# --- the matcher-side guard that real data exposed --------------------------

def test_set_contains_rejects_short_codes_inside_words():
    # The bug: 2-char TCG set codes matched inside unrelated words, so every Topps
    # listing resolved to a random TCG set ('pr' in 'printing', 'em' in 'pokemon').
    topps = "topps pokemon tv animation edition series 1 base 1st printing blue topps logo"
    assert set_contains("pr", topps) is False
    assert set_contains("em", topps) is False
    assert set_contains("ma", topps) is False


def test_set_contains_allows_real_multiword_set_names():
    assert set_contains("evolving skies", "pokemon sword shield evolving skies") is True
    assert set_contains("base set", "pokemon base set") is True


def test_set_contains_requires_whole_word():
    assert set_contains("base", "pokemon base set") is True       # standalone token
    assert set_contains("ase", "pokemon base set") is False       # mid-word, not a token
