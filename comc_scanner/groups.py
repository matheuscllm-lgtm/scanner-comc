"""Grupos canônicos de scan (padrão /myp-scan): o catálogo de sets validados de
``comc_scanner/comc_set_slugs.json`` dividido em 12 grupos, para o operador rodar
um grupo por vez (scan curto que termina e entrega, em vez de um scan gigante
que morre no meio).

- Grupos 1-2 = era ``recent`` (SV moderno); grupos 3-4 = era ``vintage`` (WotC ≤2003);
  grupos 5-10 = era ``middle`` (EX, DP, Platinum, HGSS, BW, XY, SM: 2004-2019);
  grupos 11-12 = era ``recent`` (SWSH 2020-2023).
  A era efetiva de um scan `--group N` é derivada daqui — o operador não precisa
  passar `--era` junto.
- Os nomes de set são as CHAVES VERBATIM do ``comc_set_slugs.json`` (os mesmos
  nomes TCGCSV que o ``scan`` resolve). Nunca digitar nome de set "de
  cabeça" — copie do JSON.

INVARIANTE (travado por ``tests/test_groups.py``): a união dos 12 grupos é
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
    era: str  # effective --era for `scan` ("recent" for SV, "vintage" for WotC)
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
    5: GroupDef(
        number=5,
        title="EX 2004-2005",
        description="Era EX (2004-2005): Team Magma vs Team Aqua ate Delta Species.",
        era="middle",
        sets=(
            "EX Team Magma vs Team Aqua",
            "EX Hidden Legends",
            "EX FireRed & LeafGreen",
            "EX Team Rocket Returns",
            "EX Deoxys",
            "EX Emerald",
            "EX Unseen Forces",
            "EX Delta Species",
        ),
    ),
    6: GroupDef(
        number=6,
        title="EX 2006-2007 + DP 2007",
        description="Era EX (2006-2007) + inicio de Diamond & Pearl (2007).",
        era="middle",
        sets=(
            "EX Legend Maker",
            "EX Holon Phantoms",
            "EX Crystal Guardians",
            "EX Dragon Frontiers",
            "EX Power Keepers",
            "Diamond and Pearl",
            "Mysterious Treasures",
            "Secret Wonders",
        ),
    ),
    7: GroupDef(
        number=7,
        title="DP/Platinum 2008-2010",
        description="Diamond & Pearl (2008) e Platinum (2009-2010).",
        era="middle",
        sets=(
            "Great Encounters",
            "Majestic Dawn",
            "Legends Awakened",
            "Stormfront",
            "Platinum",
            "Rising Rivals",
            "Supreme Victors",
            "Arceus",
        ),
    ),
    8: GroupDef(
        number=8,
        title="HGSS + BW 2010-2013",
        description="HeartGold SoulSilver, Call of Legends e Black & White (2010-2013).",
        era="middle",
        sets=(
            "HeartGold SoulSilver",
            "Unleashed",
            "Undaunted",
            "Triumphant",
            "Call of Legends",
            "Black and White",
            "Emerging Powers",
            "Noble Victories",
            "Next Destinies",
            "Dark Explorers",
            "Dragons Exalted",
            "Boundaries Crossed",
            "Plasma Storm",
            "Plasma Freeze",
            "Plasma Blast",
            "Legendary Treasures",
            "Legendary Treasures: Radiant Collection",
        ),
    ),
    9: GroupDef(
        number=9,
        title="XY 2014-2016",
        description="XY (2014-2016), incluindo Generations e Evolutions.",
        era="middle",
        sets=(
            "XY Base Set",
            "XY - Flashfire",
            "XY - Furious Fists",
            "XY - Phantom Forces",
            "XY - Primal Clash",
            "XY - Roaring Skies",
            "XY - Ancient Origins",
            "XY - BREAKthrough",
            "XY - BREAKpoint",
            "Generations",
            "XY - Fates Collide",
            "XY - Steam Siege",
            "XY - Evolutions",
            "Generations: Radiant Collection",
        ),
    ),
    10: GroupDef(
        number=10,
        title="SM 2017-2019",
        description="Sun & Moon (2017-2019), incluindo Shining Legends, Dragon Majesty, Detective Pikachu e Hidden Fates.",
        era="middle",
        sets=(
            "SM Base Set",
            "SM - Guardians Rising",
            "SM - Burning Shadows",
            "Shining Legends",
            "SM - Crimson Invasion",
            "SM - Ultra Prism",
            "SM - Forbidden Light",
            "SM - Celestial Storm",
            "Dragon Majesty",
            "SM - Lost Thunder",
            "SM - Team Up",
            "Detective Pikachu",
            "SM - Unbroken Bonds",
            "SM - Unified Minds",
            "Hidden Fates",
            "SM - Cosmic Eclipse",
            "Hidden Fates: Shiny Vault",
        ),
    ),
    11: GroupDef(
        number=11,
        title="SWSH 2020-2021",
        description="Sword & Shield 2020-2021, incluindo Shining Fates e Celebrations.",
        era="recent",
        sets=(
            "SWSH01: Sword & Shield Base Set",
            "SWSH02: Rebel Clash",
            "SWSH03: Darkness Ablaze",
            "SWSH04: Vivid Voltage",
            "Shining Fates",
            "SWSH05: Battle Styles",
            "SWSH06: Chilling Reign",
            "SWSH07: Evolving Skies",
            "Celebrations",
            "SWSH08: Fusion Strike",
            "Shining Fates: Shiny Vault",
            "Celebrations: Classic Collection",
        ),
    ),
    12: GroupDef(
        number=12,
        title="SWSH 2022 + Crown Zenith",
        description="Sword & Shield 2022 + Pokemon GO + Crown Zenith (jan/2023).",
        era="recent",
        sets=(
            "SWSH09: Brilliant Stars",
            "SWSH10: Astral Radiance",
            "Pokemon GO",
            "SWSH11: Lost Origin",
            "SWSH12: Silver Tempest",
            "SWSH: Crown Zenith",
            "SWSH09: Brilliant Stars Trainer Gallery",
            "SWSH10: Astral Radiance Trainer Gallery",
            "SWSH11: Lost Origin Trainer Gallery",
            "SWSH12: Silver Tempest Trainer Gallery",
            "SWSH: Crown Zenith: Galarian Gallery",
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
    """Human-readable listing of the groups (used by `list-groups`; no network)."""
    lines = ["Grupos canonicos de scan (use: python -m comc_scanner scan --group N)", ""]
    for g in SCAN_GROUPS.values():
        lines.append(
            f"Grupo {g.number} - {g.title} (era {g.era}, {len(g.sets)} sets)"
        )
        lines.append(f"  {g.description}")
        for name in g.sets:
            lines.append(f"  - {name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
