from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from dnd_sim.capability_manifest import (
    build_class_capability_manifest,
    build_item_capability_manifest,
    build_subclass_capability_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/content/verify_completion_capabilities.py"

spec = importlib.util.spec_from_file_location("verify_completion_capabilities", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
verify_completion_capabilities = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_completion_capabilities
spec.loader.exec_module(verify_completion_capabilities)


def test_item_manifest_marks_supported_items_executable() -> None:
    manifest = build_item_capability_manifest(
        item_payloads=[
            {
                "name": "Longsword",
                "item_id": "longsword",
                "content_id": "item:longsword|PHB",
                "source_book": "PHB",
                "category": "weapon",
                "equip_slots": ["main_hand"],
            }
        ]
    )

    record = manifest.records[0]
    assert record.content_id == "item:longsword|PHB"
    assert record.content_type == "item"
    assert record.support_state == "supported"
    assert record.states.blocked is False


def test_class_and_subclass_manifests_emit_first_class_records() -> None:
    class_manifest = build_class_capability_manifest(
        class_payloads=[
            {
                "content_id": "class:fighter|PHB",
                "class_id": "fighter",
                "name": "Fighter",
                "source_book": "PHB",
                "features": [{"name": "Second Wind", "level": 1}],
            }
        ]
    )
    subclass_manifest = build_subclass_capability_manifest(
        subclass_payloads=[
            {
                "content_id": "subclass:battle_master_fighter|PHB",
                "subclass_id": "battle_master",
                "class_id": "fighter",
                "name": "Battle Master",
                "source_book": "PHB",
                "features": [{"name": "Combat Superiority", "level": 3}],
            }
        ]
    )

    class_record = class_manifest.records[0]
    subclass_record = subclass_manifest.records[0]

    assert class_record.content_type == "class"
    assert class_record.support_state == "supported"
    assert subclass_record.content_type == "subclass"
    assert subclass_record.support_state == "supported"


def test_discover_shipped_ids_includes_item_class_and_subclass(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    base = repo_root / "db" / "rules" / "2014"
    for name in ("spells", "traits", "monsters", "items", "classes", "subclasses"):
        (base / name).mkdir(parents=True, exist_ok=True)

    (base / "spells" / "acid_splash.json").write_text(
        json.dumps(
            {
                "name": "Acid Splash",
                "description": "You hurl acid.",
                "mechanics": [{"effect_type": "damage", "damage": "1d6", "target": "single_enemy"}],
            }
        ),
        encoding="utf-8",
    )
    (base / "traits" / "alert.json").write_text(
        json.dumps({"name": "Alert", "source_type": "feat", "mechanics": [{"meta_type": "init"}]}),
        encoding="utf-8",
    )
    (base / "monsters" / "goblin.json").write_text(
        json.dumps({"identity": {"enemy_id": "Goblin"}, "stat_block": {"max_hp": 7, "ac": 15}}),
        encoding="utf-8",
    )
    (base / "items" / "longsword.json").write_text(
        json.dumps(
            {
                "content_id": "item:longsword|PHB",
                "item_id": "longsword",
                "name": "Longsword",
                "source_book": "PHB",
                "category": "weapon",
            }
        ),
        encoding="utf-8",
    )
    (base / "classes" / "fighter.json").write_text(
        json.dumps(
            {
                "content_id": "class:fighter|PHB",
                "class_id": "fighter",
                "name": "Fighter",
                "source_book": "PHB",
                "features": [{"name": "Second Wind", "level": 1}],
            }
        ),
        encoding="utf-8",
    )
    (base / "subclasses" / "battle_master.json").write_text(
        json.dumps(
            {
                "content_id": "subclass:battle_master_fighter|PHB",
                "subclass_id": "battle_master",
                "class_id": "fighter",
                "name": "Battle Master",
                "source_book": "PHB",
                "features": [{"name": "Combat Superiority", "level": 3}],
            }
        ),
        encoding="utf-8",
    )

    ids = verify_completion_capabilities.discover_shipped_2014_content_ids(repo_root)
    assert "item:longsword|PHB" in ids
    assert "class:fighter|PHB" in ids
    assert "subclass:battle_master_fighter|PHB" in ids
