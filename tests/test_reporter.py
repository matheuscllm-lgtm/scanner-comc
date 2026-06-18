"""Offline tests for the canonical chat delivery table (reporter.render_markdown).

These lock the canonical format documented in README "Entrega dos resultados" and
CLAUDE.md: every row carries a single `Links` column joining the COMC offer link
([oferta]) and the TCGPlayer price reference link ([referência]) with " · " — the
cross-scanner format shared with MYP/Liga — plus the card name+number and a per-row
review flag ("validar" for low-confidence matches — never dropped).
"""
from comc_scanner.models import ComcListing, Deal, TcgPrice, TcgProduct
from comc_scanner.reporter import TRUST_CONFIDENCE, render_markdown


def _deal(*, name="Pikachu", number="173/165", margin=0.30, confidence=0.95):
    product = TcgProduct(
        product_id=1,
        group_id=1,
        set_name="151",
        name=name,
        clean_name=name,
        number=number,
        rarity="Illustration Rare",
        url="https://www.tcgplayer.com/product/1",
    )
    price = TcgPrice(product_id=1, sub_type="Holofoil", market=100.0)
    listing = ComcListing(
        raw_name=name,
        price=70.0,
        url="https://www.comc.com/Cards/1",
        condition="NM",
    )
    return Deal(
        listing=listing,
        product=product,
        price=price,
        tcg_reference=100.0,
        price_field_used="market",
        sub_type_used="Holofoil",
        margin=margin,
        match_confidence=confidence,
        match_reason="set+number",
        era="recent",
    )


def test_empty_deals_renders_placeholder():
    out = render_markdown([], era="recent", top_n=50)
    assert "nenhum deal" in out


def test_table_has_offer_and_reference_links():
    out = render_markdown([_deal()], era="recent", top_n=50)
    assert "[oferta](https://www.comc.com/Cards/1)" in out
    assert "[referência](https://www.tcgplayer.com/product/1)" in out


def test_links_merged_into_single_column():
    """Canonical cross-scanner format: one `Links` column, the two links joined by " · ".

    Locks the merge (no longer separate Oferta/Referência columns) so the COMC table
    matches MYP (`delivery_links`) and Liga (`_links`)."""
    out = render_markdown([_deal()], era="recent", top_n=50)
    header = next(l for l in out.splitlines() if l.lstrip().startswith("| #"))
    assert "| Links |" in header
    assert "Oferta" not in header and "Referência" not in header
    assert (
        "[oferta](https://www.comc.com/Cards/1) · "
        "[referência](https://www.tcgplayer.com/product/1)"
    ) in out


def test_links_cell_placeholder_when_no_urls():
    """Missing links collapse to an em dash "—", mirroring MYP/Liga, never blank/invented."""
    from comc_scanner.reporter import _links_cell

    assert _links_cell({"comc_url": None, "tcg_url": None}) == "—"
    assert _links_cell({"comc_url": "https://c/1", "tcg_url": None}) == "[oferta](https://c/1)"


def test_card_column_is_name_plus_number():
    out = render_markdown([_deal(name="Charizard ex", number="199/165")], era="recent", top_n=50)
    assert "Charizard ex 199/165" in out


def test_low_confidence_row_flagged_validar_not_dropped():
    out = render_markdown([_deal(confidence=TRUST_CONFIDENCE - 0.05)], era="recent", top_n=50)
    assert "validar" in out
    assert "Pikachu" in out  # still present, not hidden


def test_high_confidence_row_flagged_ok():
    out = render_markdown([_deal(confidence=0.99)], era="recent", top_n=50)
    lines = [l for l in out.splitlines() if "Pikachu" in l]
    assert lines and " ok " in lines[0]
