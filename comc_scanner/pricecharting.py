"""Referência PriceCharting — mediana das VENDAS REAIS (sold listings) ungraded.

Segunda referência de preço do modo `--iconic` (ao lado do market price do
TCGplayer via tcgcsv). Metodologia aprovada pelo operador em 2026-08-28 no
card-trader-scanner (`pricecharting_ref.py`, de onde este módulo é portado —
os repos da frota não compartilham código): página pública da carta no
PriceCharting → MEDIANA das N vendas ungraded mais recentes (mediana, não
média — anti-outlier). A referência de vendas concluídas é mais honesta que um
market price fino/inflado por variante errada.

Invariantes da frota:
  - NUNCA inventa preço: busca sem resultado que case nome+número+set (guardas
    de slug e de console), página sem vendas, erro de rede → None. A entrega
    mostra "—" e marca a linha "sem PC".
  - Best-effort e sinal de sanidade: falha do PriceCharting nunca derruba o
    scan; a linha continua com a referência TCGplayer.

Scrape leve com urllib + cache 24h em disco (`.cache/pricecharting/`), 2 s entre
requests (validado HTTP 200 da nuvem em 2026-09-02).
"""
from __future__ import annotations

import gzip
import html as _html
import os
import re
import statistics
import time
import urllib.parse
import urllib.request

from .config import CACHE_DIR

BASE_URL = "https://www.pricecharting.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}
CACHE_TTL_SECONDS = 24 * 3600
REQUEST_GAP_SECONDS = 2.0
DEFAULT_CACHE_DIR = str(CACHE_DIR / "pricecharting")
MEDIAN_WINDOW = 10  # mediana das 10 vendas mais recentes

# Tokens de VARIANTE que um slug PC pode carregar além do nome base + número.
# Usados na guarda de slug: "charizard-1st-edition-4" só casa uma oferta 1st
# Edition; "lugia-reverse-holo-9" só casa uma oferta reverse.
_VARIANT_TOKENS = {"1st", "edition", "reverse", "holo", "holofoil", "foil",
                   "shadowless", "unlimited"}
_SET_CODE_PREFIX = re.compile(r"^[A-Za-z0-9]{2,6}:\s*")  # "SV09: ", "SWSH07: "
_NAME_NUMBER_SUFFIX = re.compile(r"\s+-\s+[A-Za-z]*\d+[A-Za-z]?(?:/[A-Za-z]*\d+)?\s*$")

_last_request_at = [0.0]


# --- HTTP + cache -----------------------------------------------------------

def fetch_page(url: str, cache_dir: str | None = None) -> str:
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:]
    cache_path = os.path.join(cache_dir, slug + ".html")
    if os.path.exists(cache_path):
        if time.time() - os.path.getmtime(cache_path) < CACHE_TTL_SECONDS:
            with open(cache_path, encoding="utf-8") as f:
                return f.read()

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
        _last_request_at[0] = time.time()  # também em falha: mantém o gap
    body = data.decode("utf-8", errors="replace")
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp_path, cache_path)  # escrita atômica
    return body


# --- parsing ----------------------------------------------------------------

def parse_sold_listings(body: str) -> list[dict]:
    """Vendas UNGRADED da página (`<div class="completed-auctions-used">`; as
    abas graded usam outras classes e ficam fora)."""
    m = re.search(r'<div class="completed-auctions-used"[^>]*>(.*?)</table>', body, re.S)
    if not m:
        return []
    rows = re.findall(
        r'<tr id="([a-z]+)-\d+">\s*'
        r'<td class="date">(\d{4}-\d{2}-\d{2})</td>'
        r'.*?<span class="js-price"[^>]*>\s*\$([\d,]+\.\d{2})',
        m.group(1), re.S)
    sales = []
    for source, date, price_text in rows:
        try:
            sales.append({"date": date, "source": source,
                          "price": float(price_text.replace(",", ""))})
        except ValueError:
            continue
    return sales


def median_recent_sold(sales: list[dict], n: int = MEDIAN_WINDOW):
    """Mediana das `n` vendas mais recentes. Vazio → (None, 0) — nunca inventa."""
    if not sales:
        return None, 0
    recent = sorted(sales, key=lambda s: s["date"], reverse=True)[:n]
    prices = [s["price"] for s in recent]
    return statistics.median(prices), len(prices)


# --- normalização de nome/número/set ----------------------------------------

def norm_number(number) -> str:
    """'004/102' → '4'; '199/165' → '199'; 'TG12/TG30' → '12'; sem dígito → ''."""
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


def split_product_name(product_name) -> tuple[str, str]:
    """Nome tcgcsv → (nome base, texto entre parênteses).

    'Charizard ex - 199/165' → ('Charizard ex', '');
    'Charizard (Black Dot Error)' → ('Charizard', 'Black Dot Error')."""
    s = _NAME_NUMBER_SUFFIX.sub("", str(product_name or "")).strip()
    parens = " ".join(re.findall(r"\((.*?)\)", s))
    base = re.sub(r"\(.*?\)", "", s).strip()
    return base, parens


def _tokens(text: str) -> list[str]:
    return [t for t in (_norm_token(x) for x in re.findall(r"[a-z0-9']+", text.lower())) if t]


def slug_matches(path: str, product_name, number) -> bool:
    """Guarda anti-match-errado por carta:

    1. o slug termina no MESMO número da carta;
    2. o PRIMEIRO token do slug é o primeiro token do nome ('dark-charizard-4'
       não casa 'Charizard');
    3. TODOS os tokens do nome base aparecem no slug ou no console
       ('charizard-6' não casa 'Charizard ex');
    4. tokens EXTRAS do slug só podem ser de variante (1st/reverse/...) ou do
       parêntese do produto — e um produto COM parêntese exige que ao menos um
       token dele esteja no slug ('Charizard (Black Dot Error)' nunca casa a
       página base 'charizard-4')."""
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    console_tokens = {_norm_token(t) for t in _html.unescape(parts[1]).split("-")}
    slug = parts[-1].lower()
    num = norm_number(number)
    if not num or not re.search(rf"(?:^|-){re.escape(num)}$", slug):
        return False
    slug_tokens = [_norm_token(t) for t in slug.split("-") if t]
    base, parens = split_product_name(product_name)
    base_tokens, paren_tokens = _tokens(base), set(_tokens(parens))
    if not base_tokens or not slug_tokens or slug_tokens[0] != base_tokens[0]:
        return False
    pool = set(slug_tokens) | console_tokens
    if not all(t in pool for t in base_tokens):
        return False
    extras = set(slug_tokens[:-1]) - set(base_tokens)
    if not extras <= (_VARIANT_TOKENS | paren_tokens):
        return False
    if paren_tokens and not (paren_tokens & extras):
        return False
    return True


def set_tokens(set_name) -> set[str]:
    """'SV: Scarlet & Violet 151' → {'scarlet','violet','151'}; 'EX Emerald' →
    {'emerald'} (o PC não usa o prefixo EX)."""
    s = _SET_CODE_PREFIX.sub("", str(set_name or ""))
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t != "ex"}


def console_matches(path: str, set_name) -> bool:
    """Guarda de SET: o console do path (/game/{console}/{carta}) tem que ter
    EXATAMENTE os tokens do nome do set (bidirecional: 'pokemon-japanese-
    aquapolis' não casa 'Aquapolis' — a tiragem japonesa corromperia o sinal)."""
    parts = path.strip("/").split("/")
    if len(parts) < 3:
        return False
    console = _html.unescape(parts[1]).lower()
    console_tokens = {t for t in (re.sub(r"[^a-z0-9]", "", x) for x in console.split("-"))
                      if t} - {"pokemon"}
    wanted = set_tokens(set_name)
    return bool(wanted) and console_tokens == wanted


def search_card_urls(query: str, cache_dir: str | None = None) -> list[str]:
    """Busca no PriceCharting → paths /game/ dos resultados, na ordem, sem
    duplicata (a carta certa pode estar longe da 1ª posição)."""
    url = f"{BASE_URL}/search-products?q={urllib.parse.quote(query)}&type=prices"
    body = fetch_page(url, cache_dir=cache_dir)
    paths = re.findall(r'href="(?:https?://www\.pricecharting\.com)?(/game/[^"#?]+)"', body)
    seen, out = set(), []
    for p in paths:
        p = _html.unescape(p)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def pick_path(paths: list[str], product_name, number, set_name, sub_type=None) -> str | None:
    """Escolhe o path da VARIANTE certa entre os resultados que passam nas
    guardas. Oferta reverse → só página reverse; 1st Edition → só página
    1st-edition; demais → só páginas sem marcador de variante; empate → slug
    mais curto (versão base). Nada casa → None."""
    matches = [p for p in paths
               if slug_matches(p, product_name, number) and console_matches(p, set_name)]
    sub = str(sub_type or "").lower()
    want_reverse, want_first = "reverse" in sub, "1st" in sub

    def _slug(p: str) -> str:
        return p.rsplit("/", 1)[-1].lower()

    if want_reverse:
        matches = [p for p in matches if "reverse" in _slug(p)]
    elif want_first:
        matches = [p for p in matches if "1st-edition" in _slug(p)]
    else:
        matches = [p for p in matches
                   if not any(v in _slug(p) for v in ("reverse", "1st-edition", "shadowless"))]
    return min(matches, key=lambda p: len(_slug(p))) if matches else None


def resolve_pc_ref(product_name, number, set_name, sub_type=None,
                   cache_dir: str | None = None) -> dict | None:
    """Nome+número+set(+variante) → {'median','n_sales','url'} ou None.

    Busca "pokemon <set> <nome base> <número>", escolhe o path pela guarda
    (`pick_path`) e tira a mediana das vendas ungraded recentes. Qualquer falha
    (rede, parse, sem match, sem vendas) → None: nunca inventa."""
    base, _ = split_product_name(product_name)
    set_words = " ".join(_SET_CODE_PREFIX.sub("", str(set_name or "")).replace("&", " ").split())
    query = " ".join(p for p in ("pokemon", set_words, base, norm_number(number)) if p)
    try:
        path = pick_path(search_card_urls(query, cache_dir=cache_dir),
                         product_name, number, set_name, sub_type)
        if not path:
            return None
        page = fetch_page(BASE_URL + path, cache_dir=cache_dir)
    except Exception:  # noqa: BLE001 — best-effort; falha → "—"
        return None
    median, n_sales = median_recent_sold(parse_sold_listings(page))
    if median is None:
        return None
    return {"median": median, "n_sales": n_sales, "url": BASE_URL + path}
