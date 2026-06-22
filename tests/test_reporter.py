"""Offline tests for the canonical chat delivery table (reporter.render_markdown).

These lock the canonical format documented in README "Entrega dos resultados" and
CLAUDE.md: every row carries a single `Links` column joining the COMC offer link
([oferta]) and the TCGPlayer price reference link ([referência]) with " · " — the
cross-scanner format shared with MYP/Liga — plus the card name+number and a per-row
review flag ("validar" for low-confidence matches — never dropped).
"""
from comc_scanner.models import ComcListing, Deal, TcgPrice, TcgProduct
from comc_scanner.reporter import TRUST_CONFIDENCE, render_markdown


def _deal(*, name="Pikachu", number="173/165", margin=0.30, confidence=0.95,
          price_field="market"):
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
        price_field_used=price_field,
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


def test_market_backed_deal_carries_no_price_tag():
    """A real `market`-backed reference must NOT be annotated — clean flag only.

    Locks that the common, trustworthy case stays visually unmarked so the
    fallback annotation actually stands out (honesty signal must be distinct)."""
    out = render_markdown([_deal(price_field="market", confidence=0.99)], era="recent", top_n=50)
    line = next(l for l in out.splitlines() if "Pikachu" in l)
    assert "preço:" not in line
    assert " ok " in line


def test_mid_fallback_deal_is_visually_distinct_from_market():
    """A `mid`-fallback deal must be distinguishable from a real-market deal in the
    chat table (the #55/#58 lesson: fallback shown as real is forbidden)."""
    market_out = render_markdown([_deal(price_field="market")], era="recent", top_n=50)
    mid_out = render_markdown([_deal(price_field="mid")], era="recent", top_n=50)

    market_line = next(l for l in market_out.splitlines() if "Pikachu" in l)
    mid_line = next(l for l in mid_out.splitlines() if "Pikachu" in l)

    assert "preço:mid" in mid_line
    assert "preço:" not in market_line
    assert mid_line != market_line  # the two surfaces are not identical


def test_low_fallback_deal_tagged_preco_low():
    out = render_markdown([_deal(price_field="low")], era="recent", top_n=50)
    line = next(l for l in out.splitlines() if "Pikachu" in l)
    assert "preço:low" in line


def test_price_tag_composes_with_validar_flag():
    """Both honesty signals coexist: a low-confidence AND fallback-priced row shows
    both "validar" and "preço:<campo>" (neither suppresses the other)."""
    out = render_markdown(
        [_deal(confidence=TRUST_CONFIDENCE - 0.05, price_field="low")],
        era="recent", top_n=50,
    )
    line = next(l for l in out.splitlines() if "Pikachu" in l)
    assert "validar" in line
    assert "preço:low" in line


def test_no_new_columns_added_to_table():
    """Annotation lives inside the existing Flag column — header is unchanged
    (no dedicated price-source column added; Links/Card kept intact)."""
    out = render_markdown([_deal(price_field="mid")], era="recent", top_n=50)
    header = next(l for l in out.splitlines() if l.lstrip().startswith("| #"))
    assert "| Flag |" in header
    assert "| Links |" in header
    # 12 canonical columns, unchanged.
    assert header.count("|") == 13
