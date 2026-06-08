"""Configuration: a tiny .env loader, typed settings, and constants.

Avoids a hard dependency on python-dotenv by parsing .env itself (using
python-dotenv if it happens to be installed).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Pokemon category on TCGplayer / TCGCSV (verified).
POKEMON_CATEGORY_ID = 3
TCGCSV_BASE_URL = "https://tcgcsv.com"

# Project paths.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
RESULTS_DIR = PROJECT_ROOT / "results"
PROGRESS_DIR = CACHE_DIR / "progress"

VALID_ERAS = ("recent", "middle", "vintage", "all")


class RunMode(str, Enum):
    RUN = "run"          # continuous incremental loop
    ONCE = "once"        # single chunk, flush, exit
    REFRESH_PRICES = "refresh-prices"
    DRY_RUN = "dry-run"  # match/report against a local listings fixture (no COMC)


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without clobbering real env vars."""
    try:  # prefer python-dotenv when available
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(path, override=False)
        return
    except Exception:
        pass
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    try:
        return int(float(os.environ.get(key, "").strip() or default))
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    # COMC
    comc_session_cookie: str = ""
    comc_condition_band: str = "EX-NM"
    comc_include_graded: bool = False
    comc_request_delay_s: float = 4.0
    comc_headless: bool = True

    # Scan behaviour
    min_gross_margin: float = 0.20
    top_n: int = 50
    scan_interval_s: int = 3600
    min_match_confidence: float = 0.80
    margin_mode: str = "gross"
    set_allowlist: tuple[str, ...] = ()

    # Eras / chunking
    default_era: str = "all"
    era_vintage_max_year: int = 2010
    era_middle_max_year: int = 2019
    max_run_seconds: int = 0
    max_sets_per_chunk: int = 0
    max_pages_per_set: int = 0

    # TCGCSV / HTTP
    tcgcsv_force_refresh: bool = False
    http_user_agent: str = "comc-scanner/0.1 (+https://github.com/matheuscllm-lgtm/scanner-comc)"

    # Google Sheets (optional)
    gsheets_credentials_json: str = ""
    gsheets_id: str = ""
    gsheets_worksheet: str = "COMC Deals"

    cache_dir: Path = field(default=CACHE_DIR)
    results_dir: Path = field(default=RESULTS_DIR)


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or (PROJECT_ROOT / ".env"))
    allowlist = tuple(
        s.strip() for s in _get("SET_ALLOWLIST").split(",") if s.strip()
    )
    return Settings(
        comc_session_cookie=_get("COMC_SESSION_COOKIE"),
        comc_condition_band=_get("COMC_CONDITION_BAND", "EX-NM"),
        comc_include_graded=_get_bool("COMC_INCLUDE_GRADED", False),
        comc_request_delay_s=_get_float("COMC_REQUEST_DELAY_SECONDS", 4.0),
        comc_headless=_get_bool("COMC_BROWSER_HEADLESS", True),
        min_gross_margin=_get_float("MIN_GROSS_MARGIN", 0.20),
        top_n=_get_int("TOP_N", 50),
        scan_interval_s=_get_int("SCAN_INTERVAL_SECONDS", 3600),
        min_match_confidence=_get_float("MIN_MATCH_CONFIDENCE", 0.80),
        margin_mode=_get("MARGIN_MODE", "gross") or "gross",
        set_allowlist=allowlist,
        default_era=(_get("DEFAULT_ERA", "all") or "all").lower(),
        era_vintage_max_year=_get_int("ERA_VINTAGE_MAX_YEAR", 2010),
        era_middle_max_year=_get_int("ERA_MIDDLE_MAX_YEAR", 2019),
        max_run_seconds=_get_int("MAX_RUN_SECONDS", 0),
        max_sets_per_chunk=_get_int("MAX_SETS_PER_CHUNK", 0),
        max_pages_per_set=_get_int("MAX_PAGES_PER_SET", 0),
        tcgcsv_force_refresh=_get_bool("TCGCSV_FORCE_REFRESH", False),
        http_user_agent=_get("HTTP_USER_AGENT")
        or "comc-scanner/0.1 (+https://github.com/matheuscllm-lgtm/scanner-comc)",
        gsheets_credentials_json=_get("GOOGLE_SHEETS_CREDENTIALS_JSON"),
        gsheets_id=_get("GOOGLE_SHEETS_ID"),
        gsheets_worksheet=_get("GOOGLE_SHEETS_WORKSHEET", "COMC Deals") or "COMC Deals",
    )
