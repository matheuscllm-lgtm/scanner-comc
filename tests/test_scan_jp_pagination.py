"""Operador 2026-09-02: páginas iniciais só com cartas japonesas (a COMC ordena JP caro
primeiro em sets como 151) NÃO podem interromper a busca — as inglesas das páginas
seguintes têm de ser avaliadas; `--max-english` conta só inglesas válidas."""
from pathlib import Path

from comc_scanner import pipeline as pl
from comc_scanner.config import load_settings
from comc_scanner.models import ComcListing
from comc_scanner.segments import TcgSet

SET = "SV: Scarlet & Violet 151"
JP = "Pokemon Scarlet Violet - 151 sv2a - Base - Japanese"
EN = "Pokemon Scarlet Violet - 151 sv2a - Base"


def _listing(name, price, set_hint, item_id):
    return ComcListing(raw_name=name, price=price, url=f"https://www.comc.com/x/{item_id}",
                       set_hint=set_hint, number_hint="006", condition="NM", item_id=item_id)


PAGES = [
    (1, [_listing("Charizard ex", 900.0, JP, "jp1"), _listing("Charizard ex", 800.0, JP, "jp2"),
         _listing("Mew ex", 700.0, JP, "jp3")]),
    (2, [_listing("Charizard ex", 50.0, EN, "en1"), _listing("Charizard ex", 55.0, EN, "en2")]),
]


class FakeScraper:
    pages_served: list[int] = []

    def __init__(self, settings):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_listings(self, search_term=None, era_path=None, max_pages=0, graded=False):
        if graded:
            return
        for page_no, listings in PAGES:
            FakeScraper.pages_served.append(page_no)
            yield page_no, listings


def _scanner(tmp_path, monkeypatch, **over):
    s = load_settings(env_file=Path("/nonexistent.env"))
    s.results_dir = tmp_path
    s.scan_slabs = False
    for k, v in over.items():
        setattr(s, k, v)
    monkeypatch.setattr(pl, "ComcScraper", FakeScraper)
    ts = TcgSet(group_id=99, name=SET, abbreviation="SV3PT5", year=2023, era="recent")
    monkeypatch.setattr(pl.Scanner, "_targets", lambda self, era: [(ts, "", "slug151")])
    products = [{"productId": 1, "groupId": 99, "name": "Charizard ex - 006/165",
                 "cleanName": "Charizard ex", "url": "https://www.tcgplayer.com/product/1",
                 "extendedData": [{"name": "Number", "value": "006/165"},
                                  {"name": "Rarity", "value": "Double Rare"}]}]
    prices = [{"productId": 1, "subTypeName": "Holofoil", "marketPrice": 100.0, "midPrice": None,
               "lowPrice": None, "highPrice": None, "directLowPrice": None}]
    monkeypatch.setattr(pl.Scanner, "_fetch_set_data", lambda self, ts: (products, prices))
    FakeScraper.pages_served = []
    return pl.Scanner(s)


def test_japanese_first_pages_do_not_stop_the_english_search(tmp_path, monkeypatch):
    sc = _scanner(tmp_path, monkeypatch)
    best = sc.run_scan("recent", "t")
    assert FakeScraper.pages_served == [1, 2]
    assert sc.stats["seen"] == 5 and sc.stats["skip_language"] == 3
    deals = best.qualifying()
    assert {d.listing.item_id for d in deals} == {"en1", "en2"}
    assert all(d.status == "OK" for d in deals)


def test_max_english_counts_only_valid_english_listings(tmp_path, monkeypatch):
    sc = _scanner(tmp_path, monkeypatch, max_english_per_set=1)
    best = sc.run_scan("recent", "t")
    # as 3 japonesas da página 1 não contam; a página 2 é lida e o corte só acontece depois
    assert FakeScraper.pages_served == [1, 2]
    assert len(best.qualifying()) >= 1 and sc.stats["sets_capped_max_english"] == 1


def test_closed_browser_marks_run_aborted_and_counts_it(tmp_path, monkeypatch):
    """Review PR #31: run abortado (browser fechado) tem de ser visível — contador
    próprio `comc_aborted` (≠ bloqueio Cloudflare) e flag `aborted` para o CLI sair ≠ 0."""
    from comc_scanner.comc_scraper import ComcAccessError

    class Dead(FakeScraper):
        def iter_listings(self, search_term=None, era_path=None, max_pages=0, graded=False):
            raise ComcAccessError("browser/contexto fechado")
            yield  # noqa

    sc = _scanner(tmp_path, monkeypatch)
    monkeypatch.setattr(pl, "ComcScraper", Dead)
    sc.run_scan("recent", "t")
    assert sc.aborted is True and sc.stats["comc_aborted"] == 1 and sc.stats["comc_errors"] == 0
