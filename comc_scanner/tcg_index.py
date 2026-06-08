"""In-memory index over the cached TCGCSV snapshot, built incrementally per set."""
from __future__ import annotations

from .models import TcgCard, TcgPrice, TcgProduct
from .normalize import normalize_set, parse_number, set_aliases

# Subtype preference order when a hint is unavailable / missing. Common/cheaper
# print runs first so we never overstate margin by defaulting to a pricier 1st Edition.
_SUBTYPE_ORDER = (
    "Normal", "Unlimited", "Holofoil", "Unlimited Holofoil",
    "Reverse Holofoil", "1st Edition", "1st Edition Holofoil",
)
_PRICE_FIELDS = ("market", "mid", "low")


def _extended(product: dict) -> tuple[str | None, str | None, str | None]:
    number = rarity = card_type = None
    for item in product.get("extendedData", []) or []:
        name = item.get("name")
        value = item.get("value")
        if name == "Number":
            number = value
        elif name == "Rarity":
            rarity = value
        elif name == "Card Type":
            card_type = value
    return number, rarity, card_type


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class TcgIndex:
    def __init__(self) -> None:
        self.cards_by_product: dict[int, TcgCard] = {}
        self.by_set_number: dict[tuple[str, str], list[TcgCard]] = {}
        self.by_set: dict[str, list[TcgCard]] = {}
        self.set_name_index: dict[str, str] = {}
        self._groups_loaded: set[int] = set()

    def has_group(self, group_id: int) -> bool:
        return group_id in self._groups_loaded

    def resolve_set(self, set_hint: str | None) -> str | None:
        if not set_hint:
            return None
        key = normalize_set(set_hint)
        if key in self.by_set:
            return key
        if key in self.set_name_index:
            return self.set_name_index[key]
        # loose containment match against known aliases
        for alias, canonical in self.set_name_index.items():
            if alias and (alias in key or key in alias):
                return canonical
        return None

    def add_group(
        self, group_id: int, set_name: str, abbreviation: str,
        products: list[dict], prices: list[dict],
    ) -> None:
        if group_id in self._groups_loaded:
            return
        set_key = normalize_set(set_name)
        for alias in set_aliases(set_name) | {normalize_set(abbreviation)}:
            if alias:
                self.set_name_index[alias] = set_key

        # price rows -> {product_id: {subtype: TcgPrice}}
        price_map: dict[int, dict[str, TcgPrice]] = {}
        for row in prices:
            pid = int(row["productId"])
            sub = row.get("subTypeName") or "Normal"
            price_map.setdefault(pid, {})[sub] = TcgPrice(
                product_id=pid,
                sub_type=sub,
                low=_to_float(row.get("lowPrice")),
                mid=_to_float(row.get("midPrice")),
                high=_to_float(row.get("highPrice")),
                market=_to_float(row.get("marketPrice")),
                direct_low=_to_float(row.get("directLowPrice")),
            )

        bucket = self.by_set.setdefault(set_key, [])
        for p in products:
            pid = int(p["productId"])
            number, rarity, card_type = _extended(p)
            product = TcgProduct(
                product_id=pid,
                group_id=group_id,
                set_name=set_name,
                name=p.get("name", ""),
                clean_name=p.get("cleanName", "") or "",
                number=number,
                rarity=rarity,
                card_type=card_type,
                url=p.get("url", "") or "",
                image_url=p.get("imageUrl", "") or "",
            )
            card = TcgCard(product=product, subtypes=price_map.get(pid, {}))
            self.cards_by_product[pid] = card
            bucket.append(card)
            num_key = parse_number(number)
            if num_key:
                self.by_set_number.setdefault((set_key, num_key), []).append(card)
        self._groups_loaded.add(group_id)

    def reference_price(
        self, card: TcgCard, prefer_subtype: str | None = None
    ) -> tuple[float, str, str] | None:
        """Return (price, sub_type_used, field_used) using market->mid->low fallback.

        Preference: the hinted subtype, then a common-first ordering. If none of those
        are present, fall back to the *cheapest* available subtype (conservative, avoids
        overstating margin on sets that only have 1st Edition / Unlimited variants).
        """
        order: list[str] = []
        if prefer_subtype:
            order.append(prefer_subtype)
        order.extend(s for s in _SUBTYPE_ORDER if s not in order)
        for sub in order:
            price = card.subtypes.get(sub)
            if not price:
                continue
            for field in _PRICE_FIELDS:
                val = getattr(price, field)
                if val is not None and val > 0:
                    return float(val), sub, field

        # Fallback: cheapest available subtype/field present on this product.
        cheapest: tuple[float, str, str] | None = None
        for sub, price in card.subtypes.items():
            for field in _PRICE_FIELDS:
                val = getattr(price, field)
                if val is not None and val > 0:
                    if cheapest is None or val < cheapest[0]:
                        cheapest = (float(val), sub, field)
                    break
        return cheapest
