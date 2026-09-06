"""comc_summary.py — ferramenta de entrega: 2 baldes por status, ranking, funil, links,
modo diagnóstico `--sensitivity` (faixas de desconto) e `--group` = grupos canônicos."""
import json

import pytest

import comc_scanner.groups as groups
import comc_summary
from comc_summary import (CLEAN_TITLE, REVIEW_TITLE, build_markdown, parse_sensitivity,
                          split_buckets)

SALES_PSA10 = "vendas PSA 10 (n=5, 2026-03..2026-08)"


def _row(*, name="Pikachu", number="173/165", comc=10.0, ref=20.0, confidence=0.95,
         price_field="market", ref_source="tcgplayer", pokemon="Pikachu", prank=6,
         listing_type="Raw NM", rank=None,
         comc_url="https://www.comc.com/Cards/Pokemon/x/1",
         tcg_url="https://www.tcgplayer.com/product/1", ref_url=None, **extra):
    spread = round(ref - comc, 2)
    row = {
        "margin_pct": round(spread / ref * 100, 2), "roi_pct": round(spread / comc * 100, 2),
        "comc_price": comc, "tcg_reference": ref, "spread_abs": spread,
        "pokemon": pokemon, "pokemon_rank": prank, "card": name, "number": number,
        "card_number": f"{name} {number}", "set": "151", "rarity": "Illustration Rare",
        "listing_type": listing_type, "condition": "NM", "sub_type": "Holofoil",
        "price_field": price_field, "ref_source": ref_source, "era": "recent",
        "confidence": confidence, "match_reason": "set+number", "status": "",
        "review_reasons": "", "quantity": 1, "comc_url": comc_url, "tcg_url": tcg_url,
        "ref_url": ref_url or tcg_url, **extra,
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
                 pokemon="Gengar", prank=3, listing_type="PSA 10", price_field=SALES_PSA10,
                 ref_source="pricecharting-sales", ref_n_sales=5,
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


def _table_lines(md: str) -> list[str]:
    """Só as linhas de DEAL (16 colunas = 17 pipes); exclui cabeçalho/separador e a
    tabela de contagens do modo diagnóstico (4 colunas)."""
    return [ln for ln in md.splitlines()
            if ln.startswith("|") and ln.count("|") == 17
            and "---" not in ln and "Desconto%" not in ln]


def _section(md: str, title: str) -> str:
    """Texto da seção `title` até o próximo '## '."""
    body = md.split(title, 1)[1]
    nxt = body.find("\n## ")
    return body if nxt < 0 else body[:nxt]


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
    table_lines = _table_lines(md)
    assert len(table_lines) == 4
    for ln in table_lines:
        assert "[oferta](https://www.comc.com/" in ln and "[referência](https://" in ln
    gengar = next(ln for ln in table_lines if "Gengar" in ln)
    assert "[referência](https://www.pricecharting.com/" in gengar and "| PSA 10 |" in gengar
    assert f"| PC {SALES_PSA10} |" in gengar


def test_header_counts_scope_funnel_and_thresholds():
    md = build_markdown(_payload(), group=1)
    assert "grupo 1" in md
    assert "OK: 1 · MATCH_REVIEW: 3 (sendo 1 do balde low-confidence)" in md
    assert "Desconto mínimo: 20%" in md and "piso US$10.0" in md
    assert "raw NM; EX-NM separada para revisão; LP só com referência LP" in md
    assert "Slabs aceitos: BGS 10, PSA 10" in md
    assert "Listagens analisadas: 500" in md and "Pokémon fora da lista: 300" in md


def test_footer_explains_status_notes_metrics_and_ranking():
    md = build_markdown(_payload())
    footer = next(ln for ln in md.splitlines() if ln.startswith("_MATCH_REVIEW"))
    for needle in ("MATCH_REVIEW", "confiança de match < 0.90", "mid/low", "`vendas<3`",
                   "`coluna÷vendas`", "`baixa-liquidez(365d)`", "≥3 vendas só em 365 dias",
                   "PC vendas <nota|LP> (n=…, mês..mês)",
                   "mediana de ≥3 vendas concluídas da mesma carta, variante, certificadora e nota",
                   "Desconto% = (ref − COMC)/ref", "Spread$ = ref − COMC (bruto, sem taxas)",
                   "ROI bruto% = spread/COMC",
                   "Ranking: ROI bruto → desconto % → spread US$ → popularidade",
                   "não é recomendação de compra"):
        assert needle in footer, needle
    assert "lucro" not in md.lower()
    assert "sem-vendas-recentes" not in md and "ref÷vendas" not in md


def test_status_reasons_preserved():
    md = build_markdown(_payload())
    assert "preço:mid" in next(ln for ln in md.splitlines() if "Mewtwo" in ln)
    assert "confiança<0.90" in next(ln for ln in md.splitlines() if "Gengar" in ln)
    assert "preço:low" in next(ln for ln in md.splitlines() if "Dragonite" in ln)


def test_low_liquidity_note_stays_ok_in_delivery():
    payload = _payload()
    payload["deals"] = [_row(rank=1, name="Charizard ex", number="199/165", comc=45.0, ref=100.0,
                             pokemon="Charizard", prank=1, listing_type="PSA 9",
                             price_field="vendas PSA 9 (n=4, 2025-10..2026-08)",
                             ref_source="pricecharting-sales", ref_n_sales=4,
                             ref_liquidity="low", ref_window_days=365)]
    payload["low_confidence"] = []
    ok, review, _ = split_buckets(payload)
    assert [r["card"] for r in ok] == ["Charizard ex"] and review == []
    md = build_markdown(payload)
    line = next(ln for ln in _section(md, CLEAN_TITLE).splitlines() if "Charizard" in ln)
    assert "| OK · baixa-liquidez(365d) |" in line


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
    src = tmp_path / "x.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(SystemExit):
        comc_summary.main([str(src)])


def test_cli_group_accepts_any_canonical_group_number(tmp_path, monkeypatch):
    """`--group` = `groups.VALID_GROUP_NUMBERS` (não hardcode 1-4): grupo 12 é aceito
    quando o catálogo o define; fora do catálogo é rejeitado."""
    monkeypatch.setattr(groups, "VALID_GROUP_NUMBERS", tuple(range(1, 13)))
    src = tmp_path / "comc_deals_grupo12_latest.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    out = tmp_path / "comc-grupo12.md"
    assert comc_summary.main([str(src), "-o", str(out), "--group", "12"]) == 0
    assert "grupo 12" in out.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        comc_summary.main([str(src), "-o", str(out), "--group", "99"])


def test_cli_group_choices_follow_the_catalog():
    assert set(groups.VALID_GROUP_NUMBERS) >= {1, 2, 3, 4}
    for n in groups.VALID_GROUP_NUMBERS:
        assert isinstance(n, int)


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


def test_legacy_payload_with_profit_abs_still_renders():
    """JSON gravado antes da PR A: `profit_abs` e `ref_source="pricecharting"` (coluna).
    A entrega ainda sai, com Spread$ = profit_abs e a linha marcada como formato antigo."""
    payload = _payload()
    row = _row(rank=1, name="Luxray ex", number="195/167", comc=69.25, ref=99.99,
               pokemon="Luxray", prank=40, listing_type="CGC 10 Pristine",
               price_field="CGC 10 PRISTINE", ref_source="pricecharting", ref_n_sales=0,
               ref_url="https://www.pricecharting.com/game/x/luxray")
    row["profit_abs"] = row.pop("spread_abs")
    payload["deals"], payload["low_confidence"] = [row], []
    ok, review, _ = split_buckets(payload)
    assert ok == [] and [r["card"] for r in review] == ["Luxray ex"]
    line = next(ln for ln in build_markdown(payload).splitlines() if "Luxray" in ln)
    assert "| 30.74 | Luxray |" in line and "ref=coluna(antigo)" in line
    assert "| PC coluna CGC 10 PRISTINE (antigo) |" in line


# ── modo diagnóstico --sensitivity ──────────────────────────────────────────────

OP_OK = "## 🟢 ≥20% — candidato comercial (sujeito às demais validações)"
OP_REVIEW = "## ⚠️ ≥20% — MATCH_REVIEW"
DIAG_15 = "## 🔬 Diagnóstico 15–19,99% — NÃO é oportunidade"
DIAG_10 = "## 🔬 Diagnóstico 10–14,99% — NÃO é oportunidade"


def _sensitivity_payload():
    """7 linhas em faixas de desconto distintas (ref=100 → desconto = 100 − comc)."""
    p = _payload()
    p["min_discount_percent"] = 10
    p["deals"] = [
        _row(rank=1, name="Charizard ex", number="6/102", comc=75.0, ref=100.0,
             pokemon="Charizard", prank=1),                                     # 25% OK
        _row(rank=2, name="Mewtwo", number="10/102", comc=78.0, ref=100.0, price_field="mid",
             pokemon="Mewtwo", prank=13),                                       # 22% REVIEW
        _row(rank=3, name="Blastoise", number="2/102", comc=80.01, ref=100.0,
             pokemon="Blastoise", prank=9),                                     # 19.99% OK
        _row(rank=4, name="Venusaur", number="15/102", comc=85.0, ref=100.0, confidence=0.8,
             pokemon="Venusaur", prank=20),                                     # 15% REVIEW
        _row(rank=5, name="Gengar", number="5/62", comc=85.01, ref=100.0,
             pokemon="Gengar", prank=3),                                        # 14.99% OK
        _row(rank=6, name="Pikachu", number="58/102", comc=90.0, ref=100.0,
             pokemon="Pikachu", prank=6),                                       # 10% OK
        _row(rank=7, name="Snorlax", number="11/64", comc=90.5, ref=100.0,
             pokemon="Snorlax", prank=30),                                      # 9.5% OK
    ]
    p["low_confidence"] = []
    p["count"] = 7
    return p


def test_parse_sensitivity_requires_ascending_positive_ints():
    assert parse_sensitivity("10,15,20") == [10, 15, 20]
    assert parse_sensitivity(" 20 ") == [20]
    for bad in ("20,15,10", "10,10", "abc", "", "0,10", "10,-5"):
        with pytest.raises(Exception):
            parse_sensitivity(bad)


def test_sensitivity_counts_table_and_sections():
    md = build_markdown(_sensitivity_payload(), group=3, sensitivity=[10, 15, 20])
    assert "Modo diagnóstico: scan com desconto mínimo 10% · limiar operacional 20%" in md
    assert "| Limiar | OK | MATCH_REVIEW | Total |" in md
    assert "| ≥20% | 1 | 1 | 2 |" in md
    assert "| ≥15% | 2 | 2 | 4 |" in md
    assert "| ≥10% | 4 | 2 | 6 |" in md
    for title in (OP_OK, OP_REVIEW, DIAG_15, DIAG_10):
        assert title in md, title
    order = [md.index(t) for t in (OP_OK, OP_REVIEW, DIAG_15, DIAG_10)]
    assert order == sorted(order)
    assert CLEAN_TITLE not in md and REVIEW_TITLE not in md


def test_sensitivity_band_membership_is_by_discount_pct():
    md = build_markdown(_sensitivity_payload(), sensitivity=[10, 15, 20])
    op_ok = _section(md, OP_OK)
    op_rev = _section(md, OP_REVIEW)
    d15 = _section(md, DIAG_15)
    d10 = _section(md, DIAG_10)
    assert "Charizard ex" in op_ok and "Mewtwo" not in op_ok and "Blastoise" not in op_ok
    assert "Mewtwo" in op_rev and "Charizard" not in op_rev and "Blastoise" not in op_rev
    assert "Blastoise" in d15 and "Venusaur" in d15  # 19,99 e 15,00 na faixa 15–19,99
    assert "Charizard" not in d15 and "Gengar" not in d15
    assert "Gengar" in d10 and "Pikachu" in d10 and "Venusaur" not in d10
    assert "Snorlax" not in md  # 9,5% < menor limiar: fora de todas as faixas
    # status continua na coluna nas faixas diagnósticas (OK e MATCH_REVIEW juntos)
    assert "| OK |" in d15 and "MATCH_REVIEW · confiança<0.90" in d15
    # toda linha da ferramenta tem os 2 links
    for ln in _table_lines(md):
        assert "[oferta](https://www.comc.com/" in ln and "[referência](https://" in ln
    assert len(_table_lines(md)) == 6


def test_sensitivity_placeholders_and_single_threshold():
    payload = _sensitivity_payload()
    payload["deals"] = payload["deals"][:1]  # só o 25% OK
    md = build_markdown(payload, sensitivity=[10, 15, 20])
    assert "_(nenhuma linha neste balde)_" in _section(md, OP_REVIEW)
    assert "_(nenhuma linha neste balde)_" in _section(md, DIAG_15)
    assert "| ≥20% | 1 | 0 | 1 |" in md and "| ≥10% | 1 | 0 | 1 |" in md
    md1 = build_markdown(payload, sensitivity=[20])
    assert OP_OK in md1 and OP_REVIEW in md1 and "Diagnóstico" not in md1
    assert "limiar operacional 20%" in md1


def test_sensitivity_warns_when_scan_threshold_above_lowest_band():
    payload = _sensitivity_payload()
    payload["min_discount_percent"] = 20
    md = build_markdown(payload, sensitivity=[10, 15, 20])
    assert "desconto mínimo 20%" in md
    assert "faixas abaixo de 20% ficam vazias por construção" in md


def test_without_sensitivity_keeps_two_sections():
    md = build_markdown(_sensitivity_payload())
    assert CLEAN_TITLE in md and REVIEW_TITLE in md
    assert "Diagnóstico" not in md and "Limiar" not in md
    assert len(_table_lines(md)) == 7


def test_cli_sensitivity_flag(tmp_path, capsys):
    src = tmp_path / "comc_deals_grupo3_latest.json"
    src.write_text(json.dumps(_sensitivity_payload()), encoding="utf-8")
    out = tmp_path / "comc-grupo3-sens.md"
    assert comc_summary.main([str(src), "-o", str(out), "--group", "3",
                              "--sensitivity", "10,15,20"]) == 0
    text = out.read_text(encoding="utf-8")
    assert OP_OK in text and DIAG_10 in text and "| ≥15% | 2 | 2 | 4 |" in text
    assert "Diagnóstico 15–19,99%" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        comc_summary.main([str(src), "-o", str(out), "--sensitivity", "20,10"])
