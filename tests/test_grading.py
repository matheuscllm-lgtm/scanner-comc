"""Slabs: parse do grader/nota da URL da COMC + allowlist + coluna INFORMATIVA do PriceCharting.

Política do operador (2026-09-02): a referência de slab é SEMPRE a mediana de vendas da
mesma certificadora+nota (+ subcategoria: BGS 10 Black Label ≠ BGS 10; CGC 10 Pristine ≠
CGC 10 Gem Mint). Coluna do PriceCharting = só informação; "proxy" deixou de existir."""
import pytest

from comc_scanner.grading import (DEFAULT_GRADED_ALLOW, Grade, is_allowed, mentions_black_label,
                                  parse_grade, pc_price_key)


@pytest.mark.parametrize("grader_seg,grade_seg,title,key", [
    ("PSA", "10", "Pikachu [PSA 10 GEM MT]", "PSA 10"),
    ("PSA", "9", "Pikachu [PSA 9 MINT]", "PSA 9"),
    ("PSA", "8", "Pikachu [PSA 8 NM-MT]", "PSA 8"),
    ("CGC_Cards", "10", "Charizard ex [CGC 10 Pristine]", "CGC 10 PRISTINE"),
    ("CGC_Cards", "10_GEM", "Charizard ex [CGC 10 Gem Mint]", "CGC 10 GEM"),
    ("CGC_Cards", "9_5 MINT+", "X [CGC 9.5 Mint+]", "CGC 9.5"),
    ("CGC_Cards", "9_5%20MINT+", "X [CGC 9.5 Mint+]", "CGC 9.5"),
    ("BGS", "9_5", "X [BGS 9.5 GEM MINT]", "BGS 9.5"),
    ("BGS", "10", "X [BGS 10 PRISTINE]", "BGS 10"),               # gold/pristine = BGS 10 "puro"
    ("BGS", "10", "X [BGS 10 Black Label]", "BGS 10 BLACK"),      # subcategoria própria
    ("BGS", "10_Black_Label", "X", "BGS 10 BLACK"),               # "black" no segmento da URL
    ("BGS", "10", "Pikachu Black Star Promo [BGS 10]", "BGS 10"),  # "Black Star" ≠ Black Label
    ("BGS", "10", "Black Kyurem EX [BGS 10 PRISTINE]", "BGS 10"),  # nome da carta fora do [..]
    ("BGS", "9_5", "X [BGS 9.5 Black Label]", "BGS 9.5"),          # Black Label só existe no 10
    ("TAG", "9", "X [TAG 9 MINT]", "TAG 9"),
    ("SGC", "10G", "X [SGC 10 GEM]", "SGC 10"),
    ("MNT", "8_5_NearMint+", "X [MNT 8.5 NMNT-MNT+]", "MNT 8.5"),
])
def test_parse_grade_key(grader_seg, grade_seg, title, key):
    g = parse_grade(grader_seg, grade_seg, title)
    assert isinstance(g, Grade)
    assert g.key == key


def test_parse_grade_fields():
    g = parse_grade("CGC_Cards", "10", "Charizard ex [CGC 10 Pristine]")
    assert (g.grader, g.value, g.qualifier) == ("CGC", 10.0, "PRISTINE")
    b = parse_grade("BGS", "10", "Charizard [BGS 10 Black Label]")
    assert (b.grader, b.value, b.qualifier) == ("BGS", 10.0, "BLACK")
    assert parse_grade("PSA", "abc", "") is None


@pytest.mark.parametrize("seg,label", [
    (("PSA", "10", ""), "PSA 10"),
    (("BGS", "10", "X [BGS 10 Black Label]"), "BGS 10 Black Label"),
    (("BGS", "10", "X [BGS 10]"), "BGS 10"),
    (("CGC_Cards", "10", "X [CGC 10 Pristine]"), "CGC 10 Pristine"),
    (("CGC_Cards", "10_GEM", "X [CGC 10 Gem Mint]"), "CGC 10 Gem Mint"),
    (("TAG", "9_5", ""), "TAG 9.5"),
])
def test_grade_label_for_delivery(seg, label):
    assert parse_grade(*seg).label == label


def test_mentions_black_label_ignores_black_star_and_black_dot():
    assert mentions_black_label("BGS 10 Black Label")
    assert mentions_black_label("BGS BLACK 10")
    assert mentions_black_label("10_Black_Label")            # segmento de URL com underscores
    assert not mentions_black_label("Pikachu Black Star Promo BGS 10")
    assert not mentions_black_label("BASE SET BLACK DOT ERR CHARIZARD BGS 10")
    assert not mentions_black_label("BGS 10 PRISTINE")
    assert not mentions_black_label("")


def _seg(key: str):
    """'CGC 10 PRISTINE' / 'BGS 10 BLACK' -> segmentos de URL + título equivalentes."""
    grader, value, *qual = key.split(" ")
    seg_grader = "CGC_Cards" if grader == "CGC" else grader
    seg_grade = value.replace(".", "_") + ("_GEM" if qual == ["GEM"] else "")
    qual_txt = {"PRISTINE": "Pristine", "BLACK": "Black Label", "GEM": "Gem Mint"}.get(
        qual[0] if qual else "", "")
    title = f"X [{grader} {value} {qual_txt}]".replace(" ]", "]")
    return seg_grader, seg_grade, title


ALLOWED = ("PSA 8", "PSA 9", "PSA 10",
           "CGC 9", "CGC 9.5", "CGC 10 GEM", "CGC 10 PRISTINE",
           "BGS 9", "BGS 9.5", "BGS 10", "BGS 10 BLACK",
           "SGC 9", "SGC 9.5", "SGC 10",
           "TAG 9.5", "TAG 10")


def test_allowlist_default_matches_operator_scope():
    assert DEFAULT_GRADED_ALLOW == frozenset(ALLOWED)
    for ok in ALLOWED:
        assert is_allowed(parse_grade(*_seg(ok)), DEFAULT_GRADED_ALLOW), ok
    for bad in ("PSA 7", "CGC 8.5", "BGS 8", "SGC 8.5", "TAG 9", "MNT 8.5", "ACE 10", "MNT 10"):
        assert not is_allowed(parse_grade(*_seg(bad)), DEFAULT_GRADED_ALLOW), bad
    assert not is_allowed(None, DEFAULT_GRADED_ALLOW)


@pytest.mark.parametrize("key,pc_key", [
    ("PSA 10", "PSA 10"),
    ("PSA 9", None),            # "Grade 9" é bucket genérico: NEM como informação
    ("PSA 8", None),
    ("BGS 10", "BGS 10"),
    ("BGS 10 BLACK", "BGS 10 BLACK"),
    ("BGS 9.5", None),
    ("CGC 10 PRISTINE", "CGC 10 PRISTINE"),
    ("CGC 10 GEM", "CGC 10"),   # rótulo do PC para CGC Gem Mint 10
    ("CGC 9.5", None),
    ("SGC 10", "SGC 10"),
    ("TAG 10", "TAG 10"),
    ("TAG 9.5", None),
    ("ACE 10", "ACE 10"),
])
def test_pc_price_key_is_exact_column_or_none_no_proxy(key, pc_key):
    got = pc_price_key(parse_grade(*_seg(key)))
    assert got == pc_key
    assert got is None or isinstance(got, str)  # nunca tupla (coluna, proxy)
