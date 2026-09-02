"""Lista curada de Pokémon "icônicos/notórios" + matcher de nome de carta.

Portada do `integrated-scanner/notorious.py` da frota (os repos não compartilham
código de propósito — cada scanner carrega a própria cópia). "Icônico" aqui =
Pokémon com histórico consistente de demanda no mercado colecionável; é um
FILTRO de escopo do modo `--iconic` (só cartas desses personagens entram),
não previsão de preço. O operador decide capital.

Regras do matcher (travadas em tests/test_notorious.py):
- Match por PALAVRA INTEIRA no nome da carta, case-insensitive, sem acento.
  "Charizard ex - 199/165", "Dark Charizard", "Mega Charizard EX" → "Charizard".
  "Charizardite X" (item) → NÃO casa (a palavra é "Charizardite").
- "Mew" não casa dentro de "Mewtwo"; "Mewtwo" tem entrada própria e vence
  (match mais longo).
- Trainer/Energy nunca contam como carta do personagem ("Pikachu Rally" é um
  Trainer): o filtro `is_iconic_product` olha o `Card Type` do tcgcsv.
"""
from __future__ import annotations

import re
import unicodedata

NOTORIOUS_POKEMON: tuple[str, ...] = (
    # Kanto starters + evoluções finais — os ícones absolutos do colecionismo;
    # Charizard é historicamente a carta mais líquida do hobby.
    "Charizard", "Charmander", "Charmeleon",
    "Blastoise", "Squirtle", "Wartortle",
    "Venusaur", "Bulbasaur", "Ivysaur",
    # Pikachu-line — mascote da franquia.
    "Pikachu", "Raichu",
    # Eevee + eeveelutions — fandom dedicado; Umbreon domina alt-arts modernas.
    "Eevee", "Vaporeon", "Jolteon", "Flareon",
    "Espeon", "Umbreon", "Leafeon", "Glaceon", "Sylveon",
    # Lendários/míticos Gen 1-2 — vintage premium e reprints sempre procurados.
    "Mewtwo", "Mew", "Lugia", "Ho-Oh", "Celebi",
    "Articuno", "Zapdos", "Moltres",
    # Pseudo-lendários e "fan favorites" Gen 1.
    "Dragonite", "Gyarados", "Snorlax", "Gengar", "Alakazam", "Machamp",
    "Arcanine", "Lapras", "Ditto",
    # Gen 3+ lendários com base de fãs forte.
    "Rayquaza", "Kyogre", "Groudon", "Latias", "Latios", "Jirachi",
    "Metagross", "Salamence",
    # Pseudo-lendários e ícones Gen 4-6.
    "Garchomp", "Lucario", "Giratina", "Darkrai", "Dialga", "Palkia",
    "Arceus", "Greninja", "Goodra", "Dragapult",
    # Modernos com culto próprio.
    "Mimikyu", "Gardevoir", "Tyranitar", "Absol", "Zoroark",
)

# Palavra inteira: sem letra antes, sem letra minúscula depois (assim
# "Charizard ex" casa mas "Charizardite" não).
_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![a-z])", re.IGNORECASE)
    for name in NOTORIOUS_POKEMON
}

# `Card Type` do tcgcsv: Pokémon carregam o tipo de energia ("Fire", "Water"...);
# cartas de treinador/energia começam com estes prefixos.
_NON_POKEMON_TYPE_PREFIXES = ("trainer", "energy", "item", "supporter", "stadium", "tool")


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def match_notorious(card_name: str | None) -> str | None:
    """Nome do Pokémon icônico contido no nome da carta, ou None.

    "Charizard ex - 199/165" → "Charizard"; "Charizardite X" → None;
    "Mewtwo VSTAR" → "Mewtwo" (não "Mew")."""
    if not card_name:
        return None
    text = _normalize(str(card_name))
    best: str | None = None
    for name, pattern in _PATTERNS.items():
        if pattern.search(text) and (best is None or len(name) > len(best)):
            best = name
    return best


def is_notorious(card_name: str | None) -> bool:
    return match_notorious(card_name) is not None


def is_pokemon_card_type(card_type: str | None) -> bool:
    """True salvo quando o `Card Type` do tcgcsv diz Trainer/Energy. Tipo
    desconhecido (None) NÃO reprova — o nome decide (o tcgcsv deixa alguns
    Pokémon sem tipo)."""
    ct = (card_type or "").strip().lower()
    return not ct.startswith(_NON_POKEMON_TYPE_PREFIXES)


def iconic_name_for_product(name: str | None, card_type: str | None) -> str | None:
    """Personagem icônico de um produto TCGplayer, ou None (Trainer/Energy ou
    Pokémon fora da lista)."""
    if not is_pokemon_card_type(card_type):
        return None
    return match_notorious(name)
