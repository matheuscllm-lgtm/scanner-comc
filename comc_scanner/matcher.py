"""Match a COMC listing to a TCGCSV product with an explicit confidence tier.

Tiers (confidence):
  T1 0.95  set + collector number exact (unique)
  T1'0.90  set + number, multiple variants -> disambiguated by name
  T2 0.85  set known, number present but no exact hit, name fuzzy >= 90 and clearly ahead of runner-up
  T3 0.70  set known, no number, name fuzzy >= 92 and clearly ahead of runner-up
  reject   set unknown / no confident name / no usable price
"""
from __future__ import annotations

from .config import Settings
from .margin import get_margin_fn
from .models import ComcListing, Deal, TcgCard
from .normalize import (
    fuzzy_ratio, normalize_name, parse_number, parse_set_total, subtype_hint,
)
from .tcg_index import TcgIndex


def _set_total_ok(listing_number: str | None, product_number: str | None) -> bool:
    """False only when listing and product BOTH carry a set-total and they disagree.

    A collector number like '4/102' fingerprints its set via the '/102' denominator.
    When the COMC listing and a candidate product both expose a set-total and the two
    differ, the candidate is from a different print run/set than the listing — a
    corroborating-signal MISMATCH, so it is rejected (guards loose set resolution and
    keeps the supranumerary '226/217' case honest). A missing total on either side is
    no signal -> allowed; a bare number is never penalized.
    """
    lt = parse_set_total(listing_number)
    pt = parse_set_total(product_number)
    if lt is None or pt is None:
        return True
    return lt == pt


def _best_name(
    cards: list[TcgCard], norm_name: str, listing_number: str | None = None,
) -> tuple[TcgCard | None, float, float]:
    """Return (best_card, best_score, runner_up_score), skipping set-total conflicts."""
    best: TcgCard | None = None
    best_score = -1.0
    runner = -1.0
    for card in cards:
        if not _set_total_ok(listing_number, card.product.number):
            continue  # different set-total -> wrong set/print run, not a candidate
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
    # Edition/foil signal lives in the COMC set name + description, not the clean card
    # name, so feed those in too (e.g. "...- Base - 1st Edition", "Reverse Holofoil").
    signal = " ".join(filter(None, (listing.raw_name, listing.set_hint, listing.description)))
    prefer = subtype_hint(signal, listing.condition, card.product.rarity)
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

    # Tier 1: exact set + number. A unique set+number is normally decisive, but a
    # mis-resolved set + a coincidental number must not pass with a wildly different
    # name (real COMC "Pokemon" listings include Topps/Bandai/etc. whose set strings
    # can resolve loosely). Require a minimal name affinity as a sanity floor.
    _NAME_FLOOR = 45.0
    # Minimum lead of the best name over the runner-up for a fuzzy (no-exact-hit)
    # match to be trusted. Tier 3 already required this; Tier 2 did not, so an
    # ambiguous near-tie (two products in the set with almost-equal names) was
    # accepted at 0.85 — a likely wrong-card match. Found via ASI-Evolve
    # (comc_tiers): adding this gap to Tier 2 took eval precision 0.90 -> 1.0 with
    # recall unchanged (vs the F1-max candidate that lowered cutoffs and dropped
    # precision to 0.81). Conservative/precision-first: ambiguous -> no deal.
    _NAME_GAP = 3.0
    if number_key:
        exact = index.by_set_number.get((set_key, number_key))
        if exact:
            # Drop exact-numerator hits whose set-total contradicts the listing's
            # (a coincidental numerator from a mis-resolved set / different print run).
            exact = [c for c in exact
                     if _set_total_ok(listing.number_hint, c.product.number)]
        if exact:
            if len(exact) == 1:
                score = fuzzy_ratio(norm_name, normalize_name(exact[0].product.name))
                if not norm_name or score >= _NAME_FLOOR:
                    return _build_deal(listing, exact[0], index, settings, 0.95, "set+number exact")
            else:
                card, score, _ = _best_name(exact, norm_name, listing.number_hint)
                if card is not None and score >= _NAME_FLOOR:
                    return _build_deal(
                        listing, card, index, settings, 0.90,
                        f"set+number, disambiguated by name {score:.0f}",
                    )

    candidates = index.by_set.get(set_key, [])
    if not candidates:
        return None

    card, score, runner = _best_name(candidates, norm_name, listing.number_hint)
    if card is None:
        return None

    # Tier 2: number present but no exact hit -> strong name match required,
    # and clearly ahead of the runner-up (gap gate; reject ambiguous near-ties).
    if number_key and score >= 90 and (score - runner) >= _NAME_GAP:
        return _build_deal(listing, card, index, settings, 0.85, f"name fuzzy {score:.0f} within set")

    # Tier 3: no number -> very strong, unambiguous name match
    if not number_key and score >= 92 and (score - runner) >= _NAME_GAP:
        return _build_deal(listing, card, index, settings, 0.70, f"name fuzzy {score:.0f} (no number)")

    return None
