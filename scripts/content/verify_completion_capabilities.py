from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_MANIFEST_PATH = Path("artifacts/capabilities/manifest_2014.json")
_SCOPE_DIR_TO_TYPE = {
    "spells": "spell",
    "traits": "trait",
    "monsters": "monster",
}
_REASON_CODE_PATTERN = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True, slots=True)
class CapabilityIssue:
    code: str
    message: str
    content_id: str | None = None


def discover_shipped_2014_content_ids(repo_root: Path) -> tuple[str, ...]:
    shipped: list[str] = []
    base = repo_root / "db" / "rules" / "2014"
    for directory_name, content_type in _SCOPE_DIR_TO_TYPE.items():
        directory = base / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            shipped.append(f"{content_type}:{path.stem}")
    return tuple(shipped)


def _manifest_payload_from_file(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("manifest payload must be a JSON object")
    return payload


def _as_bool(raw: Any, *, field_name: str, content_id: str, issues: list[CapabilityIssue]) -> bool:
    if isinstance(raw, bool):
        return raw
    issues.append(
        CapabilityIssue(
            code="CAP-GATE-003",
            message=f"{field_name} must be a boolean.",
            content_id=content_id,
        )
    )
    return False


def verify_manifest_payload(
    payload: Mapping[str, Any], *, expected_content_ids: Sequence[str]
) -> list[CapabilityIssue]:
    issues: list[CapabilityIssue] = []

    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return [
            CapabilityIssue(
                code="CAP-GATE-002",
                message="manifest payload must contain a records array.",
            )
        ]

    expected_set = set(expected_content_ids)
    seen_ids: set[str] = set()

    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-003",
                    message=f"record at index {index} must be a JSON object.",
                )
            )
            continue

        raw_content_id = raw_record.get("content_id")
        if not isinstance(raw_content_id, str) or not raw_content_id.strip():
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-003",
                    message="record content_id must be a non-empty string.",
                )
            )
            continue
        content_id = raw_content_id.strip()

        if content_id in seen_ids:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-005",
                    message="duplicate content_id found in manifest.",
                    content_id=content_id,
                )
            )
            continue
        seen_ids.add(content_id)

        if content_id not in expected_set:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-006",
                    message="manifest contains content_id outside shipped 2014 scope.",
                    content_id=content_id,
                )
            )

        cataloged = _as_bool(
            raw_record.get("cataloged"),
            field_name="cataloged",
            content_id=content_id,
            issues=issues,
        )
        schema_valid = _as_bool(
            raw_record.get("schema_valid"),
            field_name="schema_valid",
            content_id=content_id,
            issues=issues,
        )
        executable = _as_bool(
            raw_record.get("executable"),
            field_name="executable",
            content_id=content_id,
            issues=issues,
        )
        tested = _as_bool(
            raw_record.get("tested"),
            field_name="tested",
            content_id=content_id,
            issues=issues,
        )
        blocked = _as_bool(
            raw_record.get("blocked"),
            field_name="blocked",
            content_id=content_id,
            issues=issues,
        )
        unsupported_reason = raw_record.get("unsupported_reason", "")

        if not cataloged:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-008",
                    message="content record must be cataloged for shipped scope.",
                    content_id=content_id,
                )
            )
        if not schema_valid:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-008",
                    message="schema_valid must be true for shipped scope.",
                    content_id=content_id,
                )
            )

        if executable == blocked:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-010",
                    message="exactly one of executable or blocked must be true.",
                    content_id=content_id,
                )
            )

        if executable and not tested:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-007",
                    message="executable content must also be tested.",
                    content_id=content_id,
                )
            )

        if blocked:
            reason = unsupported_reason.strip() if isinstance(unsupported_reason, str) else ""
            if not reason or not _REASON_CODE_PATTERN.fullmatch(reason):
                issues.append(
                    CapabilityIssue(
                        code="CAP-GATE-009",
                        message=(
                            "blocked content must include a single unsupported_reason "
                            "code using lowercase letters, digits, and underscores."
                        ),
                        content_id=content_id,
                    )
                )

        if executable and isinstance(unsupported_reason, str) and unsupported_reason.strip():
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-009",
                    message="executable content must not declare unsupported_reason.",
                    content_id=content_id,
                )
            )

    missing_ids = sorted(expected_set - seen_ids)
    if missing_ids:
        preview = ", ".join(missing_ids[:5])
        suffix = "..." if len(missing_ids) > 5 else ""
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-004",
                message=(
                    f"manifest is missing {len(missing_ids)} shipped 2014 records: "
                    f"{preview}{suffix}"
                ),
            )
        )

    return issues


def verify_completion_capabilities(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
    expected_content_ids: Iterable[str] | None = None,
) -> list[CapabilityIssue]:
    manifest = manifest_path or (repo_root / DEFAULT_MANIFEST_PATH)
    if not manifest.exists():
        return [
            CapabilityIssue(
                code="CAP-GATE-001",
                message=f"missing capability manifest at {manifest}.",
            )
        ]

    try:
        payload = _manifest_payload_from_file(manifest)
    except ValueError as exc:
        return [CapabilityIssue(code="CAP-GATE-002", message=str(exc))]

    expected_ids = tuple(expected_content_ids or discover_shipped_2014_content_ids(repo_root))
    return verify_manifest_payload(payload, expected_content_ids=expected_ids)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that shipped 2014 content is fully cataloged in the capability manifest "
            "and satisfies FIN-02 green gate rules."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root path.",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help="Optional explicit path to manifest JSON file.",
    )
    args = parser.parse_args(argv)

    issues = verify_completion_capabilities(
        args.repo_root,
        manifest_path=args.manifest_path,
    )
    if issues:
        for issue in issues:
            if issue.content_id is None:
                print(f"{issue.code}: {issue.message}")
            else:
                print(f"{issue.code} [{issue.content_id}]: {issue.message}")
        return 1

    print("Capability manifest completion gate passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
