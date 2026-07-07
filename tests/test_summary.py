"""Offline tests for comc_summary.py — the canonical delivery tool.

Feeds a JSON payload in the REAL Reporter format (deals + low_confidence rows,
mixed price_field values) and locks the delivery contract: two sections (clean
vs. validar), every row present, the two links per row, the market/mid/low
price-coverage honesty line, and `|` escaping inside cells.
"""
import json

import comc_summary
from comc_summary import CLEAN_TITLE, REVIEW_TITLE, build_markdown, split_buckets


def _row(*, name="Pikachu", number="173/165", margin=42.5, comc=10.0, tcg=20.0,
         confidence=0.95, price_field="market", rank=None,
         comc_url="https://www.comc.com/Cards/Pokemon/x/1",
         tcg_url="https://www.tcgplayer.com/product/1"):
    """Flat row exactly as Deal.as_row() lands in the Reporter JSON."""
    row = {
        "margin_pct": margin,
        "comc_price": comc,
        "tcg_reference": tcg,
        "profit_abs": round(tcg - comc, 2),
        "card": name,
        "number": number,
        "card_number": f"{name} {number}",
        "set": "151",
        "rarity": "Illustration Rare",
        "condition": "NM",
        "sub_type": "Holofoil",
        "price_field": price_field,
        "era": "recent",
        "confidence": confidence,
        "match_reason": "set+number",
        "quantity": 1,
        "comc_url": comc_url,
        "tcg_url": tcg_url,
    }
    if rank is not None:
        row = {"rank": rank, **row}
    return row


def _payload():
    """Reporter-shaped payload: 3 qualifying deals (one clean, one mid-fallback,
    one low-ish confidence still above the 0.80 gate) + 1 low_confidence row."""
    return {
        "era": "recent",
        "generated_utc": "20260706T120000Z",
        "min_gross_margin": 0.30,
        "top_n": 50,
        "count": 3,
        "deals": [
            _row(rank=1, name="Charizard ex", number="199/165", margin=55.0,
                 confidence=0.95, price_field="market",
                 comc_url="https://www.comc.com/Cards/Pokemon/x/zard",
                 tcg_url="https://www.tcgplayer.com/product/zard"),
            _row(rank=2, name="Mewtwo", number="150/165", margin=48.0,
                 confidence=0.95, price_field="mid",
                 comc_url="https://www.comc.com/Cards/Pokemon/x/mewtwo",
                 tcg_url="https://www.tcgplayer.com/product/mewtwo"),
            _row(rank=3, name="Alakazam", number="65/165", margin=40.0,
                 confidence=0.85, price_field="market",
                 comc_url="https://www.comc.com/Cards/Pokemon/x/kazam",
                 tcg_url="https://www.tcgplayer.com/product/kazam"),
        ],
        "low_confidence": [
            _row(name="Dragonite", number="149/165", margin=60.0,
                 confidence=0.70, price_field="low",
                 comc_url="https://www.comc.com/Cards/Pokemon/x/nite",
                 tcg_url="https://www.tcgplayer.com/product/nite"),
        ],
    }


def test_split_buckets_clean_needs_high_confidence_and_market_price():
    clean, review, n_low = split_buckets(_payload())
    assert [r["card"] for r in clean] == ["Charizard ex"]
    # mid-fallback + sub-gate confidence + the low_confidence bucket all go to review
    assert {r["card"] for r in review} == {"Mewtwo", "Alakazam", "Dragonite"}
    assert n_low == 1


def test_review_sorted_by_margin_desc():
    _, review, _ = split_buckets(_payload())
    margins = [r["margin_pct"] for r in review]
    assert margins == sorted(margins, reverse=True)
    assert review[0]["card"] == "Dragonite"  # 60% > 48% > 40%


def test_markdown_has_both_sections_and_all_rows():
    md = build_markdown(_payload(), group=1)
    assert CLEAN_TITLE in md and REVIEW_TITLE in md
    for card in ("Charizard ex 199/165", "Mewtwo 150/165",
                 "Alakazam 65/165", "Dragonite 149/165"):
        assert card in md, card


def test_every_row_carries_offer_and_reference_links():
    md = build_markdown(_payload())
    table_lines = [ln for ln in md.splitlines()
                   if ln.startswith("|") and "---" not in ln and "Margin%" not in ln]
    assert len(table_lines) == 4
    for ln in table_lines:
        assert "[oferta](https://www.comc.com/" in ln
        assert "[referência](https://www.tcgplayer.com/" in ln


def test_header_counts_and_price_coverage_line():
    md = build_markdown(_payload(), group=2)
    assert "grupo 2" in md
    assert "Deals ok: 1 · validar: 3 (sendo 1 do balde low-confidence)" in md
    assert "Cobertura de preço market: 2 market · 1 mid · 1 low" in md


def test_pipe_in_cell_is_escaped():
    payload = _payload()
    payload["deals"][0]["card_number"] = "Pika|chu 1/100"
    md = build_markdown(payload)
    assert "Pika|chu" not in md          # raw pipe would break the table
    assert "Pika/chu 1/100" in md        # reporter._cell escapes | -> /


def test_flags_preserved_validar_and_price_tag():
    md = build_markdown(_payload())
    mewtwo = next(ln for ln in md.splitlines() if "Mewtwo" in ln)
    assert "preço:mid" in mewtwo
    dragonite = next(ln for ln in md.splitlines() if "Dragonite" in ln)
    assert "validar" in dragonite and "preço:low" in dragonite
    alakazam = next(ln for ln in md.splitlines() if "Alakazam" in ln)
    assert "validar" in alakazam


def test_empty_buckets_render_placeholder_not_broken_table():
    md = build_markdown({"era": "vintage", "generated_utc": "x",
                         "min_gross_margin": 0.30, "deals": [], "low_confidence": []})
    assert md.count("_(nenhuma linha neste balde)_") == 2


def test_cli_writes_output_file_and_prints(tmp_path, capsys):
    src = tmp_path / "comc_deals_recent_latest.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    out = tmp_path / "comc-grupo1-2026-07-06.md"
    rc = comc_summary.main([str(src), "-o", str(out), "--group", "1"])
    assert rc == 0
    disk = out.read_text(encoding="utf-8")
    assert CLEAN_TITLE in disk
    printed = capsys.readouterr().out
    assert "Charizard ex 199/165" in printed  # printed AND written, same content


def test_cli_output_flag_is_required(tmp_path):
    import pytest
    src = tmp_path / "x.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(SystemExit):
        comc_summary.main([str(src)])
