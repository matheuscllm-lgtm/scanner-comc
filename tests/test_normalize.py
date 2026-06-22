"""Offline tests for normalization helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comc_scanner.normalize import (  # noqa: E402
    detect_graded, normalize_name, normalize_set, parse_number, parse_set_total,
    set_aliases, subtype_hint,
)


def test_parse_number():
    assert parse_number("021/128") == "21"
    assert parse_number("21/128") == "21"
    assert parse_number("4/102") == "4"


def test_parse_set_total():
    # denominator side, normalized the same way across sources
    assert parse_set_total("001/217") == "217"
    assert parse_set_total("4/102") == "102"
    assert parse_set_total("021/128") == "128"
    assert parse_set_total("TG12/TG30") == "tg30"
    # no denominator -> no signal
    assert parse_set_total("19") is None
    assert parse_set_total("SV107") is None
    assert parse_set_total("") is None
    assert parse_set_total(None) is None
    assert parse_number("TG12/TG30") == "tg12"
    assert parse_number("SV107") == "sv107"
    assert parse_number("SWSH250") == "swsh250"
    assert parse_number("") is None
    assert parse_number(None) is None


def test_normalize_set_strips_code_prefix():
    assert normalize_set("SWSH07: Evolving Skies") == "evolving skies"
    assert normalize_set("SV01: Scarlet & Violet Base Set") == "scarlet and violet base set"
    assert normalize_set("Base Set") == "base set"


def test_set_aliases_include_code():
    aliases = set_aliases("SWSH07: Evolving Skies")
    assert "evolving skies" in aliases
    assert "swsh07" in aliases


def test_normalize_name_drops_foil_words():
    assert "holo" not in normalize_name("Charizard Reverse Holofoil")
    assert "charizard" in normalize_name("Charizard ex")  # keep suffix tokens


def test_subtype_hint():
    assert subtype_hint("Charizard", "", None) == "Normal"
    assert subtype_hint("Charizard Holo", "", None) == "Holofoil"
    assert subtype_hint("Pikachu", "1st Edition", None) == "1st Edition"
    assert subtype_hint("Pikachu Holo", "1st Edition", None) == "1st Edition Holofoil"
    assert subtype_hint("Pikachu", "Unlimited", None) == "Unlimited"
    assert subtype_hint("Charizard Reverse Holo", "", None) == "Reverse Holofoil"


def test_detect_graded():
    assert detect_graded("PSA 9") == (True, "PSA")
    assert detect_graded("BGS 9.5")[0] is True
    assert detect_graded("EX-NM") == (False, None)
