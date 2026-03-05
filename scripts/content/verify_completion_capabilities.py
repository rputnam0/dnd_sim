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
_STATE_BOOL_FIELDS = (
    "cataloged",
    "schema_valid",
    "executable",
    "tested",
    "blocked",
)
_LEGACY_FLAT_STATE_FIELDS = _STATE_BOOL_FIELDS + ("unsupported_reason",)


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


def _unsupported_reason_or_issue(
    raw_states: Mapping[str, Any], *, content_id: str, issues: list[CapabilityIssue]
) -> str | None:
    if "unsupported_reason" not in raw_states:
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-003",
                message="states.unsupported_reason must be present (null allowed when blocked=false).",
                content_id=content_id,
            )
        )
        return None
    raw_reason = raw_states["unsupported_reason"]
    if raw_reason is None:
        return None
    if isinstance(raw_reason, str):
        return raw_reason
    issues.append(
        CapabilityIssue(
            code="CAP-GATE-003",
            message="states.unsupported_reason must be null or a string.",
            content_id=content_id,
        )
    )
    return ""


def verify_manifest_payload(
    payload: Mapping[str, Any], *, expected_content_ids: Sequence[str], strict: bool = False
) -> list[CapabilityIssue]:
    issues: list[CapabilityIssue] = []

    manifest_version = payload.get("manifest_version")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-002",
                message="manifest payload must declare non-empty manifest_version.",
            )
        )
    if "generated_at" in payload:
        generated_at = payload.get("generated_at")
        if generated_at is not None and (not isinstance(generated_at, str) or not generated_at.strip()):
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-002",
                    message="generated_at must be null or a non-empty string when provided.",
                )
            )

    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-002",
                message="manifest payload must contain a records array.",
            )
        )
        return issues

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

        legacy_fields = sorted(name for name in _LEGACY_FLAT_STATE_FIELDS if name in raw_record)
        if legacy_fields:
            joined = ", ".join(legacy_fields)
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-003",
                    message=(
                        "legacy flat capability fields are not allowed; use record.states.* only "
                        f"(found: {joined})."
                    ),
                    content_id=content_id,
                )
            )

        raw_states = raw_record.get("states")
        if not isinstance(raw_states, Mapping):
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-003",
                    message="record states must be a JSON object.",
                    content_id=content_id,
                )
            )
            raw_states = {}

        cataloged = _as_bool(
            raw_states.get("cataloged"),
            field_name="states.cataloged",
            content_id=content_id,
            issues=issues,
        )
        schema_valid = _as_bool(
            raw_states.get("schema_valid"),
            field_name="states.schema_valid",
            content_id=content_id,
            issues=issues,
        )
        executable = _as_bool(
            raw_states.get("executable"),
            field_name="states.executable",
            content_id=content_id,
            issues=issues,
        )
        tested = _as_bool(
            raw_states.get("tested"),
            field_name="states.tested",
            content_id=content_id,
            issues=issues,
        )
        blocked = _as_bool(
            raw_states.get("blocked"),
            field_name="states.blocked",
            content_id=content_id,
            issues=issues,
        )
        unsupported_reason = _unsupported_reason_or_issue(
            raw_states,
            content_id=content_id,
            issues=issues,
        )

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

        if strict:
            strict_violations: list[str] = []
            if blocked:
                strict_violations.append("blocked=true")
            if not executable:
                strict_violations.append("executable=false")
            if not tested:
                strict_violations.append("tested=false")
            if unsupported_reason is not None:
                strict_violations.append("unsupported_reason must be null")
            if strict_violations:
                issues.append(
                    CapabilityIssue(
                        code="CAP-GATE-011",
                        message=(
                            "strict mode requires fully green shipped records "
                            "(cataloged/schema_valid/executable/tested and unblocked): "
                            + ", ".join(strict_violations)
                        ),
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
    strict: bool = False,
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
    return verify_manifest_payload(payload, expected_content_ids=expected_ids, strict=strict)


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
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Enable strict FIN-02 mode: every shipped record must be executable+tested and "
            "must not remain blocked."
        ),
    )
    args = parser.parse_args(argv)

    issues = verify_completion_capabilities(
        args.repo_root,
        manifest_path=args.manifest_path,
        strict=args.strict,
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
