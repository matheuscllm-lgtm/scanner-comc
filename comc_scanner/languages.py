"""Canonical language handling for COMC listings and user scan filters."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

LANGUAGE_LABELS = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "th": "Thai",
    "id": "Indonesian",
}

_ALIASES = {
    "en": "en", "eng": "en", "english": "en", "ingles": "en",
    "ja": "ja", "jp": "ja", "jpn": "ja", "japanese": "ja", "japones": "ja",
    "ko": "ko", "kr": "ko", "kor": "ko", "korean": "ko", "coreano": "ko",
    "zh": "zh", "cn": "zh", "zho": "zh", "chinese": "zh", "chines": "zh",
    "simplified chinese": "zh", "traditional chinese": "zh",
    "de": "de", "ger": "de", "german": "de", "alemao": "de",
    "es": "es", "spa": "es", "spanish": "es", "espanhol": "es",
    "fr": "fr", "fre": "fr", "french": "fr", "frances": "fr",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt", "portugues": "pt",
    "th": "th", "tha": "th", "thai": "th", "tailandes": "th",
    "id": "id", "ind": "id", "indonesian": "id", "indonesio": "id",
}

_MARKERS = (
    ("zh", re.compile(r"\b(?:simplified|traditional)?\s*chinese\b|\bchin(?:ese|es)\b", re.I)),
    ("ja", re.compile(r"\b(?:japanese|japan|japones)\b", re.I)),
    ("ko", re.compile(r"\b(?:korean|korea|coreano)\b", re.I)),
    ("de", re.compile(r"\b(?:german|alemao)\b", re.I)),
    ("es", re.compile(r"\b(?:spanish|espanhol)\b", re.I)),
    ("fr", re.compile(r"\b(?:french|frances)\b", re.I)),
    ("it", re.compile(r"\b(?:italian|italiano)\b", re.I)),
    ("pt", re.compile(r"\b(?:portuguese|portugues)\b", re.I)),
    ("th", re.compile(r"\b(?:thai|tailandes)\b", re.I)),
    ("id", re.compile(r"\b(?:indonesian|indonesio)\b", re.I)),
)


def _plain(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "")
                   if not unicodedata.combining(c)).strip().lower()


def normalize_language(value: str) -> str:
    """Return ISO-like scanner code or raise ValueError for an unknown language."""
    key = _plain(value).replace("_", " ").replace("-", " ")
    try:
        return _ALIASES[key]
    except KeyError as exc:
        supported = ", ".join(LANGUAGE_LABELS)
        raise ValueError(f"idioma desconhecido {value!r}; use: {supported}") from exc


def parse_languages(value: str) -> frozenset[str]:
    values = [part.strip() for part in (value or "").split(",") if part.strip()]
    if not values:
        raise ValueError("informe pelo menos um idioma")
    return frozenset(normalize_language(part) for part in values)


def detect_language(*texts: str) -> str:
    """Infer language from explicit COMC markers; unmarked listings are English."""
    blob = _plain(unquote(" ".join(text or "" for text in texts))).replace("_", " ")
    for code, pattern in _MARKERS:
        if pattern.search(blob):
            return code
    return "en"


def language_label(code: str) -> str:
    return LANGUAGE_LABELS.get(code, code or "Unknown")
