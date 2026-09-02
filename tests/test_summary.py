"""comc_summary.py — ferramenta de entrega: 2 baldes por status, ranking, funil, links."""
import json

import comc_summary
from comc_summary import CLEAN_TITLE, REVIEW_TITLE, build_markdown, split_buckets


def _row(*, name="Pikachu", number="173/165", comc=10.0, ref=20.0, confidence=0.95,
         price_field="market", ref_source="tcgplayer", pokemon="Pikachu", prank=6,
         listing_type="Raw NM", rank=None,
         comc_url="https://www.comc.com/Cards/Pokemon/x/1",
         tcg_url="https://www.tcgplayer.com/product/1", ref_url=None):
    profit = round(ref - comc, 2)
    row = {
        "margin_pct": round(profit / ref * 100, 2), "roi_pct": round(profit / comc * 100, 2),
        "comc_price": comc, "tcg_reference": ref, "profit_abs": profit,
        "pokemon": pokemon, "pokemon_rank": prank, "card": name, "number": number,
        "card_number": f"{name} {number}", "set": "151", "rarity": "Illustration Rare",
        "listing_type": listing_type, "condition": "NM", "sub_type": "Holofoil",
        "price_field": price_field, "ref_source": ref_source, "era": "recent",
        "confidence": confidence, "match_reason": "set+number", "status": "",
        "review_reasons": "", "quantity": 1, "comc_url": comc_url, "tcg_url": tcg_url,
        "ref_url": ref_url or tcg_url,
    }
    return {"rank": rank, **row} if rank is not None else row


def _payload():
    return {
        "scope": "grupo1", "generated_utc": "20260902T120000Z",
        "min_discount_percent": 20, "min_comc_price": 10.0,
        "graded_allow": ["BGS 10", "PSA 10"], "iconic_only": True, "top_n": 50, "count": 3,
        "funnel": {"seen": 500, "skip_not_iconic": 300, "below_discount": 150, "ok": 1, "review": 2},
        "deals": [
            _row(rank=1, name="Charizard ex", number="199/165", comc=45.0, ref=100.0,
                 pokemon="Charizard", prank=1,
                 comc_url="https://www.comc.com/Cards/Pokemon/x/zard",
                 tcg_url="https://www.tcgplayer.com/product/zard"),
            _row(rank=2, name="Mewtwo", number="150/165", comc=52.0, ref=100.0, price_field="mid",
                 pokemon="Mewtwo", prank=13,
                 comc_url="https://www.comc.com/Cards/Pokemon/x/mewtwo",
                 tcg_url="https://www.tcgplayer.com/product/mewtwo"),
            _row(rank=3, name="Gengar", number="94/165", comc=60.0, ref=100.0, confidence=0.85,
                 pokemon="Gengar", prank=3, listing_type="PSA 10", price_field="PSA 10",
                 ref_source="pricecharting",
                 comc_url="https://www.comc.com/Cards/Pokemon/x/gengar",
                 tcg_url="https://www.tcgplayer.com/product/gengar",
                 ref_url="https://www.pricecharting.com/game/pokemon-151/gengar-94"),
        ],
        "low_confidence": [
            _row(name="Dragonite", number="149/165", comc=40.0, ref=100.0, confidence=0.70,
                 price_field="low", pokemon="Dragonite", prank=7,
                 comc_url="https://www.comc.com/Cards/Pokemon/x/nite",
                 tcg_url="https://www.tcgplayer.com/product/nite"),
        ],
    }


def test_split_buckets_by_status_and_ranking():
    ok, review, n_low = split_buckets(_payload())
    assert [r["card"] for r in ok] == ["Charizard ex"]
    assert [r["card"] for r in review] == ["Dragonite", "Mewtwo", "Gengar"]  # ROI desc
    assert n_low == 1


def test_markdown_has_both_sections_all_rows_and_links():
    md = build_markdown(_payload(), group=1)
    assert CLEAN_TITLE in md and REVIEW_TITLE in md
    for card in ("Charizard ex 199/165", "Mewtwo 150/165", "Gengar 94/165", "Dragonite 149/165"):
        assert card in md, card
    table_lines = [ln for ln in md.splitlines()
                   if ln.startswith("|") and "---" not in ln and "Desconto%" not in ln]
    assert len(table_lines) == 4
    for ln in table_lines:
        assert "[oferta](https://www.comc.com/" in ln and "[referência](https://" in ln
    gengar = next(ln for ln in table_lines if "Gengar" in ln)
    assert "[referência](https://www.pricecharting.com/" in gengar and "| PSA 10 |" in gengar


def test_header_counts_scope_funnel_and_thresholds():
    md = build_markdown(_payload(), group=1)
    assert "grupo 1" in md
    assert "OK: 1 · MATCH_REVIEW: 3 (sendo 1 do balde low-confidence)" in md
    assert "Desconto mínimo: 20%" in md and "piso US$10.0" in md
    assert "Slabs aceitos: BGS 10, PSA 10" in md
    assert "Listagens analisadas: 500" in md and "Pokémon fora da lista: 300" in md


def test_status_reasons_preserved():
    md = build_markdown(_payload())
    assert "preço:mid" in next(ln for ln in md.splitlines() if "Mewtwo" in ln)
    assert "confiança<0.90" in next(ln for ln in md.splitlines() if "Gengar" in ln)
    assert "preço:low" in next(ln for ln in md.splitlines() if "Dragonite" in ln)


def test_pipe_in_cell_is_escaped():
    payload = _payload()
    payload["deals"][0]["card_number"] = "Pika|chu 1/100"
    md = build_markdown(payload)
    assert "Pika|chu" not in md and "Pika/chu 1/100" in md


def test_top_n_cap_warning():
    payload = _payload()
    payload["top_n"] = 3
    assert "Lista cheia no teto top_n=3" in build_markdown(payload)
    assert "Lista cheia no teto" not in build_markdown(_payload())


def test_empty_buckets_render_placeholder():
    md = build_markdown({"scope": "vintage", "generated_utc": "x", "deals": [], "low_confidence": []})
    assert md.count("_(nenhuma linha neste balde)_") == 2


def test_cli_writes_output_file_and_prints(tmp_path, capsys):
    src = tmp_path / "comc_deals_grupo1_latest.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    out = tmp_path / "comc-grupo1.md"
    assert comc_summary.main([str(src), "-o", str(out), "--group", "1"]) == 0
    assert CLEAN_TITLE in out.read_text(encoding="utf-8")
    assert "Charizard ex 199/165" in capsys.readouterr().out


def test_cli_output_flag_is_required(tmp_path):
    import pytest
    src = tmp_path / "x.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(SystemExit):
        comc_summary.main([str(src)])


def test_delivery_uses_the_runs_trust_confidence_not_module_default():
    """Run com TRUST_CONFIDENCE=0.95: deal com confiança 0.92 é MATCH_REVIEW no scan e
    TEM que continuar MATCH_REVIEW na entrega (nunca virar OK por recalcular com 0.90)."""
    payload = _payload()
    payload["trust_confidence"] = 0.95
    payload["deals"] = [_row(rank=1, name="Charizard ex", number="199/165", comc=45.0,
                             ref=100.0, confidence=0.92, pokemon="Charizard", prank=1)]
    payload["low_confidence"] = []
    ok, review, _ = split_buckets(payload)
    assert ok == [] and [r["card"] for r in review] == ["Charizard ex"]
    md = build_markdown(payload)
    line = next(ln for ln in md.splitlines() if "Charizard ex" in ln and ln.startswith("|"))
    assert "MATCH_REVIEW · confiança<0.95" in line
    assert "confiança de match < 0.95" in md
