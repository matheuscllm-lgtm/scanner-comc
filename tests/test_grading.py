"""Slabs: parse do grader/nota da URL da COMC + allowlist + chave PriceCharting."""
import pytest

from comc_scanner.grading import DEFAULT_GRADED_ALLOW, Grade, is_allowed, parse_grade, pc_price_key


@pytest.mark.parametrize("grader_seg,grade_seg,title,key", [
    ("PSA", "10", "Pikachu [PSA 10 GEM MT]", "PSA 10"),
    ("PSA", "9", "Pikachu [PSA 9 MINT]", "PSA 9"),
    ("CGC_Cards", "10", "Charizard ex [CGC 10 Pristine]", "CGC 10 PRISTINE"),
    ("CGC_Cards", "10_GEM", "Charizard ex [CGC 10 Gem Mint]", "CGC 10 GEM"),
    ("CGC_Cards", "9_5 MINT+", "X [CGC 9.5 Mint+]", "CGC 9.5"),
    ("CGC_Cards", "9_5%20MINT+", "X [CGC 9.5 Mint+]", "CGC 9.5"),
    ("BGS", "9_5", "X [BGS 9.5 GEM MINT]", "BGS 9.5"),
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
    assert parse_grade("PSA", "abc", "") is None


def _seg(key: str):
    """'CGC 10 PRISTINE' -> segmentos de URL + título equivalentes."""
    grader, value, *qual = key.split(" ")
    seg_grader = "CGC_Cards" if grader == "CGC" else grader
    seg_grade = value.replace(".", "_") + ("_GEM" if qual == ["GEM"] else "")
    qual_txt = "Pristine" if qual == ["PRISTINE"] else " ".join(qual)
    title = f"X [{grader} {value} {qual_txt}]"
    return seg_grader, seg_grade, title


def test_allowlist_default_matches_operator_scope():
    allow = DEFAULT_GRADED_ALLOW
    for ok in ("PSA 10", "PSA 9", "BGS 10", "BGS 9.5", "TAG 10", "TAG 9.5", "CGC 10 PRISTINE"):
        assert is_allowed(parse_grade(*_seg(ok)), allow), ok
    for bad in ("PSA 8", "CGC 10 GEM", "CGC 9", "SGC 10", "MNT 8.5", "BGS 9"):
        assert not is_allowed(parse_grade(*_seg(bad)), allow), bad


@pytest.mark.parametrize("key,pc_key,proxy", [
    ("PSA 10", "PSA 10", False),
    ("PSA 9", "PSA 9", False),
    ("BGS 10", "BGS 10", False),
    ("BGS 9.5", "GRADE 9.5", True),
    ("CGC 10 PRISTINE", "CGC 10 PRISTINE", False),
    ("TAG 10", "TAG 10", False),
    ("TAG 9.5", "GRADE 9.5", True),
])
def test_pc_price_key(key, pc_key, proxy):
    assert pc_price_key(parse_grade(*_seg(key))) == (pc_key, proxy)
