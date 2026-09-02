"""Configuration: a tiny .env loader, typed settings, and constants.

Avoids a hard dependency on python-dotenv by parsing .env itself (using
python-dotenv if it happens to be installed).

Parâmetros de negócio (editáveis por env / CLI, nunca hardcoded na lógica):
- ``MIN_DISCOUNT_PERCENT`` (inteiro, default 20): desconto mínimo da COMC sobre a
  referência, ``(ref − comc) / ref``. 20 = a carta na COMC está ≥20% abaixo.
- ``MIN_COMC_PRICE`` (US$, default 10): piso de relevância (~R$50).
- ``GRADED_ALLOW``: notas de slab aceitas (ver ``grading.DEFAULT_GRADED_ALLOW``).
- Lista de Pokémon icônicos: ``comc_scanner/iconic_pokemon.csv``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .grading import DEFAULT_GRADED_ALLOW

# Pokemon category on TCGplayer / TCGCSV (verified).
POKEMON_CATEGORY_ID = 3
TCGCSV_BASE_URL = "https://tcgcsv.com"

# Project paths.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
RESULTS_DIR = PROJECT_ROOT / "results"

VALID_ERAS = ("recent", "middle", "vintage", "all")

MIN_DISCOUNT_PERCENT = 20  # default canônico deste scanner (spec 2026-09-02)


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


def clean_secret(value: str | None) -> str:
    """Sanitize a secret read from env/.env/CI secret (BOM + zero-width + spaces).
    `str.strip()` does NOT remove a BOM, so we strip it explicitly. Returns "" if empty."""
    if value is None:
        return ""
    return value.replace("﻿", "").replace("​", "").strip()


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


def _csv(key: str, default: str) -> tuple[str, ...]:
    return tuple(v.strip().lower() for v in _get(key, default).split(",") if v.strip())


@dataclass(slots=True)
class Settings:
    # --- COMC ---
    comc_session_cookie: str = ""
    comc_condition_band: str = "EX-NM"   # facet g<band> (só na passada raw; ignorado no set-path)
    comc_seller_repo: str = ""           # "" = all repos; "COMC" = RCR only (empty for vintage)
    # Condição aceita por ERA (match EXATO contra a lista; nunca substring). COMC's g-band
    # facet is ignored on set-path browse, so we filter by the per-listing condition.
    # Moderno (recent/middle) = só "NM"; vintage WotC = "NM" ou "EX-NM" (a COMC gradua
    # quase todo raw vintage como EX-NM — decisão do operador 2026-09-02).
    comc_condition_allow: tuple[str, ...] = ("nm",)
    comc_condition_allow_vintage: tuple[str, ...] = ("nm", "ex-nm")
    # English-only: drop listings whose set string names another language.
    comc_exclude_variants: tuple[str, ...] = (
        "japanese", "korean", "german", "spanish", "french", "italian",
        "chinese", "portuguese", "thai", "indonesian",
    )
    comc_sort: str = "sh"                # highest price first
    comc_request_delay_s: float = 4.0
    comc_headless: bool = False          # COMC's Cloudflare only clears HEADFUL (real Chrome)
    comc_profile_dir: str = str(CACHE_DIR / "pw_profile_comc")

    # --- Scan scope ---
    scan_raw: bool = True                # cartas soltas NM
    scan_slabs: bool = True              # cartas gradadas (PSA/BGS/TAG/CGC Pristine 10)
    graded_allow: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_GRADED_ALLOW))
    iconic_only: bool = True             # só Pokémon da lista icônica (--all-pokemon desliga)
    set_allowlist: tuple[str, ...] = ()

    # --- Scan behaviour ---
    min_discount_percent: int = MIN_DISCOUNT_PERCENT
    min_comc_price: float = 10.0         # piso US$ (R$50 "carta valiosa"); 0 desliga
    max_comc_price: float = 0.0          # teto US$ por carta (orçamento); 0 desliga
    max_english_per_set: int = 0         # para o set após N listagens INGLESAS válidas; 0 = todas
    chase_only: bool = False
    chase_exclude_rarities: tuple[str, ...] = ("common", "uncommon", "rare")
    top_n: int = 200
    scan_interval_s: int = 3600          # flush parcial (~hora)
    min_match_confidence: float = 0.80   # abaixo disto vai para o balde low-confidence
    trust_confidence: float = 0.90       # abaixo disto = MATCH_REVIEW

    # --- Eras ---
    default_era: str = "all"
    era_vintage_max_year: int = 2010
    era_middle_max_year: int = 2019
    max_run_seconds: int = 0
    max_pages_per_set: int = 0

    # --- Reference prices ---
    tcgcsv_force_refresh: bool = True    # sempre baixa o snapshot do dia (nunca reaproveita ontem)
    tcgdex_fallback: bool = True
    pc_cache_dir: str = str(CACHE_DIR / "pc")
    http_user_agent: str = "comc-scanner/0.3 (+https://github.com/matheuscllm-lgtm/scanner-comc)"

    cache_dir: Path = field(default=CACHE_DIR)
    results_dir: Path = field(default=RESULTS_DIR)

    @property
    def min_gross_margin(self) -> float:
        """Desconto mínimo como fração (20 → 0.20), usado nas comparações internas."""
        return self.min_discount_percent / 100.0


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or (PROJECT_ROOT / ".env"))
    graded_allow = _get("GRADED_ALLOW")
    return Settings(
        comc_session_cookie=_get("COMC_SESSION_COOKIE"),
        comc_condition_band=_get("COMC_CONDITION_BAND", "EX-NM"),
        comc_seller_repo=_get("COMC_SELLER_REPO", ""),
        comc_condition_allow=_csv("COMC_CONDITION_ALLOW", "nm"),
        comc_condition_allow_vintage=_csv("COMC_CONDITION_ALLOW_VINTAGE", "nm,ex-nm"),
        comc_exclude_variants=_csv(
            "COMC_EXCLUDE_VARIANTS",
            "japanese,korean,german,spanish,french,italian,chinese,portuguese,thai,indonesian",
        ),
        comc_sort=(_get("COMC_SORT", "sh") or "sh").lower(),
        comc_request_delay_s=_get_float("COMC_REQUEST_DELAY_SECONDS", 4.0),
        comc_headless=_get_bool("COMC_BROWSER_HEADLESS", False),
        comc_profile_dir=_get("COMC_PROFILE_DIR") or str(CACHE_DIR / "pw_profile_comc"),
        scan_raw=_get_bool("SCAN_RAW", True),
        scan_slabs=_get_bool("SCAN_SLABS", True),
        graded_allow=frozenset(g.strip().upper() for g in graded_allow.split(",") if g.strip())
        if graded_allow else frozenset(DEFAULT_GRADED_ALLOW),
        iconic_only=_get_bool("ICONIC_ONLY", True),
        set_allowlist=tuple(s.strip() for s in _get("SET_ALLOWLIST").split(",") if s.strip()),
        min_discount_percent=_get_int("MIN_DISCOUNT_PERCENT", MIN_DISCOUNT_PERCENT),
        min_comc_price=_get_float("MIN_COMC_PRICE", 10.0),
        max_comc_price=_get_float("MAX_COMC_PRICE", 0.0),
        max_english_per_set=_get_int("MAX_ENGLISH_PER_SET", 0),
        chase_only=_get_bool("CHASE_ONLY", False),
        chase_exclude_rarities=_csv("CHASE_EXCLUDE_RARITIES", "common,uncommon,rare"),
        top_n=_get_int("TOP_N", 200),
        scan_interval_s=_get_int("SCAN_INTERVAL_SECONDS", 3600),
        min_match_confidence=_get_float("MIN_MATCH_CONFIDENCE", 0.80),
        trust_confidence=_get_float("TRUST_CONFIDENCE", 0.90),
        default_era=(_get("DEFAULT_ERA", "all") or "all").lower(),
        era_vintage_max_year=_get_int("ERA_VINTAGE_MAX_YEAR", 2010),
        era_middle_max_year=_get_int("ERA_MIDDLE_MAX_YEAR", 2019),
        max_run_seconds=_get_int("MAX_RUN_SECONDS", 0),
        max_pages_per_set=_get_int("MAX_PAGES_PER_SET", 0),
        tcgcsv_force_refresh=_get_bool("TCGCSV_FORCE_REFRESH", True),
        tcgdex_fallback=_get_bool("TCGDEX_FALLBACK", True),
        pc_cache_dir=_get("PC_CACHE_DIR") or str(CACHE_DIR / "pc"),
        http_user_agent=_get("HTTP_USER_AGENT")
        or "comc-scanner/0.3 (+https://github.com/matheuscllm-lgtm/scanner-comc)",
    )
