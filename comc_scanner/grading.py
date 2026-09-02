"""Slabs (cartas gradadas): parse da nota a partir da URL da COMC + escopo aceito.

Formato real da COMC (captura 2026-09-02, ``tests/fixtures/comc_graded_*``):
``/Cards/Pokemon/<ano>/<set>/<nº>/<nome>/<id>/Graded/<grader>/<nota>`` com
grader ∈ {PSA, CGC_Cards, BGS, TAG, SGC, MNT} e nota como ``10``, ``10_GEM``,
``9_5``, ``9_5 MINT+``, ``10G``, ``8_5_NearMint+``. A CGC tem DUAS notas 10:
``10`` = "CGC 10 Pristine" e ``10_GEM`` = "CGC 10 Gem Mint" (o título da
listagem, ex. ``[CGC 10 Pristine]``, confirma). A BGS também tem duas: ``BGS 10``
(Pristine, etiqueta dourada) e ``BGS 10 Black Label`` (etiqueta preta, subcategoria
própria) — só vira "BLACK" quando o segmento da URL ou o ``[...]`` do título diz
"black" ("Black Star" promo e "Black Dot" erro NÃO contam).

Política do operador (2026-09-02):
- Allowlist ``DEFAULT_GRADED_ALLOW`` (editável via env ``GRADED_ALLOW``): PSA 8/9/10;
  CGC 9/9.5/10 Gem/10 Pristine; BGS 9/9.5/10/10 Black; SGC 9/9.5/10; TAG 9.5/10.
- A REFERÊNCIA de um slab é sempre a mediana de vendas concluídas da MESMA
  certificadora + nota + subcategoria + variante (``pricecharting_client.graded_reference``).
  Nota vizinha, bucket genérico ("Grade 9", "Grade 9.5") ou coluna do PriceCharting
  NUNCA viram referência — o conceito de "proxy" deixou de existir.
- ``pc_price_key`` devolve só a coluna EXATA da nota ("PSA 10", "BGS 10 Black"…),
  que o cliente guarda como INFORMAÇÃO (``SalesRef.column_price``) para a sanidade
  coluna÷vendas na entrega. Nota sem coluna exata → None.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

_GRADER_ALIASES = {
    "CGC_CARDS": "CGC", "CGC": "CGC", "PSA": "PSA", "BGS": "BGS", "BECKETT": "BGS",
    "TAG": "TAG", "SGC": "SGC", "MNT": "MNT", "ACE": "ACE", "GMA": "GMA",
}

# Chaves aceitas (formato ``<GRADER> <nota>[ <qualificador>]``). Editável via
# env ``GRADED_ALLOW`` (ver config.py).
DEFAULT_GRADED_ALLOW: frozenset[str] = frozenset({
    "PSA 8", "PSA 9", "PSA 10",
    "CGC 9", "CGC 9.5", "CGC 10 GEM", "CGC 10 PRISTINE",
    "BGS 9", "BGS 9.5", "BGS 10", "BGS 10 BLACK",
    "SGC 9", "SGC 9.5", "SGC 10",
    "TAG 9.5", "TAG 10",
})

# Colunas que a página do PriceCharting expõe por nome EXATO ("Full Price Guide",
# verificado 2026-09-02: TAG 10, ACE 10, SGC 10, CGC 10, PSA 10, BGS 10, BGS 10 Black,
# CGC 10 Pristine). Chave da nota → rótulo normalizado da coluna. SÓ informação:
# "Grade 9" / "Grade 9.5" são buckets GENÉRICOS (misturam certificadoras) e ficam fora.
_PC_EXACT_COLUMN = {
    "PSA 10": "PSA 10",
    "BGS 10": "BGS 10",
    "BGS 10 BLACK": "BGS 10 BLACK",
    "CGC 10 PRISTINE": "CGC 10 PRISTINE",
    "CGC 10 GEM": "CGC 10",  # rótulo do PC para CGC Gem Mint 10
    "SGC 10": "SGC 10",
    "TAG 10": "TAG 10",
    "ACE 10": "ACE 10",
}
_LABEL_WORDS = {"PRISTINE": "Pristine", "GEM": "Gem Mint", "BLACK": "Black Label"}

_VALUE_RE = re.compile(r"^(\d{1,2})(?:[._](\d))?")
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_BLACK_NOT_LABEL_RE = re.compile(r"\bblack\s*[-_]?\s*(?:star|dot)\b", re.I)
_BLACK_RE = re.compile(r"\bblack\b", re.I)


@dataclass(frozen=True, slots=True)
class Grade:
    grader: str          # PSA / CGC / BGS / TAG / SGC / MNT
    value: float         # 10.0, 9.5 ...
    qualifier: str = ""  # "PRISTINE" / "GEM" (CGC 10) · "BLACK" (BGS 10 Black Label)

    @property
    def key(self) -> str:
        base = f"{self.grader} {self.value:g}"
        return f"{base} {self.qualifier}" if self.qualifier else base

    @property
    def label(self) -> str:
        """Texto curto para a entrega: 'PSA 10', 'CGC 10 Pristine', 'CGC 10 Gem Mint',
        'BGS 10 Black Label'."""
        base = f"{self.grader} {self.value:g}"
        if not self.qualifier:
            return base
        return f"{base} {_LABEL_WORDS.get(self.qualifier, self.qualifier)}"


def mentions_black_label(text: str) -> bool:
    """"black" no texto = etiqueta preta da BGS (Black Label). Ignora "Black Star"
    (promo) e "Black Dot" (erro de impressão), que são nome de carta/variante."""
    text = (text or "").replace("_", " ")
    return _BLACK_RE.search(_BLACK_NOT_LABEL_RE.sub(" ", text)) is not None


def _qualifier_text(seg: str, title: str) -> str:
    """Onde procurar o qualificador: o segmento da URL + o ``[...]`` do título (ou o
    título inteiro quando não há colchetes). O nome da carta fora dos colchetes
    ("Black Kyurem") não conta."""
    m = _BRACKET_RE.search(title or "")
    return f"{seg} {m.group(1) if m else (title or '')}"


def parse_grade(grader_seg: str, grade_seg: str, title: str = "") -> Grade | None:
    """Segmentos ``<grader>/<nota>`` da URL (+ título opcional) → Grade, ou None."""
    grader = _GRADER_ALIASES.get(urllib.parse.unquote(grader_seg or "").strip().upper())
    seg = urllib.parse.unquote(grade_seg or "").strip()
    m = _VALUE_RE.match(seg)
    if not grader or not m:
        return None
    value = float(f"{m.group(1)}.{m.group(2)}") if m.group(2) else float(m.group(1))
    qualifier = ""
    if value == 10.0 and grader in ("CGC", "BGS"):
        text = _qualifier_text(seg, title)
        low = text.lower()
        if grader == "CGC":
            if "pristine" in low:
                qualifier = "PRISTINE"
            elif "gem" in low:
                qualifier = "GEM"
            else:
                qualifier = "PRISTINE"  # segmento ``10`` puro = Pristine (captura real)
        elif mentions_black_label(text):
            qualifier = "BLACK"
    return Grade(grader=grader, value=value, qualifier=qualifier)


def is_allowed(grade: Grade | None, allow: frozenset[str] | set[str] = DEFAULT_GRADED_ALLOW) -> bool:
    return grade is not None and grade.key in allow


def pc_price_key(grade: Grade) -> str | None:
    """Coluna EXATA do PriceCharting para a nota ("PSA 10", "BGS 10 BLACK", "CGC 10"
    para CGC Gem Mint…) ou None quando a nota não tem coluna própria (PSA 9, BGS 9.5,
    TAG 9.5…). A coluna é SÓ informação (``SalesRef.column_price``): a referência vem
    sempre da mediana de vendas comparáveis; bucket genérico/nota vizinha nunca entra."""
    return _PC_EXACT_COLUMN.get(grade.key)
