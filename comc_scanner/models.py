"""Data models shared across the scanner."""
from __future__ import annotations

from dataclasses import dataclass, field


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
    grader: str | None = None
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
    tcg_reference: float
    price_field_used: str
    sub_type_used: str
    margin: float
    match_confidence: float
    match_reason: str
    era: str = ""
    # --- modo --iconic (todos opcionais; vazios fora do modo) ---
    notorious: str | None = None      # personagem icônico casado (ex. "Charizard")
    pc_reference: float | None = None  # mediana das vendas reais ungraded (PriceCharting)
    pc_n_sales: int = 0
    pc_url: str = ""
    pc_margin: float | None = None     # mesma fórmula da margem TCG, base = pc_reference

    def as_row(self) -> dict[str, object]:
        """Flat dict for CSV/JSON/markdown output (Google-Sheets friendly)."""
        return {
            "margin_pct": round(self.margin * 100, 2),
            "comc_price": round(self.listing.price, 2),
            "tcg_reference": round(self.tcg_reference, 2),
            "profit_abs": round(self.tcg_reference - self.listing.price, 2),
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
            "condition": self.listing.condition,
            "sub_type": self.sub_type_used,
            "price_field": self.price_field_used,
            "era": self.era,
            "confidence": round(self.match_confidence, 2),
            "match_reason": self.match_reason,
            "quantity": self.listing.quantity,
            "comc_url": self.listing.url,
            "tcg_url": self.product.url,
            # modo --iconic: "" / None fora dele (o CSV/JSON continua plano)
            "notorious": self.notorious or "",
            "pc_reference": None if self.pc_reference is None else round(self.pc_reference, 2),
            "pc_n_sales": self.pc_n_sales,
            "pc_margin_pct": None if self.pc_margin is None else round(self.pc_margin * 100, 2),
            "pc_url": self.pc_url,
        }
