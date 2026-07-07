"""Offline tests for the CLI layer (argument parsing + settings overrides).

Locks two conventions that live only in __main__.py and were previously untested:
- every documented subcommand parses (a renamed/removed subparser fails loudly here);
- `--min-margin` is a FRACTION (0.30 = 30%) — the CardTrader/COMC threshold
  convention, the OPPOSITE of MYP/Liga's integer percent. A future "helpful"
  conversion to percent would silently change which deals qualify.
"""
from pathlib import Path

from comc_scanner.__main__ import _apply_overrides, build_parser
from comc_scanner.config import load_settings


def _settings():
    return load_settings(env_file=Path("/nonexistent.env"))


def test_all_subcommands_parse():
    parser = build_parser()
    for argv in (
        ["run"], ["once"], ["broad"], ["targeted"], ["refresh-prices"],
        ["dry-run", "--listings", "x.json"], ["dry-run", "--html", "x.html"],
        ["capture"], ["warm"], ["parse-file", "--html", "x.html"],
        ["validate-slugs"], ["validate-slugs", "--revalidate"],
    ):
        args = parser.parse_args(argv)
        assert args.command == argv[0]


def test_min_margin_override_is_a_fraction():
    parser = build_parser()
    args = parser.parse_args(["targeted", "--min-margin", "0.30"])
    s = _settings()
    _apply_overrides(s, args)
    assert s.min_gross_margin == 0.30  # fraction, NOT 30 (MYP/Liga convention)


def test_no_override_keeps_canonical_default():
    parser = build_parser()
    args = parser.parse_args(["targeted"])
    s = _settings()
    _apply_overrides(s, args)
    assert s.min_gross_margin == 0.30


def test_headful_flag_forces_playwright_mode():
    parser = build_parser()
    args = parser.parse_args(["once", "--headful"])
    s = _settings()
    _apply_overrides(s, args)
    assert s.comc_headless is False
    assert s.comc_fetch_mode == "playwright"


def test_no_sheets_flag_disables_sheets_push():
    parser = build_parser()
    args = parser.parse_args(["once", "--no-sheets"])
    s = _settings()
    s.gsheets_credentials_json = "creds.json"
    s.gsheets_id = "sheet123"
    _apply_overrides(s, args)
    assert s.gsheets_credentials_json == ""
    assert s.gsheets_id == ""
