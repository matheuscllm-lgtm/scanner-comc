"""Match a COMC listing to a TCGCSV product with an explicit confidence tier.

Tiers (confidence):
  T1 0.95  set + collector number exact (unique)
  T1'0.90  set + number, multiple variants -> disambiguated by name
  T2 0.85  set known, number absent/garbled, name fuzzy >= 90 within set
  T3 0.70  set known, no number, name fuzzy >= 92 and clearly ahead of runner-up
  reject   set unknown / no confident name / no usable price
"""
from __future__ import annotations

from .config import Settings
from .margin import get_margin_fn
from .models import ComcListing, Deal, TcgCard
from .normalize import fuzzy_ratio, normalize_name, parse_number, subtype_hint
from .tcg_index import TcgIndex


def _best_name(cards: list[TcgCard], norm_name: str) -> tuple[TcgCard | None, float, float]:
    """Return (best_card, best_score, runner_up_score)."""
    best: TcgCard | None = None
    best_score = -1.0
    runner = -1.0
    for card in cards:
        score = fuzzy_ratio(norm_name, normalize_name(card.product.name))
        if score > best_score:
            runner = best_score
            best, best_score = card, score
        elif score > runner:
            runner = score
    return best, max(best_score, 0.0), max(runner, 0.0)


def _build_deal(
    listing: ComcListing, card: TcgCard, index: TcgIndex, settings: Settings,
    confidence: float, reason: str,
) -> Deal | None:
    prefer = subtype_hint(listing.raw_name, listing.condition, card.product.rarity)
    ref = index.reference_price(card, prefer)
    if ref is None:
        return None
    ref_price, sub_used, field_used = ref
    margin = get_margin_fn(settings.margin_mode)(ref_price, listing.price)
    return Deal(
        listing=listing,
        product=card.product,
        price=card.subtypes[sub_used],
        tcg_reference=ref_price,
        price_field_used=field_used,
        sub_type_used=sub_used,
        margin=margin,
        match_confidence=confidence,
        match_reason=reason,
    )


def match(
    listing: ComcListing, index: TcgIndex, settings: Settings,
    context_set_key: str | None = None,
) -> Deal | None:
    """Best-effort match; returns a Deal (with margin computed) or None."""
    set_key = index.resolve_set(listing.set_hint) or context_set_key
    if not set_key:
        return None

    norm_name = normalize_name(listing.raw_name)
    number_key = parse_number(listing.number_hint)

    # Tier 1: exact set + number
    if number_key:
        exact = index.by_set_number.get((set_key, number_key))
        if exact:
            if len(exact) == 1:
                return _build_deal(listing, exact[0], index, settings, 0.95, "set+number exact")
            card, score, _ = _best_name(exact, norm_name)
            if card is not None:
                return _build_deal(
                    listing, card, index, settings, 0.90,
                    f"set+number, disambiguated by name {score:.0f}",
                )

    candidates = index.by_set.get(set_key, [])
    if not candidates:
        return None

    card, score, runner = _best_name(candidates, norm_name)
    if card is None:
        return None

    # Tier 2: number present but no exact hit -> strong name match required
    if number_key and score >= 90:
        return _build_deal(listing, card, index, settings, 0.85, f"name fuzzy {score:.0f} within set")

    # Tier 3: no number -> very strong, unambiguous name match
    if not number_key and score >= 92 and (score - runner) >= 3:
        return _build_deal(listing, card, index, settings, 0.70, f"name fuzzy {score:.0f} (no number)")

    return None
