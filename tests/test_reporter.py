"""Tabela canônica de entrega (reporter.render_markdown) — formato modelo MYP.

Trava: uma coluna `Links` com "[oferta](COMC) · [referência](onde conferir o preço)",
`Carta` = nome+número, `Pokémon`, `Tipo` (Raw NM / nota do slab), `Ref` (fonte do
preço), `Status` OK/MATCH_REVIEW com motivos — linha suspeita marcada, nunca escondida.
"""
from comc_scanner.models import ComcListing, Deal, TcgPrice, TcgProduct
from comc_scanner.reporter import TRUST_CONFIDENCE, _links_cell, classify_row, render_markdown


def _deal(*, name="Pikachu", number="173/165", margin=0.30, confidence=0.95,
          price_field="market", ref_source="tcgplayer", ref_url="", graded=None,
          pokemon="Pikachu", rank=6):
    product = TcgProduct(product_id=1, group_id=1, set_name="151", name=name, clean_name=name,
                         number=number, rarity="Illustration Rare",
                         url="https://www.tcgplayer.com/product/1")
    price = TcgPrice(product_id=1, sub_type="Holofoil", market=100.0)
    listing = ComcListing(raw_name=name, price=70.0, url="https://www.comc.com/Cards/1",
                          condition="NM")
    if graded:
        listing.graded, listing.grader = True, graded.split()[0]
        listing.grade, listing.condition = graded, "10"
    return Deal(listing=listing, product=product, price=price, tcg_reference=100.0,
                price_field_used=price_field, sub_type_used="Holofoil", margin=margin,
                match_confidence=confidence, match_reason="set+number", era="recent",
                pokemon=pokemon, pokemon_rank=rank, ref_source=ref_source, ref_url=ref_url)


def _line(out, needle="Pikachu"):
    return next(l for l in out.splitlines() if needle in l and l.startswith("|"))


def test_empty_deals_renders_placeholder():
    assert "nenhum deal" in render_markdown([], label="grupo1", top_n=50)


def test_table_has_offer_and_reference_links_in_one_column():
    out = render_markdown([_deal()], label="grupo1", top_n=50)
    header = next(l for l in out.splitlines() if l.lstrip().startswith("| #"))
    assert "| Links |" in header and "Oferta" not in header
    assert ("[oferta](https://www.comc.com/Cards/1) · "
            "[referência](https://www.tcgplayer.com/product/1)") in out


def test_slab_reference_link_points_to_pricecharting():
    out = render_markdown([_deal(graded="PSA 10", ref_source="pricecharting",
                                 price_field="PSA 10",
                                 ref_url="https://www.pricecharting.com/game/x/y")],
                          label="g", top_n=50)
    line = _line(out)
    assert "[referência](https://www.pricecharting.com/game/x/y)" in line
    assert "| PSA 10 |" in line and "PC PSA 10" in line


def test_links_cell_placeholder_when_no_urls():
    assert _links_cell({"comc_url": None, "tcg_url": None}) == "—"
    assert _links_cell({"comc_url": "https://c/1", "tcg_url": None}) == "[oferta](https://c/1)"
    assert _links_cell({"comc_url": None, "tcg_url": "https://t/1", "ref_url": "https://p/1"}) == \
        "[referência](https://p/1)"


def test_card_column_is_name_plus_number_and_pokemon_column():
    out = render_markdown([_deal(name="Charizard ex", number="199/165", pokemon="Charizard", rank=1)],
                          label="g", top_n=50)
    line = _line(out, "Charizard ex 199/165")
    assert "| Charizard |" in line and "| Raw NM |" in line and "TCG market" in line


def test_status_ok_vs_match_review_reasons():
    ok = _line(render_markdown([_deal(confidence=0.99)], label="g", top_n=50))
    assert "| OK |" in ok and "preço:" not in ok
    low = _line(render_markdown([_deal(confidence=TRUST_CONFIDENCE - 0.05)], label="g", top_n=50))
    assert "MATCH_REVIEW · confiança<0.90" in low
    mid = _line(render_markdown([_deal(price_field="mid")], label="g", top_n=50))
    assert "MATCH_REVIEW · preço:mid" in mid
    both = _line(render_markdown([_deal(confidence=0.85, price_field="low")], label="g", top_n=50))
    assert "confiança<0.90" in both and "preço:low" in both
    proxy = _line(render_markdown([_deal(graded="BGS 9.5", ref_source="pricecharting-proxy",
                                         price_field="GRADE 9.5")], label="g", top_n=50))
    assert "MATCH_REVIEW · ref~proxy:GRADE 9.5" in proxy and "PC GRADE 9.5~" in proxy


def test_classify_row_is_the_single_source_of_truth():
    assert classify_row({"confidence": 0.95, "price_field": "market"}) == ("OK", [])
    assert classify_row({"confidence": 0.95, "price_field": "PSA 10",
                         "ref_source": "pricecharting"}) == ("OK", [])
    assert classify_row({"confidence": 0.8, "price_field": "mid"})[1] == ["confiança<0.90", "preço:mid"]


def test_columns_and_ranking_order():
    out = render_markdown([_deal(name="A", margin=0.30), _deal(name="B", margin=0.30)],
                          label="g", top_n=50)
    header = next(l for l in out.splitlines() if l.lstrip().startswith("| #"))
    assert header.count("|") == 15  # 14 colunas
    for col in ("Desconto%", "ROI%", "Lucro$", "Pokémon", "Carta", "Tipo", "Ref", "Status", "Links"):
        assert f"| {col} |" in header
