"""Data models shared across the scanner."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ranking import UNRANKED, compute_metrics

STATUS_OK = "OK"
STATUS_REVIEW = "MATCH_REVIEW"


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
    tcg_reference: float          # preço de referência usado (raw: TCGplayer; slab: PriceCharting)
    price_field_used: str         # raw: market/mid/low; slab: coluna do PC (ex. "PSA 10")
    sub_type_used: str
    margin: float                 # desconto como fração: (ref − comc)/ref
    match_confidence: float
    match_reason: str
    era: str = ""
    pokemon: str = ""             # Pokémon icônico casado (lista do operador)
    pokemon_rank: int = UNRANKED
    ref_source: str = "tcgplayer"  # "tcgplayer" | "pricecharting" | "pricecharting-proxy"
    ref_url: str = ""             # página onde conferir o preço de referência
    status: str = STATUS_OK       # OK | MATCH_REVIEW (match/preço não confiável o bastante)
    review_reasons: tuple[str, ...] = ()

    @property
    def listing_type(self) -> str:
        """'Raw NM' ou a nota do slab ('PSA 10', 'CGC 10 Pristine')."""
        if self.listing.graded and self.listing.grade:
            return self.listing.grade.replace("PRISTINE", "Pristine").replace("GEM", "Gem Mint")
        return f"Raw {self.listing.condition or ''}".strip()

    def as_row(self) -> dict[str, object]:
        """Flat dict for CSV/JSON/markdown output."""
        m = compute_metrics(self.tcg_reference, self.listing.price)
        return {
            "margin_pct": m.discount_pct,
            "roi_pct": m.roi_pct,
            "comc_price": round(self.listing.price, 2),
            "tcg_reference": round(self.tcg_reference, 2),
            "profit_abs": m.profit_abs,
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
            "era": self.era,
            "confidence": round(self.match_confidence, 2),
            "match_reason": self.match_reason,
            "status": self.status,
            "review_reasons": " · ".join(self.review_reasons),
            "quantity": self.listing.quantity,
            "comc_url": self.listing.url,
            "tcg_url": self.product.url,
            "ref_url": self.ref_url or self.product.url,
        }
