"""Filtro de Pokémon icônicos (lista do operador: comc_scanner/iconic_pokemon.csv)."""
from comc_scanner.iconic import ICONIC_POKEMON, is_iconic, load_iconic, match_iconic


def test_list_loads_100_ranked_names():
    entries = load_iconic()
    assert len(entries) == 100
    assert entries[0].rank == 1 and entries[0].name == "Charizard"
    assert entries[-1].rank == 100
    assert ICONIC_POKEMON[0] == "Charizard"


def test_whole_word_match_on_card_name():
    assert match_iconic("Charizard ex").name == "Charizard"
    assert match_iconic("Dark Charizard").rank == 1
    assert match_iconic("Mega Gengar ex").name == "Gengar"
    assert match_iconic("Umbreon VMAX").name == "Umbreon"
    assert match_iconic("Ho-Oh V").name == "Ho-Oh"


def test_multiword_and_longest_wins():
    assert match_iconic("Roaring Moon ex").name == "Roaring Moon"
    assert match_iconic("Mewtwo VSTAR").name == "Mewtwo"   # não "Mew"
    assert match_iconic("Mew ex").name == "Mew"


def test_no_false_positive_inside_words():
    assert match_iconic("Charizardite X") is None
    assert match_iconic("Pidgeotto") is None
    assert match_iconic("") is None and match_iconic(None) is None
    assert is_iconic("Gary Oak") is False
