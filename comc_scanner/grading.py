"""Slabs (cartas gradadas): parse da nota a partir da URL da COMC + escopo aceito.

Formato real da COMC (captura 2026-09-02, ``tests/fixtures/comc_graded_*``):
``/Cards/Pokemon/<ano>/<set>/<nº>/<nome>/<id>/Graded/<grader>/<nota>`` com
grader ∈ {PSA, CGC_Cards, BGS, TAG, SGC, MNT} e nota como ``10``, ``10_GEM``,
``9_5``, ``9_5 MINT+``, ``10G``, ``8_5_NearMint+``. A CGC tem DUAS notas 10:
``10`` = "CGC 10 Pristine" e ``10_GEM`` = "CGC 10 Gem Mint" (o título da
listagem, ex. ``[CGC 10 Pristine]``, confirma).

Escopo do operador (spec 2026-09-02): PSA, BGS, TAG e CGC SÓ se Pristine 10.
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
    "PSA 10", "PSA 9",
    "BGS 10", "BGS 9.5",
    "TAG 10", "TAG 9.5",
    "CGC 10 PRISTINE",
})

# Colunas que a página do PriceCharting expõe por nome exato.
_PC_DIRECT = {"PSA 10", "PSA 9", "BGS 10", "CGC 10 PRISTINE", "SGC 10"}
_PC_KEY_FOR_CGC_GEM = "CGC 10"  # rótulo do PC para CGC Gem Mint 10

_VALUE_RE = re.compile(r"^(\d{1,2})(?:[._](\d))?")


@dataclass(frozen=True, slots=True)
class Grade:
    grader: str          # PSA / CGC / BGS / TAG / SGC / MNT
    value: float         # 10.0, 9.5 ...
    qualifier: str = ""  # "PRISTINE" / "GEM" (só relevante na CGC 10)

    @property
    def key(self) -> str:
        base = f"{self.grader} {self.value:g}"
        return f"{base} {self.qualifier}" if self.qualifier else base

    @property
    def label(self) -> str:
        """Texto curto para a entrega, ex. 'PSA 10', 'CGC 10 Pristine'."""
        return self.key.replace("PRISTINE", "Pristine").replace("GEM", "Gem Mint")


def parse_grade(grader_seg: str, grade_seg: str, title: str = "") -> Grade | None:
    """Segmentos ``<grader>/<nota>`` da URL (+ título opcional) → Grade, ou None."""
    grader = _GRADER_ALIASES.get(urllib.parse.unquote(grader_seg or "").strip().upper())
    seg = urllib.parse.unquote(grade_seg or "").strip()
    m = _VALUE_RE.match(seg)
    if not grader or not m:
        return None
    value = float(f"{m.group(1)}.{m.group(2)}") if m.group(2) else float(m.group(1))
    qualifier = ""
    if grader == "CGC" and value == 10.0:
        low_title = (title or "").lower()
        if "pristine" in low_title:
            qualifier = "PRISTINE"
        elif "gem" in low_title or "GEM" in seg.upper():
            qualifier = "GEM"
        else:
            qualifier = "PRISTINE"  # segmento ``10`` puro = Pristine (captura real)
    return Grade(grader=grader, value=value, qualifier=qualifier)


def is_allowed(grade: Grade | None, allow: frozenset[str] | set[str] = DEFAULT_GRADED_ALLOW) -> bool:
    return grade is not None and grade.key in allow


def pc_price_key(grade: Grade) -> tuple[str | None, bool]:
    """(coluna do PriceCharting, é_proxy). Proxy = o PC não tem a coluna exata
    daquela empresa/nota e usamos a mais próxima — sempre sinalizado na entrega
    (nunca silencioso). Sem equivalente razoável → (None, True)."""
    key = grade.key
    if key in _PC_DIRECT:
        return key, False
    if key == "CGC 10 GEM":
        return _PC_KEY_FOR_CGC_GEM, False
    if grade.value == 9.5:
        return "GRADE 9.5", True          # PC agrega BGS/CGC/TAG 9.5 num bucket genérico
    if grade.grader == "TAG" and grade.value == 10.0:
        return "PSA 10", True
    if grade.grader == "TAG" and grade.value == 9.0:
        return "PSA 9", True
    return None, True
