"""Era segmentation (recent / middle / vintage) and resumable chunking.

Eras are derived from each set's `publishedOn` year (data-driven), so the buckets
stay correct as new sets release. The era also serves as the chunk unit: a run can
process a bounded number of sets and persist a cursor to resume next time.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import PROGRESS_DIR, Settings
from .normalize import normalize_set, set_aliases


@dataclass(slots=True)
class TcgSet:
    group_id: int
    name: str
    abbreviation: str
    year: int | None
    era: str


def _parse_year(published_on: str | None) -> int | None:
    if not published_on:
        return None
    m = re.search(r"(\d{4})", str(published_on))
    return int(m.group(1)) if m else None


def assign_era(year: int | None, settings: Settings) -> str:
    if year is None:
        return "unknown"
    if year <= settings.era_vintage_max_year:
        return "vintage"
    if year <= settings.era_middle_max_year:
        return "middle"
    return "recent"


def to_sets(groups: list[dict], settings: Settings) -> list[TcgSet]:
    out: list[TcgSet] = []
    for g in groups:
        year = _parse_year(g.get("publishedOn"))
        out.append(
            TcgSet(
                group_id=int(g["groupId"]),
                name=g.get("name", ""),
                abbreviation=g.get("abbreviation", "") or "",
                year=year,
                era=assign_era(year, settings),
            )
        )
    return out


def bucket_sets_by_era(
    groups: list[dict], settings: Settings
) -> dict[str, list[TcgSet]]:
    buckets: dict[str, list[TcgSet]] = {"recent": [], "middle": [], "vintage": [], "unknown": []}
    for s in to_sets(groups, settings):
        buckets.setdefault(s.era, []).append(s)
    return buckets


def _matches_allowlist(s: TcgSet, allowlist: tuple[str, ...]) -> bool:
    if not allowlist:
        return True
    aliases = set_aliases(s.name) | {normalize_set(s.abbreviation)}
    for entry in allowlist:
        key = normalize_set(entry)
        if not key:
            continue
        if key in aliases or any(key in a or a in key for a in aliases if a):
            return True
    return False


def select_sets(groups: list[dict], settings: Settings, era: str) -> list[TcgSet]:
    """Ordered (newest first) sets for the requested era, filtered by the allowlist."""
    era = (era or "all").lower()
    sets = to_sets(groups, settings)
    if era != "all":
        sets = [s for s in sets if s.era == era]
    sets = [s for s in sets if _matches_allowlist(s, settings.set_allowlist)]
    # newest first; unknown years sort last
    sets.sort(key=lambda s: (s.year if s.year is not None else -1, s.name), reverse=True)
    return sets


@dataclass
class ChunkCursor:
    """Persisted scan progress for one era, so runs resume where they left off."""
    era: str
    snapshot_date: str
    next_set_index: int = 0
    page: int = 1
    updated: float = 0.0

    @staticmethod
    def _path(era: str) -> Path:
        PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        return PROGRESS_DIR / f"{era}.json"

    @classmethod
    def load(cls, era: str, snapshot_date: str) -> "ChunkCursor":
        path = cls._path(era)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("snapshot_date") == snapshot_date:
                    return cls(**data)
            except Exception:
                pass
        return cls(era=era, snapshot_date=snapshot_date)

    def save(self) -> None:
        self.updated = time.time()
        self._path(self.era).write_text(json.dumps(asdict(self)), encoding="utf-8")

    def clear(self) -> None:
        path = self._path(self.era)
        if path.exists():
            path.unlink()
