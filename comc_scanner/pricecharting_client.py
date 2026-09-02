"""PriceCharting — referência de preço para SLABS (cartas gradadas).

O TCGplayer (tcgcsv) só tem preço de carta solta; slab PSA 10 / BGS 10 / CGC 10
Pristine precisa de outra fonte. O PriceCharting agrega vendas concluídas por
nota e a página pública de cada carta expõe uma tabela "Full Price Guide" com
colunas ``PSA 10``, ``BGS 10``, ``CGC 10``, ``CGC 10 Pristine``, ``Grade 9.5``…

Scrape leve com urllib (padrão validado no eBay scanner 2026-06-09 e no
CardTrader ``pricecharting_ref.py`` 2026-08-28; HTTP 200 sem bloqueio, verificado
de novo em 2026-09-02). Cache em disco **do dia** (``.cache/pc/<AAAA-MM-DD>``):
o operador exige dados só de hoje — o cache existe para não repetir a mesma
carta dentro de um run, nunca para reaproveitar ontem.

Invariantes: NUNCA inventa preço (busca que não casa nome+número+set, página
sem a coluna da nota, erro de rede → None); guarda de set bidirecional (o
console do PC tem que ser exatamente o set — nada de tiragem japonesa/coreana).
"""
from __future__ import annotations

import gzip
import html as html_mod
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://www.pricecharting.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}
REQUEST_GAP_SECONDS = 2.0  # educação com o site

# Tabela "Full Price Guide" (#full-prices): rótulo → chave normalizada.
FULL_TABLE_GRADE_BY_LABEL = {
    "Ungraded": "RAW",
    "Grade 7": "GRADE 7",
    "Grade 8": "GRADE 8",
    "Grade 9": "PSA 9",
    "Grade 9.5": "GRADE 9.5",
    "PSA 10": "PSA 10",
    "BGS 10": "BGS 10",
    "CGC 10": "CGC 10",
    "SGC 10": "SGC 10",
    "BGS 10 Black": "BGS 10 BLACK",
    "CGC 10 Pristine": "CGC 10 PRISTINE",
}
# Tabela principal (#price_data) usa ids herdados de videogame:
MAIN_TABLE_GRADE_BY_ID = {
    "used_price": "RAW",
    "complete_price": "GRADE 7",
    "new_price": "GRADE 8",
    "graded_price": "PSA 9",
    "box_only_price": "GRADE 9.5",
    "manual_only_price": "PSA 10",
}

_last_request_at = [0.0]
_CODE_PREFIX = re.compile(r"^[A-Za-z0-9]{2,6}:\s*")
_VARIANT_TOKENS = {"holo", "reverse", "1st", "edition", "shadowless", "unlimited", "promo"}


@dataclass(frozen=True, slots=True)
class GradedRef:
    price: float
    grade_key: str   # coluna usada no PC (ex. "PSA 10", "GRADE 9.5")
    url: str


# --- rede + cache do dia ------------------------------------------------------

def today_stamp() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def today_cache_dir(base: Path | str) -> Path:
    return Path(base) / today_stamp()


def fetch_page(url: str, cache_dir: str | None = None) -> str:
    """Baixa uma página com cache em disco (só válido dentro do mesmo dia UTC)."""
    cdir = today_cache_dir(cache_dir or os.path.join(".cache", "pc"))
    cdir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:]
    cache_path = cdir / f"{slug}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    wait = REQUEST_GAP_SECONDS - (time.time() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
    finally:
        _last_request_at[0] = time.time()  # também em falha: não martelar no retry
    body = data.decode("utf-8", errors="replace")
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, cache_path)
    return body


# --- parsers puros -------------------------------------------------------------

def _money(text: str) -> float | None:
    text = text.replace(",", "").replace("$", "").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_grade_prices(body: str) -> dict[str, float]:
    """Preço por nota da página de uma carta ({"PSA 10": 125.65, ...})."""
    prices: dict[str, float] = {}
    m = re.search(r'id="full-prices">.*?<table>(.*?)</table>', body, re.S)
    if m:
        rows = re.findall(
            r"<tr>\s*<td>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*(?:<span[^>]*>)?\s*"
            r"\$?([\d,]+\.\d{2}|N/A)", m.group(1))
        for label, price_text in rows:
            grade = FULL_TABLE_GRADE_BY_LABEL.get(label.strip())
            price = _money(price_text)
            if grade and price is not None:
                prices[grade] = price
    m = re.search(r'<table[^>]*id="price_data".*?</table>', body, re.S)
    if m:
        table = m.group(0)
        for cell_id, grade in MAIN_TABLE_GRADE_BY_ID.items():
            cm = re.search(r'id="%s".{0,300}?\$([\d,]+\.\d{2})' % cell_id, table, re.S)
            if cm:
                price = _money(cm.group(1))
                if price is not None:
                    prices.setdefault(grade, price)
    return prices


def search_card_paths(body: str) -> list[str]:
    """Paths ``/game/...`` da página de busca (hrefs vêm ABSOLUTOS desde 2026-08)."""
    paths = re.findall(
        r'href="(?:https?://www\.pricecharting\.com)?(/game/[^"#?]+)"', body)
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        p = html_mod.unescape(p)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# --- guardas de match (adaptadas do CardTrader pricecharting_ref.py) -----------

def norm_number(number) -> str:
    """'006/165' → '6'; '4/102' → '4'; '95b' → '95'. Sem dígito → ''."""
    if number is None:
        return ""
    head = str(number).strip().split("/", 1)[0]
    digits = re.sub(r"\D", "", head)
    return digits.lstrip("0") or ("0" if digits else "")


def _norm_token(t: str) -> str:
    t = t.lower().strip()
    if t.endswith("'s"):
        t = t[:-2]
    return t.replace("'", "").replace(".", "")


def clean_card_name(card_name) -> str:
    """Nome TCGCSV → nome comparável: tira ' - 006/165', parênteses e 'Lv.NN'."""
    s = str(card_name or "").split(" - ", 1)[0]
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"(?i)\blv\.?\s*\d+\b", " ", s)
    return s.strip()


def _name_tokens(card_name) -> list[str]:
    name = clean_card_name(card_name).replace(".", "")
    return [t for t in (_norm_token(x) for x in re.findall(r"[a-z0-9']+", name.lower())) if t]


def clean_set_name(set_label) -> str:
    """'SV: Scarlet & Violet 151' → 'Scarlet & Violet 151'; 'EX Emerald (em)' → 'EX Emerald'."""
    s = _CODE_PREFIX.sub("", str(set_label or "").strip())
    return s.rsplit(" (", 1)[0].strip() if " (" in s else s


def slug_matches(path: str, card_name, number) -> bool:
    """Slug termina no MESMO número; 1º token = 1º token do nome ('dark-charizard'
    não casa 'Charizard'); tokens do nome == tokens do slug (fora número e
    palavras de variante) — 'charizard-ex-6' não casa 'Charizard' nem vice-versa."""
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    slug = parts[-1].lower()
    num = norm_number(number)
    if not num or not re.search(rf"(?:^|-){re.escape(num)}$", slug):
        return False
    slug_tokens = [_norm_token(t) for t in slug.split("-")]
    slug_tokens = slug_tokens[:-1]  # drop o número final
    tokens = _name_tokens(card_name)
    if not tokens or not slug_tokens or slug_tokens[0] != tokens[0]:
        return False
    core = {t for t in slug_tokens if t and t not in _VARIANT_TOKENS}
    return core == set(tokens)


def console_matches(path: str, set_label) -> bool:
    """Console do path (/game/{console}/{carta}) == tokens do set (sem 'pokemon',
    sem o prefixo 'EX'); bidirecional — 'pokemon-japanese-base-set' NÃO casa 'Base Set'."""
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    console_tokens = {t for t in (re.sub(r"[^a-z0-9]", "", x)
                                  for x in parts[1].lower().split("-")) if t} - {"pokemon"}
    set_tokens = {t for t in re.findall(r"[a-z0-9]+", clean_set_name(set_label).lower())
                  if t != "ex"}
    return bool(set_tokens) and console_tokens == set_tokens


def choose_path(paths: list[str], card_name, number, set_label) -> str | None:
    matches = [p for p in paths if slug_matches(p, card_name, number)
               and console_matches(p, set_label)]
    matches = [p for p in matches if "reverse" not in p.rsplit("/", 1)[-1].lower()]
    if not matches:
        return None
    return min(matches, key=lambda p: len(p.rsplit("/", 1)[-1]))


# --- API usada pelo pipeline ---------------------------------------------------

def graded_reference(card_name, number, set_label, pc_key: str,
                     cache_dir: str | None = None) -> GradedRef | None:
    """Nome+número+set+coluna → GradedRef ou None (nunca inventa)."""
    set_name = clean_set_name(set_label)
    base_name = clean_card_name(card_name)
    num = norm_number(number)
    query = " ".join(p for p in ("pokemon", set_name, base_name, num) if p)
    try:
        body = fetch_page(f"{BASE_URL}/search-products?q={urllib.parse.quote(query)}&type=prices",
                          cache_dir=cache_dir)
        path = choose_path(search_card_paths(body), card_name, number, set_label)
        if not path:
            return None
        url = BASE_URL + path
        prices = parse_grade_prices(fetch_page(url, cache_dir=cache_dir))
    except Exception:  # noqa: BLE001 — rede/parse é best-effort; falha → sem referência
        return None
    price = prices.get(pc_key)
    if price is None or price <= 0:
        return None
    return GradedRef(price=float(price), grade_key=pc_key, url=url)
