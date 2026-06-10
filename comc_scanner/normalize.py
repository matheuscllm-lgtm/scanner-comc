"""Normalization helpers for matching COMC listings to TCGCSV products."""
from __future__ import annotations

import re
import unicodedata

try:  # fast path
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore

    def fuzzy_ratio(a: str, b: str) -> float:
        """Token-set similarity in [0, 100]."""
        return float(_rf_fuzz.token_set_ratio(a, b))
except Exception:  # stdlib fallback so matching still works without rapidfuzz
    from difflib import SequenceMatcher

    def fuzzy_ratio(a: str, b: str) -> float:
        ta, tb = sorted(a.split()), sorted(b.split())
        return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio() * 100.0


_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
_SET_CODE_PREFIX = re.compile(r"^[a-z0-9]{2,6}:\s*")  # e.g. "swsh07: ", "sv01: "
_FOIL_WORDS = re.compile(r"\b(reverse holofoil|reverse holo|holofoil|holo|foil)\b")


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _basic(s: str) -> str:
    s = _strip_accents(s or "").lower()
    s = s.replace("&amp;", " and ").replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalize_name(s: str) -> str:
    """Lowercase, de-accent, drop punctuation/foil words; keep suffix tokens (ex/gx/v...)."""
    base = _basic(s)
    base = _FOIL_WORDS.sub(" ", base)
    return _WS.sub(" ", base).strip()


def normalize_set(s: str) -> str:
    """Canonical key for a set name from either COMC or TCGCSV."""
    raw = _strip_accents(s or "").lower()
    raw = _SET_CODE_PREFIX.sub("", raw)  # drop a leading "swsh07:"/"sv01:" code (colon intact)
    return _basic(raw)


def set_contains(a: str, b: str) -> bool:
    """Word-boundary containment for the set-resolution *fallback*.

    True when the shorter of the two normalized strings occurs as whole word(s)
    inside the longer. Requires >= 4 chars so short set codes (``pr``/``em``/``sv``)
    can't match *inside* unrelated words — e.g. ``pr`` in "1st printing" or ``em`` in
    "pokemon" used to make every Topps listing resolve to a random TCG set. Short codes
    still resolve via exact-key equality, which callers check before this fallback.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 4:
        return False
    return re.search(rf"\b{re.escape(shorter)}\b", longer) is not None


def set_aliases(tcg_set_name: str) -> set[str]:
    """All normalized forms a COMC set string might take for this TCG set."""
    raw = _strip_accents(tcg_set_name or "").lower()
    aliases: set[str] = {_basic(raw), normalize_set(tcg_set_name)}
    # Index the leading code on its own, e.g. "swsh07", "sv01".
    m = re.match(r"^([a-z0-9]{2,6}):", raw)
    if m:
        aliases.add(m.group(1))
    return {a for a in aliases if a}


def parse_number(s: str | None) -> str | None:
    """Canonical collector-number key (numerator side), comparable across sources.

    "021/128" -> "21", "21/128" -> "21", "TG12/TG30" -> "tg12",
    "SV107" -> "sv107", "SWSH250" -> "swsh250".
    """
    if not s:
        return None
    token = s.strip().split()[0]
    numerator = token.split("/")[0].strip().lower()
    numerator = re.sub(r"[^a-z0-9]", "", numerator)
    if not numerator:
        return None
    if numerator.isdigit():
        return str(int(numerator))  # strip leading zeros
    # alphanumeric promo / trainer-gallery codes: strip zero padding after the letters
    m = re.match(r"^([a-z]+)0*([0-9]+)$", numerator)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    return numerator


def subtype_hint(listing_name: str, condition: str, rarity: str | None) -> str:
    """Best-guess TCGplayer subtype from a listing's text signals.

    Handles WotC-era print runs (1st Edition / Unlimited) and foiling. When the
    listing gives no signal, returns "Normal" and the index falls back conservatively
    (cheapest available subtype) to avoid overstating margins.
    """
    blob = f"{listing_name} {condition} {rarity or ''}".lower()
    holo = "holo" in blob or "foil" in blob
    if "reverse" in blob:
        return "Reverse Holofoil"
    if "1st" in blob or "first edition" in blob:
        return "1st Edition Holofoil" if holo else "1st Edition"
    if "unlimited" in blob:
        return "Unlimited Holofoil" if holo else "Unlimited"
    if holo:
        return "Holofoil"
    return "Normal"


_GRADERS = ("psa", "bgs", "cgc", "sgc", "tag", "ace", "gma")


def detect_graded(text: str) -> tuple[bool, str | None]:
    """Return (is_graded, grader) from a condition/title string."""
    low = (text or "").lower()
    for g in _GRADERS:
        if re.search(rf"\b{g}\b", low):
            return True, g.upper()
    return False, None
