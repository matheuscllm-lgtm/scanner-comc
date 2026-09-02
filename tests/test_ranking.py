"""Ranking: ROI > desconto % > lucro US$ > rank do Pokémon; métricas derivadas."""
from comc_scanner.ranking import compute_metrics, sort_key, sort_rows


def test_compute_metrics_matches_spec_example():
    m = compute_metrics(tcg_reference=100.0, comc_price=75.0)
    assert m.discount_pct == 25.0
    assert m.profit_abs == 25.0
    assert round(m.roi_pct, 2) == 33.33


def test_sort_rows_by_roi_then_discount_then_profit_then_rank():
    rows = [
        {"card": "A", "roi_pct": 50.0, "margin_pct": 33.3, "profit_abs": 5.0, "pokemon_rank": 10},
        {"card": "B", "roi_pct": 50.0, "margin_pct": 33.3, "profit_abs": 50.0, "pokemon_rank": 10},
        {"card": "C", "roi_pct": 80.0, "margin_pct": 44.4, "profit_abs": 8.0, "pokemon_rank": 50},
        {"card": "D", "roi_pct": 50.0, "margin_pct": 33.3, "profit_abs": 50.0, "pokemon_rank": 1},
    ]
    assert [r["card"] for r in sort_rows(rows)] == ["C", "D", "B", "A"]


def test_sort_key_tolerates_missing_fields():
    assert sort_key({}) == (0.0, 0.0, 0.0, 9999)
