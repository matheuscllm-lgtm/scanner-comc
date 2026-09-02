"""Offline tests for --group and list-groups."""
import pytest

from comc_scanner.__main__ import _resolve_era, build_parser, main
from comc_scanner.groups import group_sets


def _settings():
    from pathlib import Path

    from comc_scanner.config import load_settings
    return load_settings(env_file=Path("/nonexistent.env"))


def test_group_and_sets_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["scan", "--group", "1", "--sets", "Base Set"])


def test_group_sets_are_exact_catalog_names():
    assert "Base Set" in group_sets(3) and "Neo Genesis" in group_sets(3)


def test_group_derives_era_without_explicit_era():
    s = _settings()
    args = build_parser().parse_args(["scan", "--group", "1"])
    assert _resolve_era(args, s, 1) == "recent"
    assert _resolve_era(args, s, 4) == "vintage"


def test_conflicting_era_warns_and_group_wins(caplog):
    s = _settings()
    args = build_parser().parse_args(["scan", "--group", "3", "--era", "recent"])
    with caplog.at_level("WARNING", logger="comc_scanner.cli"):
        era = _resolve_era(args, s, 3)
    assert era == "vintage"
    assert any("conflita" in rec.getMessage() for rec in caplog.records)


def test_without_group_era_behaviour_is_unchanged():
    s = _settings()
    assert _resolve_era(build_parser().parse_args(["scan", "--era", "vintage"]), s) == "vintage"
    assert _resolve_era(build_parser().parse_args(["scan"]), s) == s.default_era


def test_list_groups_prints_groups_and_exits_zero(capsys):
    assert main(["list-groups"]) == 0
    out = capsys.readouterr().out
    assert "Grupo 1" in out and "Grupo 4" in out
    assert "SV10: Destined Rivals" in out and "Skyridge" in out


def test_invalid_group_is_an_argparse_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--group", "99"])
    assert exc.value.code == 2
