from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from dnd_sim.telemetry import TELEMETRY_SCHEMA_VERSION, build_event_envelope, serialize_event

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AGENT_INDEX_PATH = _REPO_ROOT / "docs" / "agent_index.yaml"
_OWNER_MODULE_RE = re.compile(r"^\s*owner_module:\s*(src/dnd_sim/[^\s]+\.py)\s*$")


def _iter_owned_runtime_modules() -> list[Path]:
    modules: list[Path] = []
    for line in _AGENT_INDEX_PATH.read_text(encoding="utf-8").splitlines():
        match = _OWNER_MODULE_RE.match(line)
        if match is None:
            continue
        path = _REPO_ROOT / match.group(1)
        if path.exists():
            modules.append(path)
    return modules


def _is_get_logger_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if len(node.args) != 1:
        return False
    if not isinstance(node.args[0], ast.Name) or node.args[0].id != "__name__":
        return False

    if isinstance(node.func, ast.Attribute):
        if node.func.attr != "getLogger":
            return False
        return isinstance(node.func.value, ast.Name) and node.func.value.id == "logging"
    if isinstance(node.func, ast.Name):
        return node.func.id == "getLogger"
    return False


def _has_module_level_logger(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target for target in node.targets if isinstance(target, ast.Name)]
            if any(target.id == "logger" for target in targets) and _is_get_logger_call(node.value):
                return True
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "logger" and node.value is not None:
                if _is_get_logger_call(node.value):
                    return True
    return False


def test_build_event_envelope_is_json_compatible() -> None:
    payload = {
        "round": 3,
        "actor_id": "hero",
        "movement_path": [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]],
        "rationale": {"reason": "focus_fire"},
        "nullable_value": None,
    }

    event = build_event_envelope(
        event_type="decision",
        payload=payload,
        source="dnd_sim.engine",
    )

    assert event["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert event["event_type"] == "decision"
    assert event["telemetry_type"] == "decision"
    assert event["source"] == "dnd_sim.engine"
    assert event["payload"] == payload
    assert event["actor_id"] == "hero"

    assert json.loads(json.dumps(event, sort_keys=True)) == event


def test_build_event_envelope_rejects_non_json_payload() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        build_event_envelope(
            event_type="decision",
            payload={"bad": {"value_set"}},
            source="dnd_sim.engine",
        )


def test_event_serialization_is_deterministic() -> None:
    event = build_event_envelope(
        event_type="effect_contribution",
        payload={
            "round": 2,
            "actor_id": "cleric",
            "target_id": "goblin",
            "effect_type": "damage",
            "applied_amount": 9,
        },
        source="dnd_sim.engine",
    )

    serialized = serialize_event(event)
    assert serialized == serialize_event(event)
    assert json.loads(serialized) == event


def test_owned_runtime_modules_define_module_level_loggers() -> None:
    missing = [
        str(path.relative_to(_REPO_ROOT))
        for path in _iter_owned_runtime_modules()
        if not _has_module_level_logger(path)
    ]
    assert not missing, f"Missing module-level logger definition in: {missing}"
