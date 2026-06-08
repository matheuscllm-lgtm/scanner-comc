"""Offline tests for era bucketing, set selection, and the chunk cursor."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comc_scanner.config import Settings  # noqa: E402
from comc_scanner.segments import (  # noqa: E402
    ChunkCursor, assign_era, bucket_sets_by_era, select_sets,
)

GROUPS = [
    {"groupId": 604, "name": "Base Set", "abbreviation": "BS", "publishedOn": "1999-01-09T00:00:00"},
    {"groupId": 1, "name": "Black & White", "abbreviation": "BLW", "publishedOn": "2011-04-25T00:00:00"},
    {"groupId": 2, "name": "SWSH07: Evolving Skies", "abbreviation": "SWSH07", "publishedOn": "2021-08-27T00:00:00"},
    {"groupId": 3, "name": "SV09: Journey Together", "abbreviation": "SV09", "publishedOn": "2025-03-28T00:00:00"},
    {"groupId": 4, "name": "Mystery Set", "abbreviation": "MS", "publishedOn": None},
]


def test_assign_era():
    s = Settings()
    assert assign_era(1999, s) == "vintage"
    assert assign_era(2011, s) == "middle"
    assert assign_era(2021, s) == "recent"
    assert assign_era(None, s) == "unknown"


def test_bucket_counts():
    buckets = bucket_sets_by_era(GROUPS, Settings())
    assert len(buckets["vintage"]) == 1
    assert len(buckets["middle"]) == 1
    assert len(buckets["recent"]) == 2
    assert len(buckets["unknown"]) == 1


def test_select_recent_ordered_newest_first():
    sets = select_sets(GROUPS, Settings(), "recent")
    assert [x.name for x in sets] == ["SV09: Journey Together", "SWSH07: Evolving Skies"]


def test_select_with_allowlist():
    s = Settings(set_allowlist=("evolving skies",))
    sets = select_sets(GROUPS, s, "all")
    assert len(sets) == 1 and sets[0].group_id == 2


def test_chunk_cursor_roundtrip():
    c = ChunkCursor(era="testera", snapshot_date="2099-01-01", next_set_index=3, page=2)
    c.save()
    try:
        loaded = ChunkCursor.load("testera", "2099-01-01")
        assert loaded.next_set_index == 3 and loaded.page == 2
        # different snapshot date -> fresh cursor
        fresh = ChunkCursor.load("testera", "2099-02-02")
        assert fresh.next_set_index == 0
    finally:
        c.clear()
