"""Lista icônica + matcher (comc_scanner/notorious.py) — filtro de escopo do --iconic."""
from comc_scanner.notorious import (
    NOTORIOUS_POKEMON, iconic_name_for_product, is_notorious, match_notorious,
)


def test_list_has_the_fleet_icons():
    for name in ("Charizard", "Pikachu", "Umbreon", "Mewtwo", "Lugia", "Rayquaza"):
        assert name in NOTORIOUS_POKEMON
    assert len(NOTORIOUS_POKEMON) == len(set(NOTORIOUS_POKEMON))  # sem duplicata


def test_whole_word_match_on_tcgcsv_product_names():
    assert match_notorious("Charizard ex - 199/165") == "Charizard"
    assert match_notorious("Dark Charizard") == "Charizard"
    assert match_notorious("Mega Charizard EX") == "Charizard"
    assert match_notorious("charizard") == "Charizard"  # case-insensitive


def test_item_named_after_pokemon_does_not_match():
    assert match_notorious("Charizardite X") is None  # a palavra é "Charizardite"
    assert match_notorious("Pikachunk") is None


def test_mew_vs_mewtwo():
    assert match_notorious("Mewtwo VSTAR") == "Mewtwo"  # match mais longo vence
    assert match_notorious("Mew ex - 151/165") == "Mew"
    assert match_notorious("Mewtwo") != "Mew"


def test_non_iconic_and_empty():
    assert match_notorious("Bidoof") is None
    assert match_notorious("") is None and match_notorious(None) is None
    assert is_notorious("Umbreon ex - 161/131") is True


def test_trainer_and_energy_never_count_even_with_iconic_name():
    # "Pikachu Rally"/"Charizard Cup" são Trainers no tcgcsv (Card Type "Trainer...")
    assert iconic_name_for_product("Pikachu Rally", "Trainer - Item") is None
    assert iconic_name_for_product("Charizard's Fire Energy", "Energy") is None
    # Pokémon carregam o tipo de energia; tipo desconhecido não reprova
    assert iconic_name_for_product("Charizard ex - 006/165", "Fire") == "Charizard"
    assert iconic_name_for_product("Charizard", None) == "Charizard"
