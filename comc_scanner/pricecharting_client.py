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
    "TAG 10": "TAG 10",
    "ACE 10": "ACE 10",
    "BGS 10 Black": "BGS 10 BLACK",
    "CGC 10 Pristine": "CGC 10 PRISTINE",
}
# Tabelas de VENDAS CONCLUÍDAS (eBay) da página, por balde de nota. Cada linha traz
# data, título do anúncio (com "PSA 9 MINT", "BGS 9.5", "CGC 10 Pristine"…) e preço.
SALES_TABLES = (
    "completed-auctions-graded",       # balde "Grade 9"
    "completed-auctions-box-only",     # balde "Grade 9.5"
    "completed-auctions-manual-only",  # balde "PSA 10" (e demais 10 listados ali)
)
MIN_COMPARABLE_SALES = 3   # mediana só com ≥3 vendas da MESMA certificadora+nota
SALES_WINDOW = 10          # mediana das 10 mais recentes (anti-outlier)
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
    grade_key: str        # coluna usada ("PSA 10", "GRADE 9.5") ou "vendas BGS 9.5 (n=5)"
    url: str
    method: str = "column"   # "column" (coluna exata) | "sales" (mediana de vendas) | "proxy"
    n_sales: int = 0         # vendas comparáveis encontradas (informativo na coluna exata)
    sales_median: float | None = None  # mediana das vendas da mesma nota (sanidade)

    @property
    def is_proxy(self) -> bool:
        return self.method == "proxy"


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


_SALE_ROW_RE = re.compile(
    r'<tr id="([a-z]+)-\d+">(.*?)</tr>', re.S)
_SALE_DATE_RE = re.compile(r'<td class="date">(\d{4}-\d{2}-\d{2})</td>')
_SALE_PRICE_RE = re.compile(r'class="js-price"[^>]*>\s*\$([\d,]+\.\d{2})')


def parse_graded_sales(body: str) -> list[dict]:
    """Vendas concluídas (eBay) das tabelas de nota da página: [{date, price, title, bucket}].
    O título do anúncio é o que identifica certificadora+nota ("PSA 9 MINT", "BGS 9.5")."""
    out: list[dict] = []
    for bucket in SALES_TABLES:
        m = re.search(rf'<div class="{bucket}"[^>]*>(.*?)</table>', body, re.S)
        if not m:
            continue
        for source, row in _SALE_ROW_RE.findall(m.group(1)):
            d = _SALE_DATE_RE.search(row)
            p = _SALE_PRICE_RE.search(row)
            if not d or not p:
                continue
            price = _money(p.group(1))
            if price is None:
                continue
            title = html_mod.unescape(re.sub(r"<[^>]+>", " ", row))
            title = re.sub(r"\s+", " ", title).strip()
            out.append({"date": d.group(1), "price": price, "title": title,
                        "bucket": bucket, "source": source})
    return out


_LANG_NOISE = re.compile(r"\b(japanese|korean|chinese|german|french|italian|spanish)\b", re.I)


def comparable_sales(sales: list[dict], grader: str, value: float, qualifier: str = "") -> list[dict]:
    """Só vendas cujo título nomeia a MESMA certificadora e nota (e 'Pristine' quando
    exigido), em inglês. 'PSA 9' não casa 'PSA 9.5' nem 'BGS 9'."""
    val = f"{value:g}".replace(".", r"\.")
    pat = re.compile(rf"\b{re.escape(grader)}\s*-?\s*{val}(?![\d.])", re.I)
    out = []
    for s in sales:
        t = s["title"]
        if not pat.search(t) or _LANG_NOISE.search(t):
            continue
        if qualifier == "PRISTINE" and "pristine" not in t.lower():
            continue
        if qualifier == "GEM" and "pristine" in t.lower():
            continue
        out.append(s)
    return out


def median_recent(sales: list[dict], n_min: int = MIN_COMPARABLE_SALES,
                  window: int = SALES_WINDOW) -> tuple[float | None, int]:
    """Mediana das `window` vendas mais recentes; menos de `n_min` → (None, n)."""
    if len(sales) < n_min:
        return None, len(sales)
    recent = sorted(sales, key=lambda s: s["date"], reverse=True)[:window]
    prices = sorted(s["price"] for s in recent)
    mid = len(prices) // 2
    med = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2.0
    return round(med, 2), len(prices)


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

def graded_reference(card_name, number, set_label, grade,
                     cache_dir: str | None = None) -> GradedRef | None:
    """Nome+número+set+nota → GradedRef ou None (nunca inventa).

    Política (operador 2026-09-02):
    1. coluna EXATA da certificadora+nota na página (PSA 10, BGS 10, TAG 10, CGC 10
       Pristine…) → referência (`method="column"`); a mediana das vendas da mesma
       nota vai junto como sanidade;
    2. sem coluna exata (BGS/TAG 9.5) → mediana de ≥3 vendas concluídas da MESMA
       certificadora+nota (`method="sales"`) — é referência real, pode ser OK;
    3. sem amostra suficiente → o bucket genérico ("Grade 9.5") entra SÓ para triagem
       (`method="proxy"` → MATCH_REVIEW, nunca oportunidade de compra);
    4. nada → None.
    """
    from .grading import pc_price_key  # local: grading não importa este módulo

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
        page = fetch_page(url, cache_dir=cache_dir)
        prices = parse_grade_prices(page)
        sales = comparable_sales(parse_graded_sales(page), grade.grader, grade.value,
                                 grade.qualifier)
    except Exception:  # noqa: BLE001 — rede/parse é best-effort; falha → sem referência
        return None
    median, n = median_recent(sales)
    pc_key, proxy = pc_price_key(grade)
    column = prices.get(pc_key) if pc_key else None
    if column is not None and column > 0 and not proxy:
        return GradedRef(price=float(column), grade_key=pc_key, url=url, method="column",
                         n_sales=n, sales_median=median)
    if median is not None:
        return GradedRef(price=median, grade_key=f"vendas {grade.key} (n={n})", url=url,
                         method="sales", n_sales=n, sales_median=median)
    if column is not None and column > 0 and proxy:
        return GradedRef(price=float(column), grade_key=pc_key, url=url, method="proxy",
                         n_sales=n, sales_median=None)
    return None
