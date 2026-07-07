"""Offline tests for the canonical scan groups (comc_scanner/groups.py).

The load-bearing test here is the catalog-coverage invariant: the union of the
4 groups must be EXACTLY the `validated: true` set of comc_set_slugs.json, with
no overlap. If the catalog grows (a new set gets validated), that test FAILS on
purpose — forcing whoever added the set to place it in a group (and update the
scan-comc skill) instead of silently leaving it out of every scan.
"""
import pytest

from comc_scanner.groups import (
    SCAN_GROUPS,
    VALID_GROUP_NUMBERS,
    describe_groups,
    group_era,
    group_sets,
    validated_catalog_sets,
)


def test_groups_cover_validated_catalog_exactly_no_overlap():
    catalog = validated_catalog_sets()
    union: list[str] = []
    for n in VALID_GROUP_NUMBERS:
        union.extend(group_sets(n))
    # no overlap between groups
    assert len(union) == len(set(union)), "set repetido em mais de um grupo"
    # exact coverage of the validated catalog (fails when the catalog grows —
    # that is intentional: update SCAN_GROUPS + the scan-comc skill)
    assert set(union) == catalog


def test_there_are_exactly_four_groups():
    assert VALID_GROUP_NUMBERS == (1, 2, 3, 4)
    assert set(SCAN_GROUPS) == {1, 2, 3, 4}


def test_group_sets_returns_verbatim_names():
    g1 = group_sets(1)
    assert "SV10: Destined Rivals" in g1
    assert "SV06: Twilight Masquerade" in g1
    assert len(g1) == 7
    g3 = group_sets(3)
    assert g3 == ["Base Set", "Jungle", "Fossil", "Base Set 2", "Team Rocket",
                  "Gym Heroes", "Gym Challenge", "Neo Genesis"]


def test_group_sets_unknown_group_raises():
    with pytest.raises(KeyError):
        group_sets(5)


def test_era_derived_from_group():
    # SV groups scan era=recent; WotC groups scan era=vintage — the CLI derives
    # this automatically (no --era needed alongside --group).
    assert group_era(1) == "recent"
    assert group_era(2) == "recent"
    assert group_era(3) == "vintage"
    assert group_era(4) == "vintage"


def test_describe_groups_lists_every_set_and_needs_no_network():
    out = describe_groups()
    for n in VALID_GROUP_NUMBERS:
        assert f"Grupo {n}" in out
        for name in group_sets(n):
            assert name in out
