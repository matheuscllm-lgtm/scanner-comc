"""Personalized scan filters: language, condition, grade and safe references."""
from pathlib import Path
from unittest.mock import patch

import pytest

from comc_scanner.__main__ import _apply_overrides, build_parser
from comc_scanner.config import load_settings
from comc_scanner.languages import detect_language, parse_languages
from comc_scanner.models import ComcListing
from comc_scanner.pipeline import KIND_RAW, Scanner
from comc_scanner.tcg_index import TcgIndex


def _settings(**over):
    settings = load_settings(env_file=Path("/nonexistent.env"))
    for key, value in over.items():
        setattr(settings, key, value)
    return settings


def test_language_aliases_and_detection():
    assert parse_languages("English, japonês, CN, Korean") == {"en", "ja", "zh", "ko"}
    assert detect_language("Pokemon 151 - Japanese") == "ja"
    assert detect_language("Traditional Chinese") == "zh"
    assert detect_language("Scarlet & Violet Base") == "en"
    with pytest.raises(ValueError):
        parse_languages("klingon")


def test_cli_applies_personalized_filters():
    args = build_parser().parse_args([
        "scan", "--sets", "SV: Scarlet & Violet 151", "--languages", "ja,zh",
        "--conditions", "NM,LP", "--grades", "PSA 10,TAG 10",
    ])
    settings = _settings()
    _apply_overrides(settings, args)
    assert settings.set_allowlist == ("SV: Scarlet & Violet 151",)
    assert settings.languages == {"ja", "zh"}
    assert settings.raw_conditions == {"nm", "lp"}
    assert settings.graded_allow == {"PSA 10", "TAG 10"}


def test_default_remains_english_and_existing_policy():
    settings = _settings()
    assert settings.languages == {"en"}
    assert settings.raw_conditions == {"nm", "lp", "ex-nm"}


def test_selected_language_filter_is_explicit():
    jp = ComcListing("Pikachu", 20, "https://comc/jp", set_hint="151 - Japanese")
    en = ComcListing("Pikachu", 20, "https://comc/en", set_hint="151")
    scanner = Scanner(_settings(languages=frozenset({"ja"})))
    assert scanner._variant_ok(jp) is True and jp.language == "ja"
    assert scanner._variant_ok(en) is False and en.language == "en"


def test_non_english_never_calls_english_match_or_price_source(tmp_path):
    listing = ComcListing(
        "Pikachu", 20, "https://comc/jp", set_hint="Pokemon 151 - Japanese",
        condition="NM",
    )
    scanner = Scanner(_settings(languages=frozenset({"ja"}), results_dir=tmp_path))
    with patch("comc_scanner.pipeline.match", side_effect=AssertionError("no cross-language ref")):
        assert scanner.process_listing(listing, TcgIndex(), None, KIND_RAW) is None
    assert scanner.stats["foreign_discovery"] == 1
    row = scanner.reporter.unpriced[listing.url]
    assert row["language"] == "ja" and "mesmo idioma" in row["unpriced_reason"]


def test_unselected_condition_is_rejected_before_reference():
    listing = ComcListing("Pikachu", 20, "https://comc/lp", condition="LP")
    scanner = Scanner(_settings(raw_conditions=frozenset({"nm"})))
    assert scanner.process_listing(listing, TcgIndex(), None, KIND_RAW) is None
    assert scanner.stats["skip_condition"] == 1
