"""Pokémon icônicos — a lista de personagens que o scanner procura.

A lista mora FORA do código, em ``comc_scanner/iconic_pokemon.csv`` (colunas
``rank,pokemon,score,sources``; rank 1 = mais procurado), fornecida pelo operador
(top-100 por popularidade, 2026-09-02). Editar o CSV = mudar o universo do scan;
nenhum nome fica hardcoded na lógica.

Matcher (mesmas regras do ``notorious.py`` do scanner integrado):
- palavra INTEIRA no nome da carta, sem diferenciar maiúsculas/acentos —
  "Charizard ex", "Dark Charizard", "Mega Gengar ex" casam; "Charizardite X" não;
- nomes compostos ("Roaring Moon") casam como frase;
- empate → o nome mais LONGO vence ("Mewtwo VSTAR" é Mewtwo, não Mew).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ICONIC_CSV = Path(__file__).resolve().parent / "iconic_pokemon.csv"


@dataclass(frozen=True, slots=True)
class IconicEntry:
    rank: int
    name: str
    score: float


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def load_iconic(path: Path = ICONIC_CSV) -> list[IconicEntry]:
    """Lê o CSV (ordenado por rank). Linhas sem nome são ignoradas."""
    out: list[IconicEntry] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("pokemon") or "").strip()
            if not name:
                continue
            try:
                rank = int(row.get("rank") or 0)
            except ValueError:
                rank = 0
            try:
                score = float(row.get("score") or 0.0)
            except ValueError:
                score = 0.0
            out.append(IconicEntry(rank=rank, name=name, score=score))
    out.sort(key=lambda e: e.rank)
    return out


_ENTRIES: tuple[IconicEntry, ...] = tuple(load_iconic())
ICONIC_POKEMON: tuple[str, ...] = tuple(e.name for e in _ENTRIES)

# Um padrão por nome: palavra inteira (não precedida/seguida por letra), sem
# distinguir maiúsculas; o texto é normalizado (sem acentos) antes de buscar.
_PATTERNS: tuple[tuple[IconicEntry, re.Pattern[str]], ...] = tuple(
    (e, re.compile(rf"(?<![A-Za-z]){re.escape(_strip_accents(e.name))}(?![A-Za-z])",
                   re.IGNORECASE))
    for e in _ENTRIES
)


def match_iconic(card_name: str | None) -> IconicEntry | None:
    """Entrada icônica contida no nome da carta, ou None."""
    if not card_name:
        return None
    text = _strip_accents(str(card_name))
    best: IconicEntry | None = None
    for entry, pattern in _PATTERNS:
        if pattern.search(text) and (best is None or len(entry.name) > len(best.name)):
            best = entry
    return best


def is_iconic(card_name: str | None) -> bool:
    return match_iconic(card_name) is not None
