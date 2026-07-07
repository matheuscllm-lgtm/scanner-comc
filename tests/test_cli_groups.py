"""Offline tests for the --group CLI flag and the list-groups subcommand."""
import argparse

import pytest

from comc_scanner.__main__ import _apply_overrides, _resolve_era, build_parser, main
from comc_scanner.groups import group_sets


def _settings():
    from pathlib import Path

    from comc_scanner.config import load_settings
    return load_settings(env_file=Path("/nonexistent.env"))


def test_group_flag_becomes_the_exact_allowlist():
    args = build_parser().parse_args(["targeted", "--group", "3"])
    s = _settings()
    _apply_overrides(s, args)
    assert s.set_allowlist == tuple(group_sets(3))
    assert "Base Set" in s.set_allowlist and "Neo Genesis" in s.set_allowlist


def test_group_and_sets_are_mutually_exclusive():
    with pytest.raises(SystemExit):  # argparse error (exit code 2)
        build_parser().parse_args(["targeted", "--group", "1", "--sets", "Base Set"])


def test_group_must_be_one_of_the_four():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["targeted", "--group", "9"])


def test_group_derives_era_without_explicit_era():
    s = _settings()
    args = build_parser().parse_args(["targeted", "--group", "1"])
    assert _resolve_era(args, s) == "recent"
    args = build_parser().parse_args(["targeted", "--group", "4"])
    assert _resolve_era(args, s) == "vintage"


def test_conflicting_era_warns_and_group_wins(caplog):
    s = _settings()
    args = build_parser().parse_args(["targeted", "--group", "3", "--era", "recent"])
    with caplog.at_level("WARNING", logger="comc_scanner.cli"):
        era = _resolve_era(args, s)
    assert era == "vintage"  # the group wins
    assert any("conflita" in rec.getMessage() for rec in caplog.records)


def test_without_group_era_behaviour_is_unchanged():
    s = _settings()
    args = build_parser().parse_args(["targeted", "--era", "vintage"])
    assert _resolve_era(args, s) == "vintage"
    args = build_parser().parse_args(["targeted"])
    assert _resolve_era(args, s) == s.default_era


def test_list_groups_prints_groups_and_exits_zero(capsys):
    rc = main(["list-groups"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Grupo 1" in out and "Grupo 4" in out
    assert "SV10: Destined Rivals" in out
    assert "Skyridge" in out


def test_group_flag_available_on_targeted_help():
    parser = build_parser()
    # argparse stores subparsers in _subparsers; simplest robust check: parsing
    # `targeted --group 2` works and yields the group attribute.
    args = parser.parse_args(["targeted", "--group", "2"])
    assert isinstance(args, argparse.Namespace) and args.group == 2
