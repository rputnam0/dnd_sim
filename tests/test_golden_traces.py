from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "replay" / "verify_golden_traces.py"


def _golden_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "artifacts" / "golden_traces"


def _run_verify(*, golden_dir: Path, update: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(_script_path()), "--golden-dir", str(golden_dir)]
    if update:
        cmd.append("--update")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_golden_traces", _script_path())
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_golden_trace_corpus_covers_required_scenarios() -> None:
    golden_dir = _golden_dir()
    assert golden_dir.exists()

    bundle_files = sorted(
        path
        for path in golden_dir.glob("*.json")
        if path.name != "manifest.json" and path.is_file()
    )
    assert bundle_files

    keywords = {
        "combat": False,
        "hazard": False,
        "summon": False,
        "reaction": False,
        "world": False,
    }
    for path in bundle_files:
        lower_name = path.stem.lower()
        for keyword in keywords:
            if keyword in lower_name:
                keywords[keyword] = True

    assert all(keywords.values()), f"Missing required golden corpus coverage: {keywords}"


def test_verify_golden_traces_passes_for_repo_corpus() -> None:
    result = _run_verify(golden_dir=_golden_dir())
    assert result.returncode == 0, result.stdout + result.stderr


def test_verify_golden_traces_detects_drift_and_supports_update(tmp_path: Path) -> None:
    source = _golden_dir()
    target = tmp_path / "golden_traces"
    target.mkdir(parents=True, exist_ok=True)

    for path in source.glob("*.json"):
        target.joinpath(path.name).write_bytes(path.read_bytes())

    drift_file = next(path for path in target.glob("*.json") if path.name != "manifest.json")
    payload = json.loads(drift_file.read_text(encoding="utf-8"))
    payload["summary"]["run_id"] = "drifted_run_id"
    drift_file.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    drift_result = _run_verify(golden_dir=target)
    assert drift_result.returncode == 1
    assert "drift" in (drift_result.stdout + drift_result.stderr).lower()

    approve_result = _run_verify(golden_dir=target, update=True)
    assert approve_result.returncode == 0, approve_result.stdout + approve_result.stderr

    clean_result = _run_verify(golden_dir=target)
    assert clean_result.returncode == 0, clean_result.stdout + clean_result.stderr


def test_verify_path_hashes_each_bundle_once(tmp_path: Path) -> None:
    source = _golden_dir()
    target = tmp_path / "golden_traces"
    target.mkdir(parents=True, exist_ok=True)

    for path in source.glob("*.json"):
        target.joinpath(path.name).write_bytes(path.read_bytes())

    module = _load_verify_module()
    original_digest = module._bundle_digest
    calls = {"count": 0}

    def _counting_digest(path: Path) -> str:
        calls["count"] += 1
        return original_digest(path)

    module._bundle_digest = _counting_digest
    ok, message = module.verify_golden_traces(golden_dir=target)
    assert ok is True, message

    bundle_count = len([path for path in target.glob("*.json") if path.name != "manifest.json"])
    assert calls["count"] == bundle_count
