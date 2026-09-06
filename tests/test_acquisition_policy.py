"""Acquisition rules: no invented condition prices or silently truncated delivery."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from comc_scanner import __main__ as cli
from comc_scanner.config import Settings
from comc_scanner.models import ComcListing
from comc_scanner.pipeline import Scanner, KIND_RAW, BestDeals
from comc_scanner.reporter import Reporter, classify_row
from comc_scanner.tcg_index import TcgIndex
from comc_summary import build_markdown


def test_all_eras_reaches_scanner_without_vintage_substitution():
    with patch.object(cli, 'Scanner') as factory:
        factory.return_value.aborted = False
        assert cli.main(['scan', '--era', 'all']) == 0
        factory.return_value.run_scan.assert_called_once_with('all', label='all')


def test_all_pokemon_default_and_iconic_opt_in():
    s = Settings()
    assert not s.iconic_only and not s.chase_only and s.scan_raw and s.scan_slabs
    cli._apply_overrides(s, cli.build_parser().parse_args(['scan', '--iconic-only']))
    assert s.iconic_only


def test_exnm_never_calls_matching_or_price_sources_and_is_delivered(tmp_path):
    s = Settings(results_dir=tmp_path, comc_condition_allow_vintage=('nm','ex-nm'))
    scanner = Scanner(s)
    listing = ComcListing('Charizard', 50, 'https://www.comc.com/example', condition='EX-NM')
    with patch('comc_scanner.pipeline.match', side_effect=AssertionError('EX-NM must not price as NM')):
        assert scanner.process_listing(listing, TcgIndex(), None, KIND_RAW, era='vintage') is None
    scanner.reporter.flush([], 'test', stats=scanner.stats)
    payload = json.loads((tmp_path/'comc_deals_test_latest.json').read_text())
    row = payload['unpriced_review'][0]
    assert row['tcg_reference'] is None and row['margin_pct'] is None
    assert not row['ref_url'] and not row['tcg_url']
    assert classify_row(row)[0] == 'MATCH_REVIEW'
    md = build_markdown(payload)
    assert 'Charizard' in md and 'EX-NM' in md and '[oferta]' in md
    assert 'Sem referência equivalente' in md


def test_complete_delivery_keeps_more_than_200_rows_and_reviews(tmp_path):
    rows = [dict(card_number=f'Card {n}', comc_price=50, tcg_reference=100,
                 margin_pct=50, roi_pct=100, spread_abs=50, confidence=1,
                 listing_type='Raw NM', condition='NM', price_field='market') for n in range(251)]
    deals = [SimpleNamespace(as_row=lambda row=row:row) for row in rows]
    reporter = Reporter(Settings(results_dir=tmp_path))
    reporter.add_unpriced(ComcListing('Unknown',50,'https://www.comc.com/unknown'), 'sem match')
    reporter.flush(deals,'test')
    payload=json.loads((tmp_path/'comc_deals_test_latest.json').read_text())
    assert payload['count']==251 and len(payload['unpriced_review'])==1
    assert 'Card 250' in build_markdown(payload)
    best=BestDeals(0)
    best.low={n:deals[n] for n in range(251)}
    assert len(best.low_conf())==251


def test_positive_cap_is_explicit_and_does_not_hide_unpriced_review(tmp_path):
    reporter=Reporter(Settings(results_dir=tmp_path,top_n=1))
    reporter.add_unpriced(ComcListing('A',50,'https://www.comc.com/a'),'sem match')
    reporter.add_unpriced(ComcListing('B',50,'https://www.comc.com/b'),'sem match')
    reporter.flush([],'test')
    payload=json.loads((tmp_path/'comc_deals_test_latest.json').read_text())
    assert len(payload['unpriced_review'])==2


def test_coverage_and_acquisition_limitations_are_visible():
    payload={'deals':[],'coverage':{'all':{'without_validated_path':['Unmapped Set']}}}
    text=build_markdown(payload)
    assert 'Unmapped Set' in text and 'custos' in text and 'População' in text


def test_legacy_exnm_price_cannot_be_classified_ok():
    status,reasons=classify_row(dict(condition='EX-NM',listing_type='Raw EX-NM',
                                    ref_source='tcgplayer',price_field='market',confidence=1))
    assert status=='MATCH_REVIEW' and 'EX-NM≠NM' in reasons
