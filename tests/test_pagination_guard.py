"""Guarda de paginação da COMC: página repetida = fim do set; teto duro de páginas."""
from pathlib import Path

from comc_scanner import comc_scraper as cs
from comc_scanner.config import Settings

FIX = Path(__file__).parent / "fixtures" / "comc_real_capture.html"


def _scraper(pages, monkeypatch):
    """ComcScraper sem navegador: `_fetch_html` devolve o HTML da lista `pages` por índice
    (a última entrada se repete para p > len), sem delay entre páginas."""
    s = Settings(comc_request_delay_s=0.0)
    sc = cs.ComcScraper(s)
    calls = []

    def fake_fetch(url, solve_timeout_s=60):
        calls.append(url)
        page_no = int(url.rsplit(",p", 1)[1])
        return pages[min(page_no, len(pages)) - 1]

    monkeypatch.setattr(sc, "_fetch_html", fake_fetch)
    monkeypatch.setattr(cs.random, "uniform", lambda a, b: 0.0)
    return sc, calls


def test_repeated_page_ends_the_set(monkeypatch):
    real = FIX.read_text(encoding="utf-8")
    sc, calls = _scraper([real], monkeypatch)  # a COMC devolve a MESMA página para todo p
    pages = list(sc.iter_listings(None, era_path="2001/X"))
    assert len(pages) == 1 and len(pages[0][1]) == 100
    assert len(calls) == 2  # pág. 1 (nova) + pág. 2 (repetida -> para)


def test_hard_page_cap(monkeypatch):
    real = FIX.read_text(encoding="utf-8")
    # cada "página" reescreve os item_ids para parecer nova -> só o teto duro para o loop
    pages = [real.replace("/4341265/", f"/{9000000 + i}/") for i in range(cs.HARD_MAX_PAGES + 5)]
    # todas as outras cartas repetem; só 1 item novo por página já conta como "página nova"
    sc, calls = _scraper(pages, monkeypatch)
    monkeypatch.setattr(cs, "HARD_MAX_PAGES", 5)
    got = list(sc.iter_listings(None, era_path="2001/X"))
    assert len(got) == 5 and len(calls) == 5


def test_closed_browser_context_aborts_the_run_instead_of_empty_sets(monkeypatch):
    """Diagnóstico 2026-09-02: o Chrome headful fechou no meio do grupo 5 e os 6 sets
    restantes "passaram" com 0 listagens (warning por página, sem erro). Contexto fechado
    = ComcAccessError (o run aborta, conta `comc_errors`); outra exceção segue como antes
    (só encerra o set)."""
    import pytest
    from pathlib import Path
    from comc_scanner.comc_scraper import ComcAccessError, ComcScraper
    from comc_scanner.config import load_settings
    sc = ComcScraper(load_settings(env_file=Path("/nonexistent.env")))

    def closed(url):
        raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")
    monkeypatch.setattr(sc, "_fetch_html", closed)
    with pytest.raises(ComcAccessError):
        list(sc.iter_listings(None, era_path="1999/Pokemon_Base_Set_-_Base", max_pages=1))

    def other(url):
        raise RuntimeError("net::ERR_HTTP2_PROTOCOL_ERROR")
    monkeypatch.setattr(sc, "_fetch_html", other)
    assert list(sc.iter_listings(None, era_path="1999/Pokemon_Base_Set_-_Base", max_pages=1)) == []
