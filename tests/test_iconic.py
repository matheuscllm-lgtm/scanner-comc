"""Modo --iconic: faixa 30-40% com duas referências (comc_scanner/iconic.py),
tabela icônica (reporter.py), entrega (comc_summary.py) e CLI. Offline."""
import json
from pathlib import Path

import comc_summary
from comc_scanner.__main__ import _apply_overrides, build_parser
from comc_scanner.config import load_settings
from comc_scanner.iconic import band_margin, band_of, iconic_flags, pc_diverges
from comc_scanner.models import ComcListing, Deal, TcgPrice, TcgProduct
from comc_scanner.pipeline import Scanner
from comc_scanner.reporter import render_iconic_rows_table, render_markdown
from comc_summary import (
    ICONIC_ABOVE_TITLE, ICONIC_BELOW_TITLE, ICONIC_CLEAN_TITLE, ICONIC_REVIEW_TITLE,
    build_markdown, split_iconic_buckets,
)


def _settings(**over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _row(margin=35.0, pc_margin=33.0, tcg=100.0, pc=97.0, confidence=0.95,
         price_field="market", name="Charizard ex", number="199/165",
         pc_url="https://www.pricecharting.com/game/x/charizard-ex-199"):
    return {
        "margin_pct": margin, "pc_margin_pct": pc_margin, "comc_price": 65.0,
        "tcg_reference": tcg, "pc_reference": pc, "pc_n_sales": 10,
        "card": name, "number": number, "card_number": f"{name} {number}",
        "set": "SV: Scarlet & Violet 151", "condition": "NM", "sub_type": "Holofoil",
        "price_field": price_field, "confidence": confidence, "notorious": "Charizard",
        "comc_url": "https://www.comc.com/Cards/x", "tcg_url": "https://www.tcgplayer.com/product/1",
        "pc_url": pc_url,
    }


# --- classificação -----------------------------------------------------------

def test_band_margin_is_the_conservative_one():
    assert band_margin(_row(margin=45.0, pc_margin=33.0)) == 0.33
    assert band_margin(_row(margin=33.0, pc_margin=45.0)) == 0.33
    assert band_margin(_row(margin=35.0, pc_margin=None)) == 0.35  # sem PC: só TCG
    assert band_margin({"margin_pct": None}) is None


def test_band_of_faixa_acima_abaixo():
    assert band_of(_row(35.0, 33.0), 0.30, 0.40) == "faixa"
    assert band_of(_row(30.0, 40.0), 0.30, 0.40) == "faixa"  # limites inclusivos
    assert band_of(_row(55.0, 48.0), 0.30, 0.40) == "acima"
    assert band_of(_row(35.0, 22.0), 0.30, 0.40) == "abaixo"  # PC rebaixou
    assert band_of(_row(55.0, 48.0), 0.30, None) == "faixa"   # sem teto = modo clássico
    assert band_of({"margin_pct": None}, 0.30, 0.40) == "sem_margem"


def test_pc_flags():
    assert iconic_flags(_row(pc=None, pc_margin=None)) == ["sem PC"]
    assert iconic_flags(_row(tcg=100.0, pc=50.0)) == ["PC diverge"]   # 50% > 40%
    assert iconic_flags(_row(tcg=100.0, pc=80.0)) == []
    assert pc_diverges(_row(tcg=100.0, pc=None)) is False


# --- buckets da entrega ----------------------------------------------------

def _payload(rows, low=()):
    return {"era": "recent", "generated_utc": "20260902T120000Z", "mode": "iconic",
            "min_gross_margin": 0.30, "max_gross_margin": 0.40, "pricecharting": True,
            "top_n": 200, "count": len(rows), "deals": rows, "low_confidence": list(low)}


def test_split_iconic_buckets_all_rows_land_somewhere():
    rows = [
        _row(name="Clean", margin=35.0, pc_margin=33.0),
        _row(name="LowConf", margin=35.0, pc_margin=33.0, confidence=0.85),
        _row(name="MidPrice", margin=35.0, pc_margin=33.0, price_field="mid"),
        _row(name="SemPC", margin=35.0, pc_margin=None, pc=None),
        _row(name="Diverge", margin=35.0, pc_margin=60.0, tcg=100.0, pc=200.0),
        _row(name="Above", margin=55.0, pc_margin=50.0),
        _row(name="Below", margin=32.0, pc_margin=20.0),
    ]
    low = [_row(name="Bucket70", margin=38.0, pc_margin=36.0, confidence=0.70)]
    b = split_iconic_buckets(_payload(rows, low))
    assert [r["card"] for r in b["clean"]] == ["Clean"]
    assert {r["card"] for r in b["review"]} == {"LowConf", "MidPrice", "SemPC", "Diverge", "Bucket70"}
    assert [r["card"] for r in b["above"]] == ["Above"]
    assert [r["card"] for r in b["below"]] == ["Below"]
    assert sum(len(v) for v in b.values()) == len(rows) + len(low)


def test_review_sorted_by_conservative_margin_desc():
    rows = [_row(name="A", margin=39.0, pc_margin=31.0, confidence=0.85),
            _row(name="B", margin=33.0, pc_margin=38.0, confidence=0.85)]
    b = split_iconic_buckets(_payload(rows))
    assert [r["card"] for r in b["review"]] == ["B", "A"]  # 33 > 31


# --- tabela + summary --------------------------------------------------------

def test_iconic_table_has_two_references_and_three_links():
    out = render_iconic_rows_table([_row()])
    header = out.splitlines()[0]
    for col in ("Marg TCG%", "Marg PC%", "TCG$", "PC$", "Flag", "Links"):
        assert f"| {col} |" in header
    line = out.splitlines()[2]
    assert "[oferta](https://www.comc.com/Cards/x)" in line
    assert "[referência](https://www.tcgplayer.com/product/1)" in line
    assert "[PC](https://www.pricecharting.com/game/x/charizard-ex-199)" in line
    assert "Charizard ex 199/165" in line


def test_iconic_table_marks_missing_pc_honestly():
    line = render_iconic_rows_table([_row(pc=None, pc_margin=None, pc_url="")]).splitlines()[2]
    assert "sem PC" in line
    assert "[PC]" not in line
    assert "| — | " in line  # PC$ / Marg PC% = "—", nunca 0


def test_iconic_flags_compose_with_classic_ones():
    line = render_iconic_rows_table(
        [_row(confidence=0.85, price_field="mid", tcg=100.0, pc=200.0)]).splitlines()[2]
    assert "validar" in line and "preço:mid" in line and "PC diverge" in line


def test_summary_iconic_mode_has_four_sections_and_coverage_lines():
    rows = [_row(name="Clean"), _row(name="Above", margin=55.0, pc_margin=50.0),
            _row(name="Below", margin=32.0, pc_margin=20.0),
            _row(name="SemPC", pc=None, pc_margin=None, pc_url="")]
    md = build_markdown(_payload(rows), group=1)
    for title in (ICONIC_CLEAN_TITLE, ICONIC_REVIEW_TITLE, ICONIC_ABOVE_TITLE, ICONIC_BELOW_TITLE):
        assert title in md
    assert "ICÔNICOS" in md and "grupo 1" in md
    assert "Faixa de desconto (fração): 0.3–0.4" in md
    assert "Cobertura PriceCharting: 3/4 com mediana de vendas reais · 1 sem PC" in md
    assert "Cobertura de preço market: 4 market" in md
    for card in ("Clean 199/165", "Above 199/165", "Below 199/165", "SemPC 199/165"):
        assert card in md
    assert "não é recomendação de compra" in md


def test_summary_classic_payload_unchanged():
    """Payload sem `mode` (scans antigos) segue no formato clássico de 2 seções."""
    md = build_markdown({"era": "recent", "generated_utc": "x", "min_gross_margin": 0.30,
                         "deals": [], "low_confidence": []})
    assert ICONIC_CLEAN_TITLE not in md and "Validar manualmente" in md


def test_summary_cli_reads_iconic_json(tmp_path, capsys):
    src = tmp_path / "comc_iconic_recent_latest.json"
    src.write_text(json.dumps(_payload([_row()])), encoding="utf-8")
    out = tmp_path / "comc-iconicos-g1.md"
    assert comc_summary.main([str(src), "-o", str(out), "--group", "1"]) == 0
    assert ICONIC_CLEAN_TITLE in out.read_text(encoding="utf-8")
    assert "[PC](" in capsys.readouterr().out


# --- render_markdown (flush ao vivo) ---------------------------------------

def _deal(name="Charizard ex - 199/165", card_type="Fire", pc=None):
    product = TcgProduct(product_id=1, group_id=1, set_name="SV: Scarlet & Violet 151",
                         name=name, clean_name=name, number="199/165", rarity="SIR",
                         card_type=card_type, url="https://www.tcgplayer.com/product/1")
    d = Deal(listing=ComcListing(raw_name=name, price=65.0, url="https://www.comc.com/Cards/x",
                                 condition="NM"),
             product=product, price=TcgPrice(product_id=1, sub_type="Holofoil", market=100.0),
             tcg_reference=100.0, price_field_used="market", sub_type_used="Holofoil",
             margin=0.35, match_confidence=0.95, match_reason="set+number", era="recent")
    if pc is not None:
        d.pc_reference, d.pc_margin, d.pc_url, d.pc_n_sales = pc, (pc - 65.0) / pc, "https://pc/x", 10
    return d


def test_render_markdown_iconic_uses_iconic_table_and_as_row_carries_pc():
    out = render_markdown([_deal(pc=97.0)], era="recent", top_n=50, iconic=True)
    assert "icônicos" in out and "| Marg PC% |" in out and "[PC](https://pc/x)" in out
    row = _deal(pc=97.0).as_row()
    assert row["pc_reference"] == 97.0 and row["pc_margin_pct"] == 32.99
    classic = render_markdown([_deal()], era="recent", top_n=50)
    assert "Marg PC%" not in classic  # modo clássico intocado


# --- pipeline: filtro icônico ----------------------------------------------

def test_iconic_filter_off_by_default_and_on_with_setting():
    assert Scanner(_settings())._keep(_deal(name="Bidoof - 1/165")) is True
    sc = Scanner(_settings(iconic_only=True))
    d = _deal()
    assert sc._keep(d) is True and d.notorious == "Charizard"
    assert sc._keep(_deal(name="Bidoof - 1/165")) is False
    assert sc._keep(_deal(name="Pikachu Rally", card_type="Trainer - Item")) is False


def test_iconic_reporter_writes_separate_files(tmp_path):
    s = _settings(iconic_only=True, pricecharting_enabled=False, results_dir=tmp_path)
    from comc_scanner.reporter import Reporter
    rep = Reporter(s)
    assert rep.file_prefix == "comc_iconic"
    rep.flush([_deal()], "recent")
    payload = json.loads((tmp_path / "comc_iconic_recent_latest.json").read_text())
    assert payload["mode"] == "iconic" and payload["pricecharting"] is False
    assert not (tmp_path / "comc_deals_recent_latest.json").exists()


# --- CLI ---------------------------------------------------------------------

def test_cli_iconic_sets_band_defaults_and_fraction_max():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["targeted", "--group", "1", "--iconic"]))
    assert s.iconic_only is True and s.max_gross_margin == 0.40 and s.min_gross_margin == 0.30
    assert s.pricecharting_enabled is True
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(
        ["targeted", "--iconic", "--max-margin", "0.45", "--no-pricecharting"]))
    assert s.max_gross_margin == 0.45 and s.pricecharting_enabled is False


def test_cli_classic_has_no_band_ceiling():
    s = _settings()
    _apply_overrides(s, build_parser().parse_args(["targeted", "--group", "1"]))
    assert s.iconic_only is False and s.max_gross_margin is None
