"""CLI (offline): subcomandos, `--min-discount` INTEIRO (20 = 20%), escopo raw/slabs."""
import argparse
from pathlib import Path

import pytest

from comc_scanner.__main__ import _apply_overrides, _parse_group, build_parser
from comc_scanner.config import load_settings


def _settings():
    return load_settings(env_file=Path("/nonexistent.env"))


def test_all_subcommands_parse():
    parser = build_parser()
    for argv in (["scan"], ["scan", "--group", "1"], ["scan", "--group", "all"],
                 ["list-groups"], ["validate-slugs"], ["validate-slugs", "--revalidate"],
                 ["warm"], ["capture"]):
        assert parser.parse_args(argv).command == argv[0]


def test_removed_subcommands_fail_loudly():
    for old in ("targeted", "run", "once", "broad", "dry-run", "refresh-prices", "parse-file"):
        with pytest.raises(SystemExit):
            build_parser().parse_args([old])


def test_min_discount_is_an_integer_percent():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan", "--min-discount", "25"]))
    assert s.min_discount_percent == 25 and s.min_gross_margin == 0.25


def test_default_discount_is_20_percent():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan"]))
    assert s.min_discount_percent == 20 and s.min_gross_margin == 0.20


def test_scope_flags():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan", "--raw-only", "--all-pokemon"]))
    assert s.scan_raw and not s.scan_slabs and not s.iconic_only
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan", "--slabs-only"]))
    assert s.scan_slabs and not s.scan_raw and not s.iconic_only
    with pytest.raises(SystemExit):
        build_parser().parse_args(["scan", "--raw-only", "--slabs-only"])


def test_legacy_flags_accepted_and_headful_forced():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan", "--group", "1", "--headful", "--restart"]))
    assert s.comc_headless is False


def test_parse_group_values():
    assert _parse_group(None) is None
    assert _parse_group("3") == [3]
    assert _parse_group("all") == list(range(1, 13))
    for bad in ("99", "x", "0"):
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_group(bad)


def test_budget_and_english_cap_flags():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["scan", "--max-price", "250", "--max-english", "300"]))
    assert s.max_comc_price == 250.0 and s.max_english_per_set == 300
    assert _settings().max_comc_price == 0.0 and _settings().max_english_per_set == 0
