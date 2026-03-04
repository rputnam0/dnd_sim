from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dnd_sim.characters import parse_class_levels

DEFAULT_TARGETS = ("river_line/db/characters",)
DEFAULT_REPORT_PATH = "scripts/migrations/class_level_payload_to_class_levels.report.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _iter_json_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_file() and target.suffix == ".json":
            files.append(target)
            continue
        if not target.exists():
            continue
        files.extend(path for path in target.rglob("*.json") if path.is_file())
    return sorted(set(files))


def _iter_object_nodes(payload: Any, *, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict):
        nodes: list[tuple[str, dict[str, Any]]] = [(path, payload)]
        for key in sorted(payload.keys(), key=lambda value: str(value)):
            nodes.extend(_iter_object_nodes(payload[key], path=f"{path}.{key}"))
        return nodes
    if isinstance(payload, list):
        nodes: list[tuple[str, dict[str, Any]]] = []
        for index, entry in enumerate(payload):
            nodes.extend(_iter_object_nodes(entry, path=f"{path}[{index}]"))
        return nodes
    return []


def _missing_class_levels(value: Any) -> bool:
    return not (isinstance(value, dict) and bool(value))


def migrate_json_payload(
    payload: Any,
    *,
    file_label: str,
) -> tuple[int, list[dict[str, str]]]:
    updated = 0
    failures: list[dict[str, str]] = []
    for json_path, node in _iter_object_nodes(payload):
        if "class_level" not in node:
            continue
        if not _missing_class_levels(node.get("class_levels")):
            continue
        class_level_text = str(node.get("class_level", "") or "")
        parsed = parse_class_levels(class_level_text)
        if parsed:
            node["class_levels"] = parsed
            updated += 1
            continue
        failures.append(
            {
                "file": file_label,
                "json_path": json_path,
                "class_level": class_level_text,
                "reason": "missing parseable class_level text",
            }
        )
    return updated, failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot codemod: fill missing class_levels from class_level text and report "
            "unparseable payloads."
        )
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="Target JSON file or directory (repeatable). Defaults to river_line/db/characters.",
    )
    parser.add_argument(
        "--report",
        default=DEFAULT_REPORT_PATH,
        help="Relative path for deterministic failure report JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute updates and report failures without writing any JSON files.",
    )
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    target_paths = [root / value for value in (args.targets or list(DEFAULT_TARGETS))]
    files = _iter_json_files(target_paths)

    total_updated = 0
    files_updated = 0
    failures: list[dict[str, str]] = []

    for path in files:
        payload = _load_json(path)
        relative_label = str(path.relative_to(root))
        updated, file_failures = migrate_json_payload(payload, file_label=relative_label)
        if updated > 0:
            total_updated += updated
            files_updated += 1
            if not args.dry_run:
                _dump_json(path, payload)
        failures.extend(file_failures)

    failures = sorted(
        failures,
        key=lambda row: (row["file"], row["json_path"], row["class_level"], row["reason"]),
    )
    report_payload = {
        "dry_run": bool(args.dry_run),
        "files_scanned": len(files),
        "files_updated": files_updated,
        "payloads_updated": total_updated,
        "failures": failures,
    }
    report_path = root / args.report
    if not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _dump_json(report_path, report_payload)

    print(f"files_scanned={len(files)}")
    print(f"files_updated={files_updated}")
    print(f"payloads_updated={total_updated}")
    print(f"failures={len(failures)}")
    if not args.dry_run:
        print(f"report={report_path.relative_to(root)}")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
