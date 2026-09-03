"""Suíte OFFLINE: nenhum teste pode ir à rede. O link [referência] das cartas soltas
consulta o PriceCharting no pipeline; por default os testes recebem None (link cai no
TCGplayer) — quem precisa do link faz seu próprio monkeypatch."""
import pytest


@pytest.fixture(autouse=True)
def _no_network_pricecharting_link(monkeypatch):
    from comc_scanner import pipeline as pl
    monkeypatch.setattr(pl, "product_page_url", lambda *a, **k: None)
    yield
