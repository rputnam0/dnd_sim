from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CLASSES_DIR = REPO_ROOT / "db" / "raw" / "5etools" / "classes"
RAW_ITEMS_PATH = REPO_ROOT / "db" / "raw" / "5etools" / "items" / "items_core.json"
CANONICAL_CLASSES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "classes"
CANONICAL_SUBCLASSES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "subclasses"
CANONICAL_ITEMS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "items"
_TOKEN_RE = re.compile(r"[^a-z0-9]+")
PACT_SLOTS_BY_LEVEL = {
    1: {"slot_level": 1, "slots": 1},
    2: {"slot_level": 1, "slots": 2},
    3: {"slot_level": 2, "slots": 2},
    4: {"slot_level": 2, "slots": 2},
    5: {"slot_level": 3, "slots": 2},
    6: {"slot_level": 3, "slots": 2},
    7: {"slot_level": 4, "slots": 2},
    8: {"slot_level": 4, "slots": 2},
    9: {"slot_level": 5, "slots": 2},
    10: {"slot_level": 5, "slots": 2},
    11: {"slot_level": 5, "slots": 3},
    12: {"slot_level": 5, "slots": 3},
    13: {"slot_level": 5, "slots": 3},
    14: {"slot_level": 5, "slots": 3},
    15: {"slot_level": 5, "slots": 3},
    16: {"slot_level": 5, "slots": 3},
    17: {"slot_level": 5, "slots": 4},
    18: {"slot_level": 5, "slots": 4},
    19: {"slot_level": 5, "slots": 4},
    20: {"slot_level": 5, "slots": 4},
}
SPELLCASTING_PROGRESSION_MAP = {
    None: "none",
    "": "none",
    "full": "full",
    "1/2": "half",
    "artificer": "half_up",
    "1/3": "third",
    "pact": "pact",
}


def _slugify(value: Any) -> str:
    return _TOKEN_RE.sub("_", str(value).strip().lower()).strip("_")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _reset_generated_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for entry in sorted(path.glob("*.json")):
        entry.unlink()


def _select_class_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if row.get("edition") == "classic":
            return row
    raise ValueError("raw class file did not contain a classic edition row")


def _iter_supported_subclasses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("edition") or "").strip().lower() != "one"
    ]


def _parse_feature_ref(raw: Any, *, subclass: bool) -> tuple[str, int, bool] | None:
    subclass_unlock = False
    if isinstance(raw, dict):
        ref = raw.get("subclassFeature") if subclass else raw.get("classFeature")
        if ref is None:
            ref = raw.get("classFeature") or raw.get("subclassFeature")
        subclass_unlock = bool(raw.get("gainSubclassFeature", False))
    else:
        ref = raw

    parts = str(ref or "").split("|")
    name = str(parts[0]).strip() if parts else ""
    level_index = 5 if subclass else 3
    if not name or len(parts) <= level_index:
        return None
    try:
        level = int(parts[level_index])
    except (TypeError, ValueError):
        return None
    if level <= 0:
        return None
    return name, level, subclass_unlock


def _normalize_feature_rows(raw_features: list[Any], *, subclass: bool) -> list[dict[str, Any]]:
    deduped: dict[tuple[int, str], dict[str, Any]] = {}
    for row in raw_features:
        parsed = _parse_feature_ref(row, subclass=subclass)
        if parsed is None:
            continue
        name, level, subclass_unlock = parsed
        key = (level, name.casefold())
        payload = {"name": name, "level": level}
        if subclass_unlock:
            payload["subclass_unlock"] = True
        deduped[key] = payload
    return [deduped[key] for key in sorted(deduped)]


def _normalize_class_payload(row: dict[str, Any]) -> dict[str, Any]:
    class_id = _slugify(row.get("name"))
    source_book = str(row.get("source") or "PHB").strip().upper()
    spellcasting = {
        "progression": SPELLCASTING_PROGRESSION_MAP.get(row.get("casterProgression"), "none")
    }
    if spellcasting["progression"] == "pact":
        spellcasting["pact_slots_by_level"] = {
            str(level): payload for level, payload in sorted(PACT_SLOTS_BY_LEVEL.items())
        }

    return {
        "class_id": class_id,
        "content_id": f"class:{class_id}|{source_book}",
        "features": _normalize_feature_rows(list(row.get("classFeatures", [])), subclass=False),
        "name": str(row.get("name")).strip(),
        "source_book": source_book,
        "spellcasting": spellcasting,
    }


def _normalize_subclass_payload(row: dict[str, Any]) -> dict[str, Any]:
    class_id = _slugify(row.get("className"))
    subclass_id = _slugify(row.get("shortName") or row.get("name"))
    source_book = str(row.get("source") or row.get("classSource") or "PHB").strip().upper()
    return {
        "class_id": class_id,
        "content_id": f"subclass:{subclass_id}_{class_id}|{source_book}",
        "features": _normalize_feature_rows(
            list(row.get("subclassFeatures", [])),
            subclass=True,
        ),
        "name": str(row.get("name")).strip(),
        "source_book": source_book,
        "subclass_id": subclass_id,
    }


def populate_class_catalogs() -> tuple[int, int]:
    _reset_generated_directory(CANONICAL_CLASSES_DIR)
    _reset_generated_directory(CANONICAL_SUBCLASSES_DIR)

    class_count = 0
    subclass_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(RAW_CLASSES_DIR.glob("class-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        class_row = _select_class_row(list(payload.get("class", [])))
        class_payload = _normalize_class_payload(class_row)
        _write_json(CANONICAL_CLASSES_DIR / f"{class_payload['class_id']}.json", class_payload)
        class_count += 1

        for subclass_row in _iter_supported_subclasses(list(payload.get("subclass", []))):
            subclass_payload = _normalize_subclass_payload(subclass_row)
            key = (subclass_payload["class_id"], subclass_payload["subclass_id"])
            current = subclass_payloads.get(key)
            if current is None or len(subclass_payload["features"]) > len(current["features"]):
                subclass_payloads[key] = subclass_payload

    for _, subclass_payload in sorted(subclass_payloads.items()):
        filename = f"{subclass_payload['class_id']}__{subclass_payload['subclass_id']}.json"
        _write_json(CANONICAL_SUBCLASSES_DIR / filename, subclass_payload)

    return class_count, len(subclass_payloads)


def _normalize_item_payload(row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("name")).strip()
    item_id = _slugify(row.get("item_id") or name)
    source_book = str(row.get("source") or row.get("source_book") or "PHB").strip().upper()
    payload: dict[str, Any] = {
        "category": str(row.get("category") or "gear").strip().lower(),
        "content_id": f"item:{item_id}|{source_book}",
        "item_id": item_id,
        "name": name,
        "source_book": source_book,
    }
    for source_key, target_key in (
        ("equipSlots", "equip_slots"),
        ("weaponProperties", "weapon_properties"),
        ("damage", "damage"),
        ("damageType", "damage_type"),
        ("requiresAttunement", "requires_attunement"),
        ("consumable", "consumable"),
        ("ammoType", "ammo_type"),
        ("maxCharges", "max_charges"),
        ("chargeRecovery", "charge_recovery"),
        ("passiveEffects", "passive_effects"),
        ("grantedActions", "granted_actions"),
        ("valueCp", "value_cp"),
        ("weightLb", "weight_lb"),
        ("metadata", "metadata"),
    ):
        if source_key in row:
            payload[target_key] = row[source_key]
    return payload


def populate_item_catalog() -> int:
    _reset_generated_directory(CANONICAL_ITEMS_DIR)
    raw_payload = json.loads(RAW_ITEMS_PATH.read_text(encoding="utf-8"))
    items = list(raw_payload.get("item", []))
    item_count = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        payload = _normalize_item_payload(row)
        _write_json(CANONICAL_ITEMS_DIR / f"{payload['item_id']}.json", payload)
        item_count += 1
    return item_count


def main() -> None:
    class_count, subclass_count = populate_class_catalogs()
    item_count = populate_item_catalog()
    print(
        "Populated Wave 7 catalogs: "
        f"{class_count} classes, {subclass_count} subclasses, {item_count} items."
    )


if __name__ == "__main__":
    main()
