"""Data models shared across the scanner."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ranking import UNRANKED, compute_metrics

STATUS_OK = "OK"
STATUS_REVIEW = "MATCH_REVIEW"

# Chave da nota (como gravada em ComcListing.grade) → rótulo de entrega.
_GRADE_QUALIFIER_LABELS = (
    ("BGS 10 BLACK", "BGS 10 Black Label"),
    ("CGC 10 PRISTINE", "CGC 10 Pristine"),
    ("CGC 10 GEM", "CGC 10 Gem Mint"),
)


def grade_label(grade_key: str) -> str:
    """Rótulo legível da chave da nota: "BGS 10 BLACK" → "BGS 10 Black Label",
    "CGC 10 PRISTINE" → "CGC 10 Pristine", "CGC 10 GEM" → "CGC 10 Gem Mint";
    demais chaves ("PSA 10", "TAG 9.5", "BGS 10") ficam como estão."""
    key = (grade_key or "").strip()
    for raw, label in _GRADE_QUALIFIER_LABELS:
        if key.upper() == raw:
            return label
    return key


@dataclass(slots=True)
class TcgProduct:
    product_id: int
    group_id: int
    set_name: str
    name: str
    clean_name: str
    number: str | None = None
    rarity: str | None = None
    card_type: str | None = None
    url: str = ""
    image_url: str = ""


@dataclass(slots=True)
class TcgPrice:
    product_id: int
    sub_type: str
    low: float | None = None
    mid: float | None = None
    high: float | None = None
    market: float | None = None
    direct_low: float | None = None


@dataclass(slots=True)
class TcgCard:
    """A product joined with its per-subtype prices."""
    product: TcgProduct
    subtypes: dict[str, TcgPrice] = field(default_factory=dict)


@dataclass(slots=True)
class ComcListing:
    raw_name: str
    price: float
    url: str
    set_hint: str | None = None
    number_hint: str | None = None
    condition: str = ""
    graded: bool = False
    grader: str | None = None      # PSA / CGC / BGS / TAG ... (slab)
    grade: str | None = None       # chave da nota, ex. "PSA 10", "CGC 10 PRISTINE" (slab)
    grade_label: str = ""          # texto do título da COMC, ex. "PSA 10 GEM MT"
    quantity: int = 1
    seller: str | None = None
    image_url: str | None = None
    item_id: str | None = None
    description: str = ""  # full COMC description line (set + printing/edition signal)


@dataclass(slots=True)
class Deal:
    listing: ComcListing
    product: TcgProduct
    price: TcgPrice
    tcg_reference: float          # preço de referência usado (raw NM: TCGplayer; slab/LP: mediana PC)
    price_field_used: str         # raw NM: market/mid/low; slab/LP: label da SalesRef ("vendas PSA 9 (n=5, …)")
    sub_type_used: str
    margin: float                 # desconto como fração: (ref − comc)/ref
    match_confidence: float
    match_reason: str
    era: str = ""
    pokemon: str = ""             # Pokémon icônico casado (lista do operador)
    pokemon_rank: int = UNRANKED
    # "tcgplayer" (raw NM/EX-NM) | "pricecharting-sales" (slab: mediana de vendas da
    # mesma certificadora+nota+variante) | "pricecharting-sales-lp" (raw LP: mediana de
    # vendas LP). Valores antigos ("pricecharting" = coluna, "pricecharting-proxy") só
    # aparecem em JSON gravado antes da PR A — a entrega os lê e marca como antigos.
    ref_source: str = "tcgplayer"
    ref_url: str = ""             # página onde conferir o preço de referência
    ref_sales_median: float | None = None  # mediana das vendas comparáveis (= ref, slabs/LP)
    ref_n_sales: int = 0          # nº de vendas comparáveis na janela usada
    ref_liquidity: str = ""       # "ok" (≥3 em 180d) | "low" (≥3 só em 365d) | "thin" (1–2)
    ref_window_days: int = 0      # janela da referência: 180 | 365 (0 = não se aplica)
    ref_column_price: float | None = None  # coluna exata do PC (só informativa/sanidade)
    status: str = STATUS_OK       # OK | MATCH_REVIEW (match/preço não confiável o bastante)
    review_reasons: tuple[str, ...] = ()

    @property
    def listing_type(self) -> str:
        """'Raw NM' / 'Raw EX-NM' / 'Raw LP' ou o rótulo da nota do slab
        ('PSA 10', 'CGC 10 Pristine', 'CGC 10 Gem Mint', 'BGS 10 Black Label')."""
        if self.listing.graded and self.listing.grade:
            return grade_label(self.listing.grade)
        return f"Raw {self.listing.condition or ''}".strip()

    def as_row(self) -> dict[str, object]:
        """Flat dict for CSV/JSON/markdown output."""
        m = compute_metrics(self.tcg_reference, self.listing.price)
        return {
            "margin_pct": m.discount_pct,
            "roi_pct": m.roi_pct,
            "comc_price": round(self.listing.price, 2),
            "tcg_reference": round(self.tcg_reference, 2),
            "spread_abs": m.spread_abs,
            "pokemon": self.pokemon,
            "pokemon_rank": self.pokemon_rank,
            "card": self.product.name,
            "number": self.product.number or "",
            # Pokémon name followed by its collector number, e.g. "Pikachu 173/165".
            # Some TCGCSV product names already embed the number — avoid doubling it.
            "card_number": (
                self.product.name if (self.product.number or "") in self.product.name
                else f"{self.product.name} {self.product.number or ''}".strip()
            ),
            "set": self.product.set_name,
            "rarity": self.product.rarity or "",
            "listing_type": self.listing_type,
            "condition": self.listing.condition,
            "sub_type": self.sub_type_used,
            "price_field": self.price_field_used,
            "ref_source": self.ref_source,
            "ref_sales_median": self.ref_sales_median,
            "ref_n_sales": self.ref_n_sales,
            "ref_liquidity": self.ref_liquidity,
            "ref_window_days": self.ref_window_days,
            "ref_column_price": self.ref_column_price,
            "era": self.era,
            "confidence": round(self.match_confidence, 2),
            "match_reason": self.match_reason,
            "status": self.status,
            "review_reasons": " · ".join(self.review_reasons),
            "quantity": self.listing.quantity,
            "seller": self.listing.seller,
            "image_url": self.listing.image_url,
            "acquisition_review": "fotos/condição, vendedor e custos pendentes" + ("; população não verificada" if self.listing.graded else ""),
            "comc_url": self.listing.url,
            "tcg_url": self.product.url,
            "ref_url": self.ref_url or self.product.url,
        }
