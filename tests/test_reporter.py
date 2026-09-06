"""Tabela canônica de entrega (reporter.render_markdown) — formato modelo MYP.

Trava: uma coluna `Links` com "[oferta](COMC) · [referência](onde conferir o preço)",
`Carta` = nome+número, `Pokémon`, `Tipo` (Raw NM/EX-NM/LP ou a nota do slab), `Ref`
(fonte do preço), `Status` OK/MATCH_REVIEW com motivos + notas — linha suspeita
marcada, nunca escondida. Métricas: Desconto%, ROI bruto%, Spread$ (nunca "lucro").
"""
import comc_scanner.reporter as reporter_mod
from comc_scanner.models import ComcListing, Deal, TcgPrice, TcgProduct
from comc_scanner.reporter import (FUNNEL_LABELS, TRUST_CONFIDENCE, _links_cell, _ref_label,
                                   _status_cell, classify_row, funnel_lines, render_markdown,
                                   render_rows_table, row_notes)

SALES_PSA10 = "vendas PSA 10 (n=5, 2026-03..2026-08)"


def _deal(*, name="Pikachu", number="173/165", margin=0.30, confidence=0.95,
          price_field="market", ref_source="tcgplayer", ref_url="", graded=None,
          pokemon="Pikachu", rank=6, condition="NM", **extra):
    product = TcgProduct(product_id=1, group_id=1, set_name="151", name=name, clean_name=name,
                         number=number, rarity="Illustration Rare",
                         url="https://www.tcgplayer.com/product/1")
    price = TcgPrice(product_id=1, sub_type="Holofoil", market=100.0)
    listing = ComcListing(raw_name=name, price=70.0, url="https://www.comc.com/Cards/1",
                          condition=condition)
    if graded:
        listing.graded, listing.grader = True, graded.split()[0]
        listing.grade, listing.condition = graded, "10"
    return Deal(listing=listing, product=product, price=price, tcg_reference=100.0,
                price_field_used=price_field, sub_type_used="Holofoil", margin=margin,
                match_confidence=confidence, match_reason="set+number", era="recent",
                pokemon=pokemon, pokemon_rank=rank, ref_source=ref_source, ref_url=ref_url,
                **extra)


def _line(out, needle="Pikachu"):
    return next(l for l in out.splitlines() if needle in l and l.startswith("|"))


def _header(out):
    return next(l for l in out.splitlines() if l.lstrip().startswith("| #"))


def test_empty_deals_renders_placeholder():
    assert "nenhum deal" in render_markdown([], label="grupo1", top_n=50)


def test_table_has_offer_and_reference_links_in_one_column():
    out = render_markdown([_deal()], label="grupo1", top_n=50)
    header = _header(out)
    assert "| Links |" in header and "Oferta" not in header
    assert ("[oferta](https://www.comc.com/Cards/1) · "
            "[referência](https://www.tcgplayer.com/product/1)") in out


def test_slab_reference_link_points_to_pricecharting():
    out = render_markdown([_deal(graded="PSA 10", ref_source="pricecharting-sales",
                                 price_field=SALES_PSA10, ref_n_sales=5,
                                 ref_url="https://www.pricecharting.com/game/x/y")],
                          label="g", top_n=50)
    line = _line(out)
    assert "[referência](https://www.pricecharting.com/game/x/y)" in line
    assert "| PSA 10 |" in line and f"| PC {SALES_PSA10} |" in line
    assert "| OK |" in line


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
    thin = _line(render_markdown([_deal(graded="PSA 9", ref_source="pricecharting-sales",
                                        price_field="vendas PSA 9 (n=2, 2026-01..2026-06)",
                                        ref_n_sales=2, ref_liquidity="thin")],
                                 label="g", top_n=50))
    assert "MATCH_REVIEW · vendas<3(n=2)" in thin


def test_legacy_json_sources_are_flagged_and_labelled():
    """Compat com JSON antigo: coluna ("pricecharting") e proxy ("pricecharting-proxy")
    nunca são OK e o rótulo diz que é o formato antigo."""
    proxy = _line(render_markdown([_deal(graded="BGS 9.5", ref_source="pricecharting-proxy",
                                         price_field="GRADE 9.5")], label="g", top_n=50))
    assert "MATCH_REVIEW · ref~proxy" in proxy and "PC GRADE 9.5~ (antigo)" in proxy
    col = _line(render_markdown([_deal(graded="PSA 10", ref_source="pricecharting",
                                       price_field="PSA 10", ref_n_sales=5)], label="g", top_n=50))
    assert "MATCH_REVIEW · ref=coluna(antigo)" in col and "| PC coluna PSA 10 (antigo) |" in col
    assert "sem-vendas-recentes" not in col and "ref÷vendas" not in col


def test_classify_row_is_the_single_source_of_truth():
    assert classify_row({"confidence": 0.95, "price_field": "market"}) == ("OK", [])
    assert classify_row({"confidence": 0.8, "price_field": "mid"})[1] == ["confiança<0.90", "preço:mid"]
    assert classify_row({"confidence": 0.95, "price_field": "market", "ref_source": "tcgplayer",
                         "listing_type": "PSA 10"})[1] == ["slab×ref-raw"]
    sales = {"confidence": 0.95, "price_field": SALES_PSA10, "ref_source": "pricecharting-sales",
             "listing_type": "PSA 10", "tcg_reference": 100.0}
    assert classify_row({**sales, "ref_n_sales": 3}) == ("OK", [])
    assert classify_row({**sales, "ref_n_sales": 2}) == ("MATCH_REVIEW", ["vendas<3(n=2)"])
    assert classify_row({**sales, "ref_n_sales": 1}) == ("MATCH_REVIEW", ["vendas<3(n=1)"])
    assert classify_row({**sales, "ref_n_sales": 0}) == ("MATCH_REVIEW", ["vendas<3(n=0)"])
    assert classify_row({**sales, "ref_n_sales": None}) == ("OK", [])  # ausente = desconhecido
    assert classify_row(sales) == ("OK", [])
    lp = {**sales, "ref_source": "pricecharting-sales-lp", "listing_type": "Raw LP",
          "price_field": "vendas LP (n=4, 2026-05..2026-08)", "ref_n_sales": 4}
    assert classify_row(lp) == ("OK", [])
    assert classify_row({**lp, "ref_n_sales": 2}) == ("MATCH_REVIEW", ["vendas<3(n=2)"])


def test_classify_row_column_sanity_against_sales_median():
    """Coluna exata informativa >30% longe da mediana de vendas → revisar; dentro → OK;
    ausente → nada a checar."""
    base = {"confidence": 0.95, "price_field": SALES_PSA10, "ref_source": "pricecharting-sales",
            "listing_type": "PSA 10", "tcg_reference": 60.0, "ref_n_sales": 5}
    assert classify_row({**base, "ref_column_price": 99.99}) == \
        ("MATCH_REVIEW", ["coluna÷vendas(99.99)"])
    assert classify_row({**base, "ref_column_price": 70.0}) == ("OK", [])
    assert classify_row({**base, "ref_column_price": None}) == ("OK", [])
    assert classify_row({**base, "ref_column_price": 99.99, "tcg_reference": 0}) == ("OK", [])
    assert classify_row({**base, "ref_column_price": "abc"}) == ("OK", [])


def test_classify_row_legacy_sources():
    assert classify_row({"confidence": 0.95, "price_field": "PSA 10", "ref_source": "pricecharting",
                         "ref_n_sales": 0, "tcg_reference": 99.99}) == \
        ("MATCH_REVIEW", ["ref=coluna(antigo)"])
    assert classify_row({"confidence": 0.95, "price_field": "GRADE 9.5",
                         "ref_source": "pricecharting-proxy"}) == ("MATCH_REVIEW", ["ref~proxy"])


def test_low_liquidity_is_a_note_not_a_status_change():
    row = {"confidence": 0.95, "price_field": "vendas PSA 9 (n=4, 2025-10..2026-08)",
           "ref_source": "pricecharting-sales", "listing_type": "PSA 9", "tcg_reference": 100.0,
           "ref_n_sales": 4, "ref_liquidity": "low", "ref_window_days": 365}
    assert classify_row(row) == ("OK", [])
    assert row_notes(row) == ["baixa-liquidez(365d)"]
    assert _status_cell(row) == "OK · baixa-liquidez(365d)"
    for liq in ("ok", "thin", "", None):
        assert row_notes({**row, "ref_liquidity": liq}) == []
    both = {**row, "confidence": 0.5}
    assert _status_cell(both) == "MATCH_REVIEW · confiança<0.90 · baixa-liquidez(365d)"


def test_ref_label_variants():
    assert _ref_label({"ref_source": "pricecharting-sales", "price_field": SALES_PSA10}) == \
        f"PC {SALES_PSA10}"
    assert _ref_label({"ref_source": "pricecharting-sales-lp",
                       "price_field": "vendas LP (n=4, 2026-05..2026-08)"}) == \
        "PC vendas LP (n=4, 2026-05..2026-08)"
    assert _ref_label({"ref_source": "tcgplayer", "price_field": "market"}) == "TCG market"
    assert _ref_label({"price_field": "mid"}) == "TCG mid"
    assert _ref_label({"ref_source": "pricecharting", "price_field": "PSA 10"}) == \
        "PC coluna PSA 10 (antigo)"


def test_columns_and_ranking_order():
    out = render_markdown([_deal(name="A", margin=0.30), _deal(name="B", margin=0.30)],
                          label="g", top_n=50)
    header = _header(out)
    assert header.count("|") == 17  # 16 colunas
    expected = ["#", "Desconto%", "ROI bruto%", "COMC$", "Ref$", "Spread$", "Pokémon", "Carta",
                "Set", "Tipo", "Ref", "Conf", "Status", "Vendedor", "Revisão aquisição", "Links"]
    assert [c.strip() for c in header.strip().strip("|").split("|")] == expected
    assert "lucro" not in out.lower()


def test_title_and_docstring_use_operator_vocabulary():
    out = render_markdown([_deal()], label="g", top_n=50)
    assert "(ROI bruto → desconto → spread)" in out.splitlines()[0]
    assert "lucro" not in reporter_mod.__doc__.lower()
    assert "Spread$" in reporter_mod.__doc__ and "ROI bruto%" in reporter_mod.__doc__


def test_legacy_row_with_profit_abs_only_renders_spread_column():
    """JSON antigo traz `profit_abs` e não `spread_abs`: a célula Spread$ usa o valor
    antigo (nunca fica vazia)."""
    row = {"margin_pct": 30.74, "roi_pct": 44.39, "comc_price": 69.25, "tcg_reference": 99.99,
           "profit_abs": 30.74, "pokemon": "Luxray", "card_number": "Luxray ex 195/167",
           "set": "SV06", "listing_type": "CGC 10 Pristine", "price_field": "CGC 10 PRISTINE",
           "ref_source": "pricecharting", "confidence": 0.95, "ref_n_sales": 0,
           "comc_url": "https://www.comc.com/x", "ref_url": "https://www.pricecharting.com/y"}
    line = render_rows_table([row]).splitlines()[2]
    assert line.startswith("| 1 | 30.74 | 44.39 | 69.25 | [99.99](https://www.pricecharting.com/y) | 30.74 | Luxray |")
    assert "MATCH_REVIEW · ref=coluna(antigo)" in line


def test_listing_type_labels():
    assert _deal(graded="PSA 10").listing_type == "PSA 10"
    assert _deal(graded="CGC 10 PRISTINE").listing_type == "CGC 10 Pristine"
    assert _deal(graded="CGC 10 GEM").listing_type == "CGC 10 Gem Mint"
    assert _deal(graded="BGS 10 BLACK").listing_type == "BGS 10 Black Label"
    assert _deal(graded="BGS 10").listing_type == "BGS 10"
    assert _deal(graded="TAG 9.5").listing_type == "TAG 9.5"
    assert _deal(condition="NM").listing_type == "Raw NM"
    assert _deal(condition="EX-NM").listing_type == "Raw EX-NM"
    assert _deal(condition="LP").listing_type == "Raw LP"


def test_as_row_has_spread_and_reference_metadata():
    row = _deal(graded="PSA 9", ref_source="pricecharting-sales",
                price_field="vendas PSA 9 (n=4, 2025-10..2026-08)", ref_n_sales=4,
                ref_sales_median=100.0, ref_liquidity="low", ref_window_days=365,
                ref_column_price=120.0).as_row()
    assert row["spread_abs"] == 30.0 and "profit_abs" not in row
    assert row["ref_liquidity"] == "low" and row["ref_window_days"] == 365
    assert row["ref_column_price"] == 120.0 and row["ref_n_sales"] == 4
    assert row["ref_source"] == "pricecharting-sales" and row["listing_type"] == "PSA 9"
    raw = _deal().as_row()
    assert raw["ref_liquidity"] == "" and raw["ref_window_days"] == 0
    assert raw["ref_column_price"] is None


def test_funnel_labels_new_keys_order_and_wording():
    keys = [k for k, _ in FUNNEL_LABELS]
    labels = dict(FUNNEL_LABELS)
    for k in ("lp_prefilter", "lp_no_reference", "lp_pc_error"):
        assert k in keys, k
    assert (keys.index("slab_grade_malformed") < keys.index("lp_prefilter")
            < keys.index("lp_no_reference") < keys.index("lp_pc_error")
            < keys.index("below_discount"))
    assert labels["slab_no_reference"] == ("Slabs sem vendas comparáveis (mesma certificadora"
                                           "+nota+variante) — sem referência")
    assert labels["skip_condition"] == ("Ignoradas: condição fora do permitido (WotC ≤2003 "
                                        "NM/EX-NM; 2004+ NM; LP só com referência LP)")
    assert labels["lp_prefilter"] == ("Raw LP acima do pré-filtro (COMC > ref NM × "
                                      "(1 − desconto mín.))")
    assert labels["lp_no_reference"] == "Raw LP sem ≥3 vendas LP comparáveis — sem referência"
    assert labels["lp_pc_error"] == "Raw LP com ERRO na fonte PriceCharting"
    lines = funnel_lines({"seen": 10, "lp_prefilter": 2, "lp_no_reference": 1, "lp_pc_error": 3})
    assert lines == ["Listagens analisadas: 10",
                     f"{labels['lp_prefilter']}: 2",
                     f"{labels['lp_no_reference']}: 1",
                     f"{labels['lp_pc_error']}: 3"]
