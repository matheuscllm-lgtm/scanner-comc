"""Offline tests for the Firecrawl transport (no network)."""
from comc_scanner.firecrawl_client import extract_raw_html, is_comc_challenge


def test_challenge_detected_when_no_results_shell():
    assert is_comc_challenge("") is True
    assert is_comc_challenge("<html>Just a moment...</html>") is True
    assert is_comc_challenge("<html><body>nothing useful</body></html>") is True


def test_real_results_shell_is_not_a_challenge():
    # A genuine COMC results page carries the results shell, even with 0 listings.
    assert is_comc_challenge('<div id="cardexplorer">...</div>') is False
    assert is_comc_challenge('<div class="searchResultsStats">Listings 0 of 0</div>') is False


def test_extract_raw_html_reads_v2_envelope():
    env = {"success": True, "data": {"rawHtml": "<html>ok</html>"}}
    assert extract_raw_html(env) == "<html>ok</html>"


def test_extract_raw_html_raises_on_failure_and_empty():
    import pytest

    with pytest.raises(RuntimeError):
        extract_raw_html({"success": False, "error": "blocked"})
    with pytest.raises(RuntimeError):
        extract_raw_html({"data": {"rawHtml": ""}})


def test_default_fetch_mode_is_firecrawl():
    from comc_scanner.config import load_settings

    # No .env override in CI -> default transport is the headless Firecrawl path.
    s = load_settings(env_file=__import__("pathlib").Path("/nonexistent.env"))
    assert s.comc_fetch_mode == "firecrawl"
