from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ITEMS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "items"
_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_CONTENT_ID_RE = re.compile(r"^item:(?P<slug>[a-z0-9_]+)\|(?P<source>[A-Z0-9_]+)$")


def _slugify(value: Any) -> str:
    token = _TOKEN_RE.sub("_", str(value).strip().lower()).strip("_")
    return token


def _normalize_source_book(value: Any, *, default: str = "2014") -> str:
    text = str(value or default).strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    if not text:
        raise ValueError("source_book must be non-empty")
    return text


def canonical_item_id(*, name: str, source_book: str = "2014") -> str:
    slug = _slugify(name)
    if not slug:
        raise ValueError("name must be non-empty")
    return f"item:{slug}|{_normalize_source_book(source_book)}"


def _normalize_tokens(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(value) for value in raw]
    else:
        return ()

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = _slugify(value)
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return tuple(normalized)


class CanonicalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str | None = None
    item_id: str | None = None
    name: str
    source_book: str = "2014"
    category: str = "gear"
    equip_slots: tuple[str, ...] = ()
    weapon_properties: tuple[str, ...] = ()
    damage: str | None = None
    damage_type: str | None = None
    requires_attunement: bool = False
    consumable: bool = False
    ammo_type: str | None = None
    max_charges: int | None = None
    charge_recovery: dict[str, Any] | None = None
    passive_effects: list[dict[str, Any]] = Field(default_factory=list)
    granted_actions: list[dict[str, Any]] = Field(default_factory=list)
    value_cp: int = 0
    weight_lb: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("name must be non-empty")
        return normalized

    @field_validator("source_book")
    @classmethod
    def normalize_source_book(cls, value: str) -> str:
        return _normalize_source_book(value)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        token = _slugify(value)
        if not token:
            raise ValueError("category must be non-empty")
        return token

    @field_validator("equip_slots", "weapon_properties", mode="before")
    @classmethod
    def normalize_token_fields(cls, value: Any) -> tuple[str, ...]:
        return _normalize_tokens(value)

    @field_validator("ammo_type")
    @classmethod
    def normalize_ammo_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = _slugify(value)
        return token or None

    @field_validator("value_cp")
    @classmethod
    def validate_value_cp(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value_cp must be >= 0")
        return int(value)

    @field_validator("weight_lb")
    @classmethod
    def validate_weight_lb(cls, value: float) -> float:
        if value < 0:
            raise ValueError("weight_lb must be >= 0")
        return float(value)

    @field_validator("max_charges")
    @classmethod
    def validate_max_charges(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if int(value) <= 0:
            raise ValueError("max_charges must be >= 1")
        return int(value)

    @model_validator(mode="after")
    def validate_identity_fields(self) -> CanonicalItem:
        item_id = _slugify(self.item_id or self.name)
        if not item_id:
            raise ValueError("item_id must be non-empty")
        self.item_id = item_id

        expected_content_id = canonical_item_id(name=item_id, source_book=self.source_book)
        if self.content_id is None:
            self.content_id = expected_content_id
        else:
            text = str(self.content_id).strip()
            if _CONTENT_ID_RE.fullmatch(text) is None:
                raise ValueError("content_id must match 'item:<slug>|<SOURCE>'")
            if text != expected_content_id:
                raise ValueError(
                    f"content_id '{text}' does not match canonical id '{expected_content_id}'"
                )
            self.content_id = text
        return self


def build_item_catalog(*, item_payloads: list[dict[str, Any]]) -> dict[str, CanonicalItem]:
    catalog: dict[str, CanonicalItem] = {}
    seen_content_ids: set[str] = set()
    for payload in item_payloads:
        item = CanonicalItem.model_validate(payload)
        if item.item_id in catalog:
            raise ValueError(f"duplicate item_id '{item.item_id}' in canonical item catalog")
        if item.content_id in seen_content_ids:
            raise ValueError(f"duplicate content_id '{item.content_id}' in canonical item catalog")
        catalog[item.item_id] = item
        seen_content_ids.add(str(item.content_id))
    return dict(sorted(catalog.items()))


def load_item_catalog(*, items_dir: Path = DEFAULT_ITEMS_DIR) -> dict[str, CanonicalItem]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(items_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        normalized = dict(payload)
        normalized.setdefault("item_id", _slugify(path.stem))
        normalized.setdefault("name", path.stem)
        normalized.setdefault("source_book", payload.get("source_book") or payload.get("source"))
        payloads.append(normalized)
    return build_item_catalog(item_payloads=payloads)


@lru_cache(maxsize=1)
def load_default_item_catalog() -> dict[str, CanonicalItem]:
    return load_item_catalog(items_dir=DEFAULT_ITEMS_DIR)


def merge_item_payload_with_catalog_defaults(
    *,
    row: Mapping[str, Any],
    item: CanonicalItem,
) -> dict[str, Any]:
    merged = {
        "content_id": item.content_id,
        "item_id": item.item_id,
        "name": item.name,
        "value_cp": item.value_cp,
        "weight_lb": item.weight_lb,
        "requires_attunement": item.requires_attunement,
        "consumable": item.consumable,
        "equip_slots": list(item.equip_slots),
        "metadata": {
            **dict(item.metadata),
            "source_book": item.source_book,
            "category": item.category,
            "weapon_properties": list(item.weapon_properties),
            "ammo_type": item.ammo_type,
            "damage": item.damage,
            "damage_type": item.damage_type,
            "passive_effects": list(item.passive_effects),
            "granted_actions": list(item.granted_actions),
            "max_charges": item.max_charges,
            "charge_recovery": dict(item.charge_recovery or {}),
        },
    }
    for key, value in row.items():
        merged[key] = value

    merged_metadata = dict(merged.get("metadata", {}))
    if item.ammo_type and "ammo_type" not in merged_metadata:
        merged_metadata["ammo_type"] = item.ammo_type
    if item.weapon_properties and "weapon_properties" not in merged_metadata:
        merged_metadata["weapon_properties"] = list(item.weapon_properties)
    if item.damage and "damage" not in merged_metadata:
        merged_metadata["damage"] = item.damage
    if item.damage_type and "damage_type" not in merged_metadata:
        merged_metadata["damage_type"] = item.damage_type
    if item.passive_effects and "passive_effects" not in merged_metadata:
        merged_metadata["passive_effects"] = list(item.passive_effects)
    if item.granted_actions and "granted_actions" not in merged_metadata:
        merged_metadata["granted_actions"] = list(item.granted_actions)
    if item.max_charges is not None and "max_charges" not in merged_metadata:
        merged_metadata["max_charges"] = item.max_charges
    if item.charge_recovery and "charge_recovery" not in merged_metadata:
        merged_metadata["charge_recovery"] = dict(item.charge_recovery)
    merged["metadata"] = merged_metadata
    return merged
