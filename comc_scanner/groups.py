"""Grupos canônicos de scan (padrão /myp-scan): o catálogo de sets validados de
``comc_scanner/comc_set_slugs.json`` dividido em 4 grupos, para o operador rodar
um grupo por vez (scan curto que termina e entrega, em vez de um scan gigante
que morre no meio).

- Grupos 1-2 = era ``recent`` (SV moderno); grupos 3-4 = era ``vintage`` (WotC).
  A era efetiva de um scan `--group N` é derivada daqui — o operador não precisa
  passar `--era` junto.
- Os nomes de set são as CHAVES VERBATIM do ``comc_set_slugs.json`` (os mesmos
  nomes TCGCSV que o modo ``targeted`` resolve). Nunca digitar nome de set "de
  cabeça" — copie do JSON.

INVARIANTE (travado por ``tests/test_groups.py``): a união dos 4 grupos é
EXATAMENTE o conjunto de sets ``validated: true`` do ``comc_set_slugs.json``,
sem sobreposição. Se o catálogo crescer (um set novo for validado), aquele teste
FALHA de propósito — é o lembrete forçado de atualizar os grupos aqui (e a skill
``.claude/skills/scan-comc``) antes de seguir.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_SLUGS_PATH = Path(__file__).resolve().parent / "comc_set_slugs.json"


@dataclass(frozen=True, slots=True)
class GroupDef:
    """One canonical scan group: a titled, era-homogeneous slice of the catalog."""

    number: int
    title: str
    description: str
    era: str  # effective --era for `targeted` ("recent" for SV, "vintage" for WotC)
    sets: tuple[str, ...]  # verbatim comc_set_slugs.json keys (= TCGCSV set names)


SCAN_GROUPS: dict[int, GroupDef] = {
    1: GroupDef(
        number=1,
        title="SV recente",
        description="Os ~7 sets Scarlet & Violet mais novos (2024-2025).",
        era="recent",
        sets=(
            "SV10: Destined Rivals",
            "SV09: Journey Together",
            "SV: Prismatic Evolutions",
            "SV08: Surging Sparks",
            "SV07: Stellar Crown",
            "SV: Shrouded Fable",
            "SV06: Twilight Masquerade",
        ),
    ),
    2: GroupDef(
        number=2,
        title="SV restante",
        description="Os demais sets Scarlet & Violet do catálogo (2023-2024).",
        era="recent",
        sets=(
            "SV05: Temporal Forces",
            "SV: Paldean Fates",
            "SV04: Paradox Rift",
            "SV03: Obsidian Flames",
            "SV02: Paldea Evolved",
            "SV: Scarlet & Violet 151",
        ),
    ),
    3: GroupDef(
        number=3,
        title="WotC 1999-2000",
        description="Vintage WotC: Base ate Neo Genesis.",
        era="vintage",
        sets=(
            "Base Set",
            "Jungle",
            "Fossil",
            "Base Set 2",
            "Team Rocket",
            "Gym Heroes",
            "Gym Challenge",
            "Neo Genesis",
        ),
    ),
    4: GroupDef(
        number=4,
        title="WotC 2001-2003",
        description="Vintage WotC: Neo Discovery ate Skyridge (e-Card).",
        era="vintage",
        sets=(
            "Neo Discovery",
            "Neo Revelation",
            "Neo Destiny",
            "Legendary Collection",
            "Expedition",
            "Aquapolis",
            "Skyridge",
        ),
    ),
}

VALID_GROUP_NUMBERS: tuple[int, ...] = tuple(sorted(SCAN_GROUPS))


def group_sets(n: int) -> list[str]:
    """Verbatim set-name allowlist for group ``n`` (KeyError on unknown group)."""
    return list(SCAN_GROUPS[n].sets)


def group_era(n: int) -> str:
    """Effective scan era for group ``n`` ("recent" or "vintage")."""
    return SCAN_GROUPS[n].era


def validated_catalog_sets(path: Path | None = None) -> set[str]:
    """Set names with ``validated: true`` in comc_set_slugs.json (the scan universe)."""
    raw = json.loads((path or _SLUGS_PATH).read_text(encoding="utf-8"))
    return {
        name
        for name, info in raw.items()
        if not name.startswith("_") and isinstance(info, dict) and info.get("validated")
    }


def describe_groups() -> str:
    """Human-readable listing of the 4 groups (used by `list-groups`; no network)."""
    lines = ["Grupos canonicos de scan (use: python -m comc_scanner targeted --group N)", ""]
    for g in SCAN_GROUPS.values():
        lines.append(
            f"Grupo {g.number} - {g.title} (era {g.era}, {len(g.sets)} sets)"
        )
        lines.append(f"  {g.description}")
        for name in g.sets:
            lines.append(f"  - {name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
