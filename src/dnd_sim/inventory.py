from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

COIN_VALUES_CP: dict[str, int] = {
    "cp": 1,
    "sp": 10,
    "ep": 50,
    "gp": 100,
    "pp": 1000,
}
_CANONICAL_COIN_ORDER: tuple[str, ...] = ("pp", "gp", "ep", "sp", "cp")


def _coerce_non_negative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _normalize_slot_name(value: Any) -> str:
    normalized = _slugify(str(value).strip())
    if not normalized:
        raise ValueError("equipment slot must not be blank")
    return normalized


def _coerce_slot_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    candidates: list[Any]
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        return ()

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        slot = _normalize_slot_name(candidate)
        if slot in seen:
            continue
        seen.add(slot)
        normalized.append(slot)
    return tuple(normalized)


def _currency_total_cp(value: Mapping[str, int] | CurrencyWallet) -> int:
    if isinstance(value, CurrencyWallet):
        return value.total_cp

    total = 0
    for coin, cp_value in COIN_VALUES_CP.items():
        amount = value.get(coin, 0)
        total += _coerce_non_negative_int(amount, field_name=coin) * cp_value
    return total


@dataclass(slots=True)
class CurrencyWallet:
    cp: int = 0
    sp: int = 0
    ep: int = 0
    gp: int = 0
    pp: int = 0

    def __post_init__(self) -> None:
        self.cp = _coerce_non_negative_int(self.cp, field_name="cp")
        self.sp = _coerce_non_negative_int(self.sp, field_name="sp")
        self.ep = _coerce_non_negative_int(self.ep, field_name="ep")
        self.gp = _coerce_non_negative_int(self.gp, field_name="gp")
        self.pp = _coerce_non_negative_int(self.pp, field_name="pp")

    @property
    def total_cp(self) -> int:
        return (
            self.cp * COIN_VALUES_CP["cp"]
            + self.sp * COIN_VALUES_CP["sp"]
            + self.ep * COIN_VALUES_CP["ep"]
            + self.gp * COIN_VALUES_CP["gp"]
            + self.pp * COIN_VALUES_CP["pp"]
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> CurrencyWallet:
        payload = raw or {}
        return cls(
            cp=int(payload.get("cp", 0)),
            sp=int(payload.get("sp", 0)),
            ep=int(payload.get("ep", 0)),
            gp=int(payload.get("gp", 0)),
            pp=int(payload.get("pp", 0)),
        )

    def to_mapping(self) -> dict[str, int]:
        return {"cp": self.cp, "sp": self.sp, "ep": self.ep, "gp": self.gp, "pp": self.pp}

    def can_afford(self, cost: Mapping[str, int] | CurrencyWallet) -> bool:
        return self.total_cp >= _currency_total_cp(cost)

    def add(self, amount: Mapping[str, int] | CurrencyWallet) -> None:
        self._set_from_cp(self.total_cp + _currency_total_cp(amount))

    def spend(self, cost: Mapping[str, int] | CurrencyWallet) -> None:
        required_cp = _currency_total_cp(cost)
        if required_cp > self.total_cp:
            raise ValueError("Insufficient currency")
        self._set_from_cp(self.total_cp - required_cp)

    def transfer_to(
        self, recipient: CurrencyWallet, amount: Mapping[str, int] | CurrencyWallet
    ) -> None:
        required_cp = _currency_total_cp(amount)
        if required_cp > self.total_cp:
            raise ValueError("Insufficient currency")
        self._set_from_cp(self.total_cp - required_cp)
        recipient._set_from_cp(recipient.total_cp + required_cp)

    def _set_from_cp(self, total_cp: int) -> None:
        remaining = _coerce_non_negative_int(total_cp, field_name="total_cp")
        values: dict[str, int] = {coin: 0 for coin in COIN_VALUES_CP}
        for coin in _CANONICAL_COIN_ORDER:
            coin_cp = COIN_VALUES_CP[coin]
            count, remaining = divmod(remaining, coin_cp)
            values[coin] = count
        self.cp = values["cp"]
        self.sp = values["sp"]
        self.ep = values["ep"]
        self.gp = values["gp"]
        self.pp = values["pp"]


@dataclass(slots=True)
class InventoryItem:
    item_id: str
    name: str
    quantity: int = 1
    value_cp: int = 0
    weight_lb: float = 0.0
    requires_attunement: bool = False
    attuned: bool = False
    consumable: bool = False
    equip_slots: tuple[str, ...] = ()
    equipped_slot: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.item_id = _slugify(self.item_id.strip())
        if not self.item_id:
            raise ValueError("item_id must not be blank")
        self.name = str(self.name).strip()
        if not self.name:
            raise ValueError("name must not be blank")
        self.quantity = _coerce_non_negative_int(self.quantity, field_name="quantity")
        if self.quantity == 0:
            raise ValueError("quantity must be >= 1")
        self.value_cp = _coerce_non_negative_int(self.value_cp, field_name="value_cp")
        if self.weight_lb < 0:
            raise ValueError("weight_lb must be >= 0")
        if self.attuned and not self.requires_attunement:
            raise ValueError("Only attunement-required items can be attuned")
        self.equip_slots = _coerce_slot_tuple(self.equip_slots)
        if self.equipped_slot is not None:
            self.equipped_slot = _normalize_slot_name(self.equipped_slot)
            if not self.equip_slots:
                self.equip_slots = (self.equipped_slot,)
            if self.equipped_slot not in self.equip_slots:
                raise ValueError(
                    f"equipped_slot={self.equipped_slot} is not legal for item_id={self.item_id}"
                )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> InventoryItem:
        item_id = raw.get("item_id") or raw.get("id") or raw.get("name")
        if not isinstance(item_id, str):
            raise TypeError("item_id must be a string")
        name = raw.get("name") or item_id
        value_cp: int
        if "value_cp" in raw:
            value_cp = int(raw["value_cp"])
        elif "value_gp" in raw:
            value_cp = int(round(float(raw["value_gp"]) * COIN_VALUES_CP["gp"]))
        else:
            value_cp = 0

        metadata = dict(raw.get("metadata", {}))
        raw_slots = (
            raw.get("equip_slots")
            or raw.get("equippable_slots")
            or raw.get("slots")
            or raw.get("slot")
            or metadata.get("equip_slots")
            or metadata.get("equippable_slots")
            or metadata.get("slot")
        )
        raw_equipped_slot = raw.get("equipped_slot") or metadata.get("equipped_slot")
        if raw_equipped_slot is None and bool(raw.get("equipped") or metadata.get("equipped")):
            slots = _coerce_slot_tuple(raw_slots)
            raw_equipped_slot = slots[0] if slots else None

        return cls(
            item_id=item_id,
            name=str(name),
            quantity=int(raw.get("quantity", 1)),
            value_cp=value_cp,
            weight_lb=float(raw.get("weight_lb", 0.0)),
            requires_attunement=bool(raw.get("requires_attunement", False)),
            attuned=bool(raw.get("attuned", False)),
            consumable=bool(raw.get("consumable", False)),
            equip_slots=_coerce_slot_tuple(raw_slots),
            equipped_slot=(
                _normalize_slot_name(raw_equipped_slot) if raw_equipped_slot is not None else None
            ),
            metadata=metadata,
        )


@dataclass(slots=True)
class InventoryState:
    items: dict[str, InventoryItem] = field(default_factory=dict)
    currency: CurrencyWallet = field(default_factory=CurrencyWallet)
    attunement_limit: int = 3

    def __post_init__(self) -> None:
        self.attunement_limit = _coerce_non_negative_int(
            self.attunement_limit, field_name="attunement_limit"
        )
        if self.attunement_limit == 0:
            raise ValueError("attunement_limit must be >= 1")
        if not isinstance(self.currency, CurrencyWallet):
            self.currency = CurrencyWallet.from_mapping(dict(self.currency))
        for item in self.items.values():
            if item.equipped_slot is None:
                continue
            if (
                self._item_equipped_in_slot(item.equipped_slot, exclude_item_id=item.item_id)
                is not None
            ):
                raise ValueError(
                    f"equipment slot {item.equipped_slot} is occupied by multiple items"
                )

    @classmethod
    def from_character_payload(cls, character: Mapping[str, Any]) -> InventoryState:
        raw_attunement_limit = character.get("attunement_limit", 3)
        attunement_limit = int(raw_attunement_limit) if isinstance(raw_attunement_limit, int) else 3

        raw_currency = character.get("currency", {})
        currency = (
            CurrencyWallet.from_mapping(raw_currency)
            if isinstance(raw_currency, Mapping)
            else CurrencyWallet()
        )
        state = cls(currency=currency, attunement_limit=attunement_limit)

        raw_items = character.get("inventory", [])
        if not isinstance(raw_items, list):
            return state

        for row in raw_items:
            if not isinstance(row, Mapping):
                continue
            try:
                item = InventoryItem.from_mapping(row)
            except (TypeError, ValueError):
                continue
            state.add_item(item)

        return state

    def add_item(self, item: InventoryItem) -> None:
        existing = self.items.get(item.item_id)
        if existing is None:
            if item.equipped_slot is not None:
                occupied = self._item_equipped_in_slot(item.equipped_slot)
                if occupied is not None:
                    raise ValueError(
                        f"equipment slot {item.equipped_slot} already occupied by {occupied.item_id}"
                    )
            self.items[item.item_id] = item
            return
        if existing.requires_attunement != item.requires_attunement:
            raise ValueError(f"Item shape mismatch for item_id={item.item_id}")
        if existing.consumable != item.consumable:
            raise ValueError(f"Item shape mismatch for item_id={item.item_id}")
        if existing.equip_slots != item.equip_slots:
            raise ValueError(f"Item shape mismatch for item_id={item.item_id}")
        if (
            existing.equipped_slot is not None
            and item.equipped_slot is not None
            and existing.equipped_slot != item.equipped_slot
        ):
            raise ValueError(f"Item shape mismatch for item_id={item.item_id}")
        existing.quantity += item.quantity
        existing.attuned = existing.attuned or item.attuned
        existing.equipped_slot = existing.equipped_slot or item.equipped_slot
        existing.value_cp = max(existing.value_cp, item.value_cp)
        existing.weight_lb = max(existing.weight_lb, item.weight_lb)

    def remove_item(self, item_id: str, *, quantity: int = 1) -> None:
        key = _slugify(item_id)
        item = self.items.get(key)
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        quantity = _coerce_non_negative_int(quantity, field_name="quantity")
        if quantity == 0:
            raise ValueError("quantity must be >= 1")
        if quantity > item.quantity:
            raise ValueError("quantity exceeds amount in inventory")
        item.quantity -= quantity
        if item.quantity == 0:
            self.items.pop(key, None)

    def consume_item(self, item_id: str, *, quantity: int = 1) -> None:
        item = self.items.get(_slugify(item_id))
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        if not item.consumable:
            raise ValueError(f"Item {item_id} is not consumable")
        self.remove_item(item_id, quantity=quantity)

    def attuned_item_ids(self) -> set[str]:
        return {item.item_id for item in self.items.values() if item.attuned}

    def attune_item(self, item_id: str) -> None:
        item = self.items.get(_slugify(item_id))
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        if not item.requires_attunement:
            raise ValueError(f"Item {item_id} does not require attunement")
        if item.attuned:
            return
        if len(self.attuned_item_ids()) >= self.attunement_limit:
            raise ValueError("Attunement limit exceeded")
        item.attuned = True

    def unattune_item(self, item_id: str) -> None:
        item = self.items.get(_slugify(item_id))
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        item.attuned = False

    def equip_item(self, item_id: str, *, slot: str | None = None) -> str:
        key = _slugify(item_id)
        item = self.items.get(key)
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        if not item.equip_slots:
            raise ValueError(f"Item {item_id} is not equippable")
        if item.requires_attunement and not item.attuned:
            raise ValueError(f"Item {item_id} must be attuned before it can be equipped")

        target_slot = _normalize_slot_name(slot) if slot is not None else None
        if target_slot is None:
            if item.equipped_slot is not None:
                return item.equipped_slot
            for candidate in item.equip_slots:
                occupant = self._item_equipped_in_slot(candidate, exclude_item_id=item.item_id)
                if occupant is None:
                    target_slot = candidate
                    break
            if target_slot is None:
                target_slot = item.equip_slots[0]

        if target_slot not in item.equip_slots:
            raise ValueError(f"Item {item_id} cannot be equipped in slot {target_slot}")
        occupant = self._item_equipped_in_slot(target_slot, exclude_item_id=item.item_id)
        if occupant is not None:
            raise ValueError(f"equipment slot {target_slot} already occupied by {occupant.item_id}")

        item.equipped_slot = target_slot
        return target_slot

    def unequip_item(self, item_id: str, *, slot: str | None = None) -> None:
        key = _slugify(item_id)
        item = self.items.get(key)
        if item is None:
            raise KeyError(f"Unknown item_id={item_id}")
        if item.equipped_slot is None:
            return
        if slot is not None and _normalize_slot_name(slot) != item.equipped_slot:
            raise ValueError(f"Item {item_id} is not equipped in slot {slot}")
        item.equipped_slot = None

    def is_item_equipped(self, item_id: str, *, slot: str | None = None) -> bool:
        key = _slugify(item_id)
        item = self.items.get(key)
        if item is None or item.equipped_slot is None:
            return False
        if slot is None:
            return True
        return item.equipped_slot == _normalize_slot_name(slot)

    def has_equipped_shield(self) -> bool:
        for item in self.items.values():
            if item.equipped_slot is None:
                continue
            if item.equipped_slot == "shield":
                return True
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            armor_type = _slugify(str(metadata.get("armor_type", "")))
            if armor_type == "shield":
                return True
            if bool(metadata.get("is_shield")):
                return True
            if "shield" in _slugify(item.name):
                return True
        return False

    def has_item_quantity(self, item_id: str, *, quantity: int = 1) -> bool:
        required = _coerce_non_negative_int(quantity, field_name="quantity")
        if required == 0:
            return True
        item = self.items.get(_slugify(item_id))
        return item is not None and item.quantity >= required

    def consume_ammo(self, item_id: str, *, quantity: int = 1) -> None:
        self.remove_item(item_id, quantity=quantity)

    def find_ammo_item_id(self, ammo_type: str) -> str | None:
        token = _slugify(ammo_type)
        if not token:
            return None
        for item_id in sorted(self.items.keys()):
            item = self.items[item_id]
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            current_type = _slugify(str(metadata.get("ammo_type", "")))
            if current_type == token and item.quantity > 0:
                return item_id
        return None

    def resolve_ammo_item_id(
        self,
        *,
        ammo_item_id: str | None = None,
        ammo_type: str | None = None,
    ) -> str | None:
        if ammo_item_id:
            candidate = _slugify(ammo_item_id)
            if candidate in self.items:
                return candidate
        if ammo_type:
            return self.find_ammo_item_id(ammo_type)
        return None

    def _item_equipped_in_slot(
        self,
        slot: str,
        *,
        exclude_item_id: str | None = None,
    ) -> InventoryItem | None:
        for item in self.items.values():
            if exclude_item_id is not None and item.item_id == exclude_item_id:
                continue
            if item.equipped_slot == slot:
                return item
        return None

    def can_afford(self, cost: Mapping[str, int] | CurrencyWallet) -> bool:
        return self.currency.can_afford(cost)

    def spend_currency(self, cost: Mapping[str, int] | CurrencyWallet) -> None:
        self.currency.spend(cost)

    def add_currency(self, amount: Mapping[str, int] | CurrencyWallet) -> None:
        self.currency.add(amount)

    def transfer_currency(
        self, recipient: InventoryState, amount: Mapping[str, int] | CurrencyWallet
    ) -> None:
        self.currency.transfer_to(recipient.currency, amount)
