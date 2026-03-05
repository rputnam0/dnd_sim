from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dnd_sim.replay import load_replay_bundle
from dnd_sim.replay_schema import (
    GOLDEN_TRACE_MANIFEST_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)

MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = GOLDEN_TRACE_MANIFEST_SCHEMA_VERSION
MANIFEST_BUNDLE_SCHEMA_KEY = "bundle_schema_version"
REQUIRED_COVERAGE_KEYWORDS: tuple[str, ...] = ("combat", "hazard", "summon", "reaction", "world")


def _default_golden_dir() -> Path:
    return (Path(__file__).resolve().parents[2] / "artifacts" / "golden_traces").resolve()


def _bundle_paths(golden_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in golden_dir.glob("*.json")
        if path.is_file() and path.name != MANIFEST_FILE_NAME
    )


def _bundle_digest(path: Path) -> str:
    bundle = load_replay_bundle(path)
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _coverage_ok(bundle_paths: list[Path]) -> tuple[bool, dict[str, bool]]:
    coverage = {keyword: False for keyword in REQUIRED_COVERAGE_KEYWORDS}
    for path in bundle_paths:
        lowered = path.stem.lower()
        for keyword in coverage:
            if keyword in lowered:
                coverage[keyword] = True
    return all(coverage.values()), coverage


def _build_manifest(golden_dir: Path, bundle_paths: list[Path]) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        MANIFEST_BUNDLE_SCHEMA_KEY: REPLAY_BUNDLE_SCHEMA_VERSION,
        "bundles": {path.name: {"sha256": _bundle_digest(path)} for path in bundle_paths},
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def verify_golden_traces(
    *,
    golden_dir: Path,
    manifest_path: Path | None = None,
    update: bool = False,
) -> tuple[bool, str]:
    resolved_golden_dir = golden_dir.resolve()
    if not resolved_golden_dir.exists():
        return False, f"Golden trace directory does not exist: {resolved_golden_dir}"

    bundles = _bundle_paths(resolved_golden_dir)
    if not bundles:
        return False, f"No golden replay bundles found in {resolved_golden_dir}"

    coverage_ok, coverage = _coverage_ok(bundles)
    if not coverage_ok:
        return False, f"Golden trace corpus missing required coverage: {coverage}"

    resolved_manifest = (
        manifest_path.resolve()
        if manifest_path is not None
        else resolved_golden_dir / MANIFEST_FILE_NAME
    )
    generated_manifest = _build_manifest(resolved_golden_dir, bundles)

    if update:
        _write_manifest(resolved_manifest, generated_manifest)
        return True, f"Golden trace manifest updated at {resolved_manifest}"

    if not resolved_manifest.exists():
        return (
            False,
            f"Golden trace manifest missing: {resolved_manifest}. "
            "Run with --update to approve this corpus.",
        )

    raw_manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    if not isinstance(raw_manifest, dict):
        return False, f"Golden trace manifest must be a JSON object: {resolved_manifest}"

    schema_version = str(raw_manifest.get("schema_version", "")).strip()
    if schema_version != MANIFEST_SCHEMA_VERSION:
        return (
            False,
            f"Unsupported golden trace manifest schema_version '{schema_version}'. "
            f"Expected '{MANIFEST_SCHEMA_VERSION}'.",
        )

    bundle_schema_version = str(raw_manifest.get(MANIFEST_BUNDLE_SCHEMA_KEY, "")).strip()
    if bundle_schema_version != REPLAY_BUNDLE_SCHEMA_VERSION:
        return (
            False,
            f"Unsupported golden trace bundle schema_version '{bundle_schema_version}'. "
            f"Expected '{REPLAY_BUNDLE_SCHEMA_VERSION}'.",
        )

    entries = raw_manifest.get("bundles")
    if not isinstance(entries, dict):
        return False, f"Golden trace manifest 'bundles' must be an object: {resolved_manifest}"

    expected_names = sorted(entries.keys())
    actual_names = [path.name for path in bundles]
    if expected_names != actual_names:
        return (
            False,
            f"Golden trace manifest drift: bundle set mismatch. expected={expected_names} actual={actual_names}",
        )

    drifts: list[str] = []
    current_entries = generated_manifest["bundles"]
    for path in bundles:
        expected = entries.get(path.name, {})
        if not isinstance(expected, dict):
            drifts.append(f"{path.name}: manifest entry must be an object")
            continue
        expected_hash = str(expected.get("sha256", "")).strip()
        actual = current_entries.get(path.name, {})
        actual_hash = str(actual.get("sha256", "")).strip() if isinstance(actual, dict) else ""
        if expected_hash != actual_hash:
            drifts.append(f"{path.name}: expected {expected_hash} got {actual_hash}")

    if drifts:
        detail = "\n".join(f"- {row}" for row in drifts)
        return (
            False,
            "Golden trace drift detected.\n"
            f"{detail}\n"
            f"Run with --update to approve new baselines: {resolved_manifest}",
        )

    return True, f"Golden trace corpus verified for {resolved_golden_dir}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the golden replay trace corpus and fail on unapproved drift."
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=_default_golden_dir(),
        help="Path to the golden trace corpus directory.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional explicit manifest path. Defaults to <golden-dir>/manifest.json.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Approve current corpus content by rewriting manifest hashes.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ok, message = verify_golden_traces(
        golden_dir=args.golden_dir,
        manifest_path=args.manifest,
        update=args.update,
    )
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
