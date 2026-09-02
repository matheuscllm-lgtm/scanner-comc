"""Era segmentation (recent / middle / vintage).

Eras are derived from each set's `publishedOn` year (data-driven), so the buckets
stay correct as new sets release.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings
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
    """Allowlist por IGUALDADE normalizada (nome, alias ou abreviação) — nunca
    substring: "Base Set" casa "Base Set", não "Base Set 2" nem "SV01: Scarlet &
    Violet Base Set" (vazamento real que a busca textual ampla produzia)."""
    aliases = {a for a in set_aliases(s.name) | {normalize_set(s.abbreviation)} if a}
    return any(normalize_set(entry) in aliases for entry in allowlist if normalize_set(entry))


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
