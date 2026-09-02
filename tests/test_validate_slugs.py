"""`validate-slugs` (operador 2026-09-02): um slug só é validado se a página 1 for do
PRÓPRIO set — slug errado/acentuado cai numa categoria-pai da COMC (ano inteiro) e
mistura sets (Neo Revelation antigo; `Pokémon_EX_Hidden_Legends_-_Base`)."""
import json
from pathlib import Path

from comc_scanner import pipeline as pl
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing


def _L(name, hint):
    return ComcListing(raw_name=name, price=10.0, url="https://www.comc.com/x", set_hint=hint,
                       condition="NM", item_id=name)


PAGES = {
    "2004/Pokemon_EX_Hidden_Legends_-_Base": [_L("Groudon", "Pokémon EX Hidden Legends - Base")] * 7
    + [_L("Kyogre", "Pokémon EX Hidden Legends - Base - Reverse Foil")] * 3,
    "2004/Pokémon_EX_Deoxys_-_Base": [_L("Rayquaza", "Pokémon - EX Team Rocket Returns - Base")] * 8
    + [_L("Deoxys", "Pokémon EX Deoxys - Base")] * 2,
    "2005/Pokemon_EX_Emerald_-_Base": [],
}


class FakeScraper:
    def __init__(self, settings):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_listings(self, search_term=None, era_path=None, max_pages=0, graded=False):
        yield 1, PAGES.get(era_path, [])


def test_validate_slugs_requires_page1_to_belong_to_the_set(tmp_path, monkeypatch):
    cat = tmp_path / "slugs.json"
    cat.write_text(json.dumps({
        "_meta": {"x": 1},
        "EX Hidden Legends": {"year": "2004", "slug": "Pokemon_EX_Hidden_Legends_-_Base", "validated": False},
        "EX Deoxys": {"year": "2004", "slug": "Pokémon_EX_Deoxys_-_Base", "validated": False},
        "EX Emerald": {"year": "2005", "slug": "Pokemon_EX_Emerald_-_Base", "validated": False},
    }), encoding="utf-8")
    monkeypatch.setattr(pl, "ComcScraper", FakeScraper)
    s = load_settings(env_file=Path("/nonexistent.env"))
    res = pl.Scanner(s).validate_slugs(catalog_path=cat)
    out = json.loads(cat.read_text(encoding="utf-8"))
    assert res["EX Hidden Legends"] == 10 and out["EX Hidden Legends"]["validated"] is True
    assert out["EX Hidden Legends"]["page1_own_share"] == 1.0  # subsets do próprio set contam
    # categoria-pai: 80% das listagens são de OUTRO set → NÃO valida (share gravado)
    assert res["EX Deoxys"] == 10 and out["EX Deoxys"]["validated"] is False
    assert out["EX Deoxys"]["page1_own_share"] == 0.2
    assert res["EX Emerald"] == 0 and out["EX Emerald"]["validated"] is False
    assert out["_meta"] == {"x": 1}


def test_set_key_generic_names_require_exact_core_match():
    """Nomes só com palavras genéricas/de série ("Base Set", "XY Base Set", "SM Base Set")
    não podem virar chave frouxa ({base} casa QUALQUER slug "…_-_Base"): nesses casos o
    núcleo do hint (sem base/set) tem de ser IGUAL ao da chave (review PR B)."""
    S = pl.Scanner
    assert S._set_key("XY - Flashfire") == ({"flashfire"}, False)
    assert S._set_key("XY Base Set") == ({"xy"}, True)
    assert S._set_key("SM Base Set") == ({"sun", "moon"}, True)
    assert S._set_key("Base Set") == (frozenset(), True)
    assert S._set_key("Base Set 2") == ({"2"}, True)
    assert S._set_key("SWSH09: Brilliant Stars Trainer Gallery") == ({"brilliant", "stars", "trainer", "gallery"}, False)
    # página misturada (categoria-pai): Jungle/Fossil têm "- Base" no hint mas NÃO são Base Set
    mixed = [_L("Scyther", "Pokemon Jungle - Base")] * 4 + [_L("Lapras", "Pokemon Fossil - Base")] * 4         + [_L("Charizard", "Pokemon Base Set - Base")] * 2
    assert S.own_set_share("Base Set", mixed) == 0.2
    assert S.own_set_share("Base Set 2", [_L("Charizard", "Pokemon Base Set 2 - Base")]) == 1.0
    assert S.own_set_share("Base Set 2", [_L("Charizard", "Pokemon Base Set - Base")]) == 0.0
    assert S.own_set_share("XY Base Set", [_L("Xerneas", "Pokémon XY - Base")]) == 1.0
    assert S.own_set_share("XY Base Set", [_L("Charizard", "Pokémon XY - Flashfire - Base")]) == 0.0
    assert S.own_set_share("SM Base Set", [_L("Umbreon", "Pokémon Sun  Moon - Base - Base")]) == 1.0
    assert S.own_set_share("SM Base Set", [_L("Zoroark", "Pokémon Sun  Moon - Team Up - Base")]) == 0.0
    assert S.own_set_share("SWSH01: Sword & Shield Base Set", [_L("Zacian", "Pokémon Sword  Shield - Base")]) == 1.0
    assert S.own_set_share("Hidden Fates", [_L("Charizard", "Pokémon Sun  Moon - Hidden Fates - Base - Reverse Foil")]) == 1.0
