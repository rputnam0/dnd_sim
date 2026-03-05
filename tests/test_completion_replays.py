from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
COMBAT_CORPUS_DIR = REPO_ROOT / "artifacts/golden_traces"
WORLD_CORPUS_DIR = REPO_ROOT / "artifacts/world_regressions"
REQUIRED_KEYS = ("scenario_id", "seed", "input", "trace", "outcome", "deterministic_digest")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _compute_replay_digest(payload: dict[str, Any]) -> str:
    material = {
        "seed": payload["seed"],
        "input": payload["input"],
        "trace": payload["trace"],
        "outcome": payload["outcome"],
    }
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _load_replay_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    missing_keys = [key for key in REQUIRED_KEYS if key not in payload]
    if missing_keys:
        raise ValueError(f"{path} missing required keys: {', '.join(missing_keys)}")
    if not isinstance(payload["seed"], int) or isinstance(payload["seed"], bool):
        raise ValueError(f"{path} field 'seed' must be an integer")
    if payload["seed"] < 0:
        raise ValueError(f"{path} field 'seed' must be >= 0")
    for key in ("scenario_id", "deterministic_digest"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"{path} field '{key}' must be a non-empty string")
    return payload


def evaluate_replay_corpus_gate(
    combat_dir: Path,
    world_dir: Path,
    *,
    approved_drift_ids: set[str] | None = None,
) -> list[str]:
    approved = approved_drift_ids or set()
    issues: list[str] = []
    seen_ids: set[str] = set()

    corpus_pairs = (
        ("combat", combat_dir),
        ("world", world_dir),
    )
    for label, corpus_dir in corpus_pairs:
        if not corpus_dir.exists():
            issues.append(f"REPLAY-GATE-{label.upper()}-001 missing corpus directory: {corpus_dir}")
            continue
        if not corpus_dir.is_dir():
            issues.append(
                f"REPLAY-GATE-{label.upper()}-002 corpus path is not a directory: {corpus_dir}"
            )
            continue

        scenario_files = tuple(sorted(corpus_dir.glob("*.json")))
        if not scenario_files:
            issues.append(
                f"REPLAY-GATE-{label.upper()}-003 no replay scenarios found in: {corpus_dir}"
            )
            continue

        for scenario_path in scenario_files:
            try:
                payload = _load_replay_payload(scenario_path)
            except ValueError as error:
                issues.append(f"REPLAY-GATE-{label.upper()}-004 {error}")
                continue

            scenario_id = payload["scenario_id"].strip()
            if scenario_id in seen_ids:
                issues.append(
                    f"REPLAY-GATE-ID-001 duplicate scenario_id '{scenario_id}' in {scenario_path}"
                )
            seen_ids.add(scenario_id)

            computed_digest = _compute_replay_digest(payload)
            if computed_digest != payload["deterministic_digest"]:
                if scenario_id not in approved:
                    issues.append(
                        f"REPLAY-GATE-DIFF-001 unapproved replay drift for '{scenario_id}' "
                        f"in {scenario_path.name}"
                    )
    return issues


def test_repository_corpus_passes_deterministic_replay_gate() -> None:
    issues = evaluate_replay_corpus_gate(COMBAT_CORPUS_DIR, WORLD_CORPUS_DIR)
    assert issues == []


def test_combat_replay_gate_detects_unapproved_diff(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    scenario_path = combat_dir / "combat_duel_fixed_seed.json"
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["outcome"]["rounds"] = 3
    scenario_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(combat_dir, world_dir)
    assert any("REPLAY-GATE-DIFF-001" in issue for issue in issues)


def test_world_replay_gate_detects_unapproved_diff(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    scenario_path = world_dir / "world_patrol_hazard_fixed_seed.json"
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["trace"].append(
        {
            "step": 5,
            "event": "camp",
            "elapsed_minutes": 60,
        }
    )
    scenario_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(combat_dir, world_dir)
    assert any("REPLAY-GATE-DIFF-001" in issue for issue in issues)


def test_diff_approval_path_allows_explicitly_approved_drift(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    scenario_path = combat_dir / "combat_duel_fixed_seed.json"
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["trace"][0]["damage"] = 7
    scenario_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(
        combat_dir,
        world_dir,
        approved_drift_ids={"combat_duel_fixed_seed"},
    )
    assert issues == []
