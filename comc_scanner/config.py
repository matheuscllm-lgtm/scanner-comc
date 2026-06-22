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
    comc_seller_repo: str = ""  # "" = all repos; "COMC" = RCR only (empty for vintage)
    # NM-only invariant: COMC's g-band facet is ignored on set-path browse, so we filter
    # by the per-listing condition (from the card URL). Keep only these (lowercased) — the
    # NM-range top raw grades. Comparing a played card to the NM TCG price would inflate margin.
    comc_condition_allow: tuple[str, ...] = ("nm", "mint", "m", "ex-nm", "exnm", "near mint")
    # English-only: COMC set-path browse returns every language sub-printing (Japanese,
    # Korean, ...) of a set, but TCGCSV prices are the ENGLISH product — matching a JP/KR
    # card to the EN price is a false signal. Drop listings whose set string names another
    # language. (Set COMC_EXCLUDE_VARIANTS="" to disable.)
    comc_exclude_variants: tuple[str, ...] = (
        "japanese", "korean", "german", "spanish", "french", "italian",
        "chinese", "portuguese", "thai", "indonesian",
    )
    # Browse sort: "sh" (highest price first) surfaces valuable NM cards + big-$ arbitrage
    # on the first pages — better than "sl" once we filter to NM-only (cheapest pages are
    # all played commons that get dropped). "sl" = lowest first.
    comc_sort: str = "sh"
    comc_request_delay_s: float = 4.0
    comc_headless: bool = True
    # Fetch transport: "firecrawl" (headless, no browser/login — clears Cloudflare via
    # stealth proxy) or "playwright" (local Chromium). Default firecrawl.
    comc_fetch_mode: str = "firecrawl"
    firecrawl_api_key: str = ""
    firecrawl_wait_ms: int = 12000
    firecrawl_proxy: str = "stealth"
    # Playwright persistent-profile dir: warm it once headful (`warm` cmd) to clear the
    # Cloudflare challenge, then headless runs reuse its cf_clearance cookie — credit-free.
    comc_profile_dir: str = str(CACHE_DIR / "pw_profile_comc")

    # Scan behaviour
    # 0.30 = the operator's canonical cross-scanner gross-margin threshold (CT/MYP/Liga).
    min_gross_margin: float = 0.30
    # Price floor (USD) on the COMC ask: the canonical "valuable card" floor is R$50 ≈ $10.
    # Cards below it are noise for the operator's import lot model. 0 disables.
    min_comc_price: float = 10.0
    # Value-buy mode: keep only "chase" rarities (anything beyond Common/Uncommon/plain
    # Rare — Illustration Rare, Special Illustration Rare, Ultra Rare, vintage Holo Rare...).
    # These are the classes that hold/appreciate; bulk rarities rarely do.
    chase_only: bool = False
    chase_exclude_rarities: tuple[str, ...] = ("common", "uncommon", "rare")
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
    # Price fallback: when tcgcsv.com is unreachable/empty for a set, reconstruct its
    # prices from TCGdex (the SAME TCGplayer marketPrice, keyed by the same productId).
    # Emergency fallback only (TCGdex is 1 request/card -> slow); on by default, triggers
    # only on a TCGCSV failure. Set TCGDEX_FALLBACK=0 to disable.
    tcgdex_fallback: bool = True
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
        comc_seller_repo=_get("COMC_SELLER_REPO", ""),
        comc_sort=(_get("COMC_SORT", "sh") or "sh").lower(),
        comc_condition_allow=tuple(
            c.strip().lower() for c in _get(
                "COMC_CONDITION_ALLOW", "nm,mint,m,ex-nm,exnm,near mint"
            ).split(",") if c.strip()
        ),
        comc_exclude_variants=tuple(
            v.strip().lower() for v in _get(
                "COMC_EXCLUDE_VARIANTS",
                "japanese,korean,german,spanish,french,italian,chinese,portuguese,thai,indonesian",
            ).split(",") if v.strip()
        ),
        comc_request_delay_s=_get_float("COMC_REQUEST_DELAY_SECONDS", 4.0),
        comc_headless=_get_bool("COMC_BROWSER_HEADLESS", True),
        comc_fetch_mode=(_get("COMC_FETCH_MODE", "firecrawl") or "firecrawl").lower(),
        firecrawl_api_key=_get("FIRECRAWL_API_KEY"),
        firecrawl_wait_ms=_get_int("FIRECRAWL_WAIT_MS", 12000),
        firecrawl_proxy=_get("FIRECRAWL_PROXY", "stealth") or "stealth",
        comc_profile_dir=_get("COMC_PROFILE_DIR", str(CACHE_DIR / "pw_profile_comc"))
        or str(CACHE_DIR / "pw_profile_comc"),
        min_gross_margin=_get_float("MIN_GROSS_MARGIN", 0.30),
        min_comc_price=_get_float("MIN_COMC_PRICE", 10.0),
        chase_only=_get_bool("CHASE_ONLY", False),
        chase_exclude_rarities=tuple(
            r.strip().lower() for r in _get(
                "CHASE_EXCLUDE_RARITIES", "common,uncommon,rare"
            ).split(",") if r.strip()
        ),
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
        tcgdex_fallback=_get_bool("TCGDEX_FALLBACK", True),
        http_user_agent=_get("HTTP_USER_AGENT")
        or "comc-scanner/0.1 (+https://github.com/matheuscllm-lgtm/scanner-comc)",
        gsheets_credentials_json=_get("GOOGLE_SHEETS_CREDENTIALS_JSON"),
        gsheets_id=_get("GOOGLE_SHEETS_ID"),
        gsheets_worksheet=_get("GOOGLE_SHEETS_WORKSHEET", "COMC Deals") or "COMC Deals",
    )
