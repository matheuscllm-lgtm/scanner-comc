"""Ranking: ROI bruto > desconto % > spread US$ > rank do Pokémon; métricas derivadas."""
import comc_scanner.ranking as ranking
from comc_scanner.ranking import Metrics, compute_metrics, sort_key, sort_rows


def test_compute_metrics_matches_spec_example():
    m = compute_metrics(tcg_reference=100.0, comc_price=75.0)
    assert m.discount_pct == 25.0
    assert m.spread_abs == 25.0
    assert round(m.roi_pct, 2) == 33.33


def test_metrics_has_no_profit_field():
    """Nomenclatura do operador: spread bruto, nunca "lucro"."""
    assert "spread_abs" in Metrics.__slots__
    assert "profit_abs" not in Metrics.__slots__
    assert "lucro" not in ranking.__doc__.lower()


def test_sort_rows_by_roi_then_discount_then_spread_then_rank():
    rows = [
        {"card": "A", "roi_pct": 50.0, "margin_pct": 33.3, "spread_abs": 5.0, "pokemon_rank": 10},
        {"card": "B", "roi_pct": 50.0, "margin_pct": 33.3, "spread_abs": 50.0, "pokemon_rank": 10},
        {"card": "C", "roi_pct": 80.0, "margin_pct": 44.4, "spread_abs": 8.0, "pokemon_rank": 50},
        {"card": "D", "roi_pct": 50.0, "margin_pct": 33.3, "spread_abs": 50.0, "pokemon_rank": 1},
    ]
    assert [r["card"] for r in sort_rows(rows)] == ["C", "D", "B", "A"]


def test_sort_key_falls_back_to_legacy_profit_abs():
    """JSON antigo (só `profit_abs`): o valor é usado como spread, nunca zerado."""
    old = {"roi_pct": 50.0, "margin_pct": 33.3, "profit_abs": 50.0, "pokemon_rank": 10}
    new = {"roi_pct": 50.0, "margin_pct": 33.3, "spread_abs": 5.0, "pokemon_rank": 10}
    assert sort_key(old) == (-50.0, -33.3, -50.0, 10)
    assert [r["spread_abs"] if "spread_abs" in r else r["profit_abs"]
            for r in sort_rows([new, old])] == [50.0, 5.0]


def test_sort_key_tolerates_missing_fields():
    assert sort_key({}) == (0.0, 0.0, 0.0, 9999)
