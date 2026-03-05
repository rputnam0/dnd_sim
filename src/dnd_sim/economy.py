from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Mapping

from dnd_sim.inventory import CurrencyWallet

BASIS_POINTS = 10_000
DEFAULT_MARKET_PRICE_INDEX_BP = BASIS_POINTS
DEFAULT_VENDOR_MARKUP_BP = 11_000

_RARITIES = {
    "common",
    "uncommon",
    "rare",
    "very_rare",
    "legendary",
    "artifact",
}


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(
    value: Any,
    *,
    field_name: str,
    minimum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _required_basis_points(
    value: Any,
    *,
    field_name: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    normalized = _required_int(value, field_name=field_name, minimum=minimum)
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be <= {maximum}")
    return normalized


@dataclass(frozen=True, slots=True)
class MarketItem:
    item_id: str
    name: str
    base_price_cp: int
    rarity: str = "common"
    category: str = "general"
    vendor_weight: int = 1
    loot_weight: int = 1
    min_vendor_quantity: int = 1
    max_vendor_quantity: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _required_text(self.item_id, field_name="item_id"))
        name = str(self.name).strip()
        if not name:
            raise ValueError("name must be non-empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "base_price_cp",
            _required_int(self.base_price_cp, field_name="base_price_cp", minimum=1),
        )
        rarity = _required_text(self.rarity, field_name="rarity")
        if rarity not in _RARITIES:
            raise ValueError("rarity must be a canonical rarity token")
        object.__setattr__(self, "rarity", rarity)
        object.__setattr__(self, "category", _required_text(self.category, field_name="category"))
        object.__setattr__(
            self,
            "vendor_weight",
            _required_int(self.vendor_weight, field_name="vendor_weight", minimum=1),
        )
        object.__setattr__(
            self,
            "loot_weight",
            _required_int(self.loot_weight, field_name="loot_weight", minimum=1),
        )
        min_quantity = _required_int(
            self.min_vendor_quantity,
            field_name="min_vendor_quantity",
            minimum=0,
        )
        max_quantity = _required_int(
            self.max_vendor_quantity,
            field_name="max_vendor_quantity",
            minimum=min_quantity,
        )
        object.__setattr__(self, "min_vendor_quantity", min_quantity)
        object.__setattr__(self, "max_vendor_quantity", max_quantity)


@dataclass(frozen=True, slots=True)
class VendorStock:
    item_id: str
    quantity: int
    unit_price_cp: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _required_text(self.item_id, field_name="item_id"))
        object.__setattr__(
            self,
            "quantity",
            _required_int(self.quantity, field_name="quantity", minimum=1),
        )
        object.__setattr__(
            self,
            "unit_price_cp",
            _required_int(self.unit_price_cp, field_name="unit_price_cp", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class VendorInventory:
    vendor_id: str
    markup_bp: int = DEFAULT_VENDOR_MARKUP_BP
    stock: dict[str, VendorStock] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "vendor_id", _required_text(self.vendor_id, field_name="vendor_id")
        )
        object.__setattr__(
            self,
            "markup_bp",
            _required_basis_points(
                self.markup_bp,
                field_name="markup_bp",
                minimum=1,
            ),
        )

        normalized_stock: dict[str, VendorStock] = {}
        for item_id, stock_row in sorted(dict(self.stock).items()):
            normalized_item_id = _required_text(item_id, field_name="item_id")
            if not isinstance(stock_row, VendorStock):
                raise ValueError("stock values must be VendorStock")
            if stock_row.item_id != normalized_item_id:
                stock_row = VendorStock(
                    item_id=normalized_item_id,
                    quantity=stock_row.quantity,
                    unit_price_cp=stock_row.unit_price_cp,
                )
            normalized_stock[normalized_item_id] = stock_row
        object.__setattr__(self, "stock", normalized_stock)


@dataclass(frozen=True, slots=True)
class LootDrop:
    item_quantities: dict[str, int] = field(default_factory=dict)
    currency_cp: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "currency_cp",
            _required_int(self.currency_cp, field_name="currency_cp", minimum=0),
        )
        normalized_items: dict[str, int] = {}
        for item_id, quantity in sorted(dict(self.item_quantities).items()):
            normalized_item_id = _required_text(item_id, field_name="item_id")
            normalized_items[normalized_item_id] = _required_int(
                quantity,
                field_name="quantity",
                minimum=1,
            )
        object.__setattr__(self, "item_quantities", normalized_items)


@dataclass(frozen=True, slots=True)
class EconomyState:
    day_index: int
    market_price_index_bp: int
    catalog: dict[str, MarketItem]
    vendors: dict[str, VendorInventory] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "day_index",
            _required_int(self.day_index, field_name="day_index", minimum=1),
        )
        object.__setattr__(
            self,
            "market_price_index_bp",
            _required_basis_points(
                self.market_price_index_bp,
                field_name="market_price_index_bp",
                minimum=1,
            ),
        )

        normalized_catalog: dict[str, MarketItem] = {}
        for item_id, item in sorted(dict(self.catalog).items()):
            normalized_item_id = _required_text(item_id, field_name="item_id")
            if not isinstance(item, MarketItem):
                raise ValueError("catalog values must be MarketItem")
            if item.item_id != normalized_item_id:
                item = MarketItem(
                    item_id=normalized_item_id,
                    name=item.name,
                    base_price_cp=item.base_price_cp,
                    rarity=item.rarity,
                    category=item.category,
                    vendor_weight=item.vendor_weight,
                    loot_weight=item.loot_weight,
                    min_vendor_quantity=item.min_vendor_quantity,
                    max_vendor_quantity=item.max_vendor_quantity,
                )
            normalized_catalog[normalized_item_id] = item
        object.__setattr__(self, "catalog", normalized_catalog)

        normalized_vendors: dict[str, VendorInventory] = {}
        for vendor_id, vendor in sorted(dict(self.vendors).items()):
            normalized_vendor_id = _required_text(vendor_id, field_name="vendor_id")
            if not isinstance(vendor, VendorInventory):
                raise ValueError("vendors values must be VendorInventory")
            if vendor.vendor_id != normalized_vendor_id:
                vendor = VendorInventory(
                    vendor_id=normalized_vendor_id,
                    markup_bp=vendor.markup_bp,
                    stock=vendor.stock,
                )
            normalized_vendors[normalized_vendor_id] = vendor
        object.__setattr__(self, "vendors", normalized_vendors)


def _coerce_market_item(item_id: str, payload: MarketItem | Mapping[str, Any]) -> MarketItem:
    if isinstance(payload, MarketItem):
        if payload.item_id == item_id:
            return payload
        return MarketItem(
            item_id=item_id,
            name=payload.name,
            base_price_cp=payload.base_price_cp,
            rarity=payload.rarity,
            category=payload.category,
            vendor_weight=payload.vendor_weight,
            loot_weight=payload.loot_weight,
            min_vendor_quantity=payload.min_vendor_quantity,
            max_vendor_quantity=payload.max_vendor_quantity,
        )
    if not isinstance(payload, Mapping):
        raise ValueError("catalog entries must be MarketItem or mapping payloads")

    payload_item_id = payload.get("item_id", item_id)
    return MarketItem(
        item_id=str(payload_item_id),
        name=str(payload.get("name", payload_item_id)),
        base_price_cp=int(payload.get("base_price_cp")),
        rarity=str(payload.get("rarity", "common")),
        category=str(payload.get("category", "general")),
        vendor_weight=int(payload.get("vendor_weight", 1)),
        loot_weight=int(payload.get("loot_weight", 1)),
        min_vendor_quantity=int(payload.get("min_vendor_quantity", 1)),
        max_vendor_quantity=int(payload.get("max_vendor_quantity", 3)),
    )


def _coerce_vendor_stock(
    item_id: str,
    payload: VendorStock | Mapping[str, Any] | int,
    *,
    catalog: Mapping[str, MarketItem],
    market_price_index_bp: int,
    markup_bp: int,
) -> VendorStock:
    if item_id not in catalog:
        raise ValueError(f"Unknown item_id={item_id} for vendor stock")

    if isinstance(payload, VendorStock):
        if payload.item_id == item_id:
            return payload
        return VendorStock(
            item_id=item_id,
            quantity=payload.quantity,
            unit_price_cp=payload.unit_price_cp,
        )
    if isinstance(payload, int) and not isinstance(payload, bool):
        return VendorStock(
            item_id=item_id,
            quantity=payload,
            unit_price_cp=price_item(
                catalog[item_id],
                market_price_index_bp=market_price_index_bp,
                vendor_markup_bp=markup_bp,
            ),
        )
    if not isinstance(payload, Mapping):
        raise ValueError("vendor stock rows must be VendorStock, mapping, or integer quantity")

    quantity = int(payload.get("quantity", 1))
    if "unit_price_cp" in payload:
        unit_price_cp = int(payload["unit_price_cp"])
    else:
        unit_price_cp = price_item(
            catalog[item_id],
            market_price_index_bp=market_price_index_bp,
            vendor_markup_bp=markup_bp,
        )
    return VendorStock(
        item_id=item_id,
        quantity=quantity,
        unit_price_cp=unit_price_cp,
    )


def _coerce_vendor_inventory(
    vendor_id: str,
    payload: VendorInventory | Mapping[str, Any],
    *,
    catalog: Mapping[str, MarketItem],
    market_price_index_bp: int,
) -> VendorInventory:
    if isinstance(payload, VendorInventory):
        if payload.vendor_id == vendor_id:
            return payload
        return VendorInventory(
            vendor_id=vendor_id,
            markup_bp=payload.markup_bp,
            stock=payload.stock,
        )
    if not isinstance(payload, Mapping):
        raise ValueError("vendors entries must be VendorInventory or mapping payloads")

    markup_bp = int(payload.get("markup_bp", DEFAULT_VENDOR_MARKUP_BP))
    raw_stock = payload.get("stock", {})
    if not isinstance(raw_stock, Mapping):
        raise ValueError("vendor stock must be a mapping")

    stock: dict[str, VendorStock] = {}
    for item_id, stock_payload in sorted(raw_stock.items()):
        normalized_item_id = _required_text(item_id, field_name="item_id")
        stock[normalized_item_id] = _coerce_vendor_stock(
            normalized_item_id,
            stock_payload,
            catalog=catalog,
            market_price_index_bp=market_price_index_bp,
            markup_bp=markup_bp,
        )
    return VendorInventory(vendor_id=vendor_id, markup_bp=markup_bp, stock=stock)


def create_economy_state(
    *,
    catalog: Mapping[str, MarketItem | Mapping[str, Any]] | None = None,
    vendors: Mapping[str, VendorInventory | Mapping[str, Any]] | None = None,
    day_index: int = 1,
    market_price_index_bp: int = DEFAULT_MARKET_PRICE_INDEX_BP,
) -> EconomyState:
    normalized_catalog: dict[str, MarketItem] = {}
    for item_id, payload in sorted((catalog or {}).items()):
        normalized_item_id = _required_text(item_id, field_name="item_id")
        normalized_catalog[normalized_item_id] = _coerce_market_item(normalized_item_id, payload)

    normalized_vendors: dict[str, VendorInventory] = {}
    for vendor_id, payload in sorted((vendors or {}).items()):
        normalized_vendor_id = _required_text(vendor_id, field_name="vendor_id")
        normalized_vendors[normalized_vendor_id] = _coerce_vendor_inventory(
            normalized_vendor_id,
            payload,
            catalog=normalized_catalog,
            market_price_index_bp=market_price_index_bp,
        )

    return EconomyState(
        day_index=day_index,
        market_price_index_bp=market_price_index_bp,
        catalog=normalized_catalog,
        vendors=normalized_vendors,
    )


def price_item(
    item: MarketItem,
    *,
    market_price_index_bp: int = DEFAULT_MARKET_PRICE_INDEX_BP,
    vendor_markup_bp: int = BASIS_POINTS,
    discount_bp: int = 0,
) -> int:
    market_bp = _required_basis_points(
        market_price_index_bp,
        field_name="market_price_index_bp",
        minimum=1,
    )
    markup_bp = _required_basis_points(
        vendor_markup_bp,
        field_name="vendor_markup_bp",
        minimum=1,
    )
    discount = _required_basis_points(
        discount_bp,
        field_name="discount_bp",
        minimum=0,
        maximum=BASIS_POINTS - 1,
    )

    market_adjusted = (item.base_price_cp * market_bp + (BASIS_POINTS - 1)) // BASIS_POINTS
    marked_up = (market_adjusted * markup_bp + (BASIS_POINTS - 1)) // BASIS_POINTS
    discount_cp = (marked_up * discount) // BASIS_POINTS
    return max(1, marked_up - discount_cp)


def _weighted_pick_index(
    *,
    rng: random.Random,
    items: list[MarketItem],
    weight_getter: Callable[[MarketItem], int],
) -> int:
    total_weight = sum(weight_getter(item) for item in items)
    if total_weight <= 0:
        raise ValueError("weighted selection requires positive total weight")
    roll = rng.randint(1, total_weight)
    running = 0
    for index, item in enumerate(items):
        running += weight_getter(item)
        if running >= roll:
            return index
    return len(items) - 1


def generate_vendor_inventory(
    *,
    vendor_id: str,
    catalog: Mapping[str, MarketItem],
    seed: int,
    stock_count: int,
    market_price_index_bp: int = DEFAULT_MARKET_PRICE_INDEX_BP,
    markup_bp: int = DEFAULT_VENDOR_MARKUP_BP,
) -> VendorInventory:
    normalized_vendor_id = _required_text(vendor_id, field_name="vendor_id")
    selection_count = _required_int(stock_count, field_name="stock_count", minimum=1)
    if not catalog:
        raise ValueError("catalog must contain at least one item")

    rng = random.Random(seed)
    available = [item for _, item in sorted(catalog.items())]
    selected: list[MarketItem] = []
    for _ in range(min(selection_count, len(available))):
        chosen_index = _weighted_pick_index(
            rng=rng,
            items=available,
            weight_getter=lambda entry: entry.vendor_weight,
        )
        selected.append(available.pop(chosen_index))

    stock: dict[str, VendorStock] = {}
    for item in selected:
        quantity = rng.randint(item.min_vendor_quantity, item.max_vendor_quantity)
        if quantity <= 0:
            continue
        stock[item.item_id] = VendorStock(
            item_id=item.item_id,
            quantity=quantity,
            unit_price_cp=price_item(
                item,
                market_price_index_bp=market_price_index_bp,
                vendor_markup_bp=markup_bp,
            ),
        )

    return VendorInventory(
        vendor_id=normalized_vendor_id,
        markup_bp=markup_bp,
        stock=stock,
    )


def generate_loot_drop(
    *,
    catalog: Mapping[str, MarketItem],
    seed: int,
    budget_cp: int,
    max_items: int = 4,
    currency_share_bp: int = 3_000,
) -> LootDrop:
    total_budget = _required_int(budget_cp, field_name="budget_cp", minimum=0)
    item_limit = _required_int(max_items, field_name="max_items", minimum=1)
    currency_share = _required_basis_points(
        currency_share_bp,
        field_name="currency_share_bp",
        minimum=0,
        maximum=BASIS_POINTS,
    )

    currency_cp = (total_budget * currency_share) // BASIS_POINTS
    remaining_budget = total_budget - currency_cp
    if remaining_budget <= 0 or not catalog:
        return LootDrop(currency_cp=total_budget)

    rng = random.Random(seed)
    item_quantities: dict[str, int] = {}
    generated_items = 0
    while generated_items < item_limit and remaining_budget > 0:
        candidates = [
            item for _, item in sorted(catalog.items()) if item.base_price_cp <= remaining_budget
        ]
        if not candidates:
            break
        chosen_index = _weighted_pick_index(
            rng=rng,
            items=candidates,
            weight_getter=lambda entry: entry.loot_weight,
        )
        chosen_item = candidates[chosen_index]
        item_quantities[chosen_item.item_id] = item_quantities.get(chosen_item.item_id, 0) + 1
        remaining_budget -= chosen_item.base_price_cp
        generated_items += 1

    currency_cp += remaining_budget
    return LootDrop(item_quantities=item_quantities, currency_cp=currency_cp)


def purchase_from_vendor(
    state: EconomyState,
    *,
    vendor_id: str,
    item_id: str,
    quantity: int,
    buyer_wallet: CurrencyWallet,
) -> tuple[EconomyState, int]:
    normalized_vendor_id = _required_text(vendor_id, field_name="vendor_id")
    normalized_item_id = _required_text(item_id, field_name="item_id")
    requested_quantity = _required_int(quantity, field_name="quantity", minimum=1)

    vendor = state.vendors.get(normalized_vendor_id)
    if vendor is None:
        raise KeyError(f"Unknown vendor_id={normalized_vendor_id}")

    stock = vendor.stock.get(normalized_item_id)
    if stock is None:
        raise KeyError(f"Unknown item_id={normalized_item_id} for vendor_id={normalized_vendor_id}")
    if requested_quantity > stock.quantity:
        raise ValueError("quantity exceeds vendor stock")

    total_cost_cp = stock.unit_price_cp * requested_quantity
    if not buyer_wallet.can_afford({"cp": total_cost_cp}):
        raise ValueError("Insufficient currency")
    buyer_wallet.spend({"cp": total_cost_cp})

    next_stock = dict(vendor.stock)
    remaining_quantity = stock.quantity - requested_quantity
    if remaining_quantity == 0:
        next_stock.pop(normalized_item_id, None)
    else:
        next_stock[normalized_item_id] = VendorStock(
            item_id=normalized_item_id,
            quantity=remaining_quantity,
            unit_price_cp=stock.unit_price_cp,
        )

    next_vendors = dict(state.vendors)
    next_vendors[normalized_vendor_id] = VendorInventory(
        vendor_id=vendor.vendor_id,
        markup_bp=vendor.markup_bp,
        stock=next_stock,
    )
    next_state = EconomyState(
        day_index=state.day_index,
        market_price_index_bp=state.market_price_index_bp,
        catalog=state.catalog,
        vendors=next_vendors,
    )
    return next_state, total_cost_cp
