from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dnd_sim.capability_evidence import (
    CapabilityEvidenceError,
    CapabilityEvidenceTarget,
    SupportedPackEvidencePlan,
    build_supported_pack_evidence_plan,
    load_supported_capability_pack,
    load_test_evidence_registry,
    run_exact_pytest_nodes,
)

DEFAULT_MANIFEST_PATH = Path("artifacts/capabilities/manifest_2014.json")
DEFAULT_EVIDENCE_REGISTRY_PATH = Path("db/rules/2014/capability_test_evidence.json")
_REASON_CODE_PATTERN = re.compile(r"^[a-z0-9_]+$")
_EVIDENCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
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
    from dnd_sim.capability_manifest import (
        build_class_capability_manifest,
        build_feature_capability_manifest,
        build_item_capability_manifest,
        build_monster_capability_manifest,
        build_spell_capability_manifest,
        build_subclass_capability_manifest,
    )

    base = repo_root / "db" / "rules" / "2014"
    manifests = (
        build_spell_capability_manifest(spells_dir=base / "spells"),
        build_feature_capability_manifest(features_dir=base / "traits"),
        build_monster_capability_manifest(monsters_dir=base / "monsters"),
        build_item_capability_manifest(items_dir=base / "items"),
        build_class_capability_manifest(classes_dir=base / "classes"),
        build_subclass_capability_manifest(subclasses_dir=base / "subclasses"),
    )

    shipped_ids: set[str] = set()
    for manifest in manifests:
        for record in manifest.records:
            shipped_ids.add(record.content_id)
    return tuple(sorted(shipped_ids, key=str.casefold))


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


def _evidence_ids_or_issue(
    raw_record: Mapping[str, Any], *, content_id: str, issues: list[CapabilityIssue]
) -> tuple[str, ...]:
    raw_evidence_ids = raw_record.get("evidence_ids")
    if not isinstance(raw_evidence_ids, list):
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-003",
                message="evidence_ids must be an array of evidence identifier strings.",
                content_id=content_id,
            )
        )
        return ()

    evidence_ids: list[str] = []
    malformed = False
    for raw_evidence_id in raw_evidence_ids:
        if (
            not isinstance(raw_evidence_id, str)
            or _EVIDENCE_ID_PATTERN.fullmatch(raw_evidence_id) is None
        ):
            malformed = True
            continue
        evidence_ids.append(raw_evidence_id)
    if (
        malformed
        or len(set(evidence_ids)) != len(evidence_ids)
        or evidence_ids != sorted(evidence_ids, key=str.casefold)
    ):
        issues.append(
            CapabilityIssue(
                code="CAP-GATE-003",
                message=(
                    "evidence_ids must contain unique, canonically sorted evidence identifier "
                    "strings."
                ),
                content_id=content_id,
            )
        )
    return tuple(evidence_ids)


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
        if generated_at is not None and (
            not isinstance(generated_at, str) or not generated_at.strip()
        ):
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
        evidence_ids = _evidence_ids_or_issue(
            raw_record,
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
        if executable == blocked:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-010",
                    message="exactly one of executable or blocked must be true.",
                    content_id=content_id,
                )
            )
        if executable and not schema_valid:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-010",
                    message="executable content requires schema_valid=true.",
                    content_id=content_id,
                )
            )
        if tested and not executable:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-010",
                    message="tested content requires executable=true.",
                    content_id=content_id,
                )
            )
        if tested != bool(evidence_ids):
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-010",
                    message="states.tested must equal bool(evidence_ids).",
                    content_id=content_id,
                )
            )

        if strict and executable and not tested:
            issues.append(
                CapabilityIssue(
                    code="CAP-GATE-007",
                    message="strict mode requires executable content to have behavioral tests.",
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


def _repo_relative_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _supported_pack_manifest_targets(
    payload: Mapping[str, Any],
) -> tuple[
    tuple[CapabilityEvidenceTarget, ...],
    dict[str, Mapping[str, Any]],
    list[CapabilityIssue],
]:
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return (
            (),
            {},
            [
                CapabilityIssue(
                    code="CAP-PACK-001",
                    message="manifest payload must contain a records array for supported-pack verification.",
                )
            ],
        )

    targets: list[CapabilityEvidenceTarget] = []
    records_by_id: dict[str, Mapping[str, Any]] = {}
    issues: list[CapabilityIssue] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-001",
                    message=f"manifest record at index {index} is not a JSON object.",
                )
            )
            continue
        content_id = raw_record.get("content_id")
        states = raw_record.get("states")
        if (
            not isinstance(content_id, str)
            or not content_id.strip()
            or not isinstance(states, Mapping)
        ):
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-001",
                    message=(
                        f"manifest record at index {index} must have a content_id and states object."
                    ),
                )
            )
            continue
        normalized_id = content_id.strip()
        required_bools = {
            field_name: states.get(field_name)
            for field_name in ("schema_valid", "executable", "blocked")
        }
        if any(not isinstance(value, bool) for value in required_bools.values()):
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-001",
                    message=(
                        "supported-pack verification requires boolean schema_valid, "
                        "executable, and blocked states."
                    ),
                    content_id=normalized_id,
                )
            )
            continue
        if normalized_id in records_by_id:
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-001",
                    message="duplicate content_id found in manifest.",
                    content_id=normalized_id,
                )
            )
            continue
        records_by_id[normalized_id] = raw_record
        targets.append(
            CapabilityEvidenceTarget(
                content_id=normalized_id,
                schema_valid=required_bools["schema_valid"],
                executable=required_bools["executable"],
                blocked=required_bools["blocked"],
            )
        )
    return tuple(targets), records_by_id, issues


def verify_supported_pack_capabilities(
    *,
    repo_root: Path,
    manifest_path: Path,
    supported_pack_path: Path,
    evidence_registry_path: Path,
) -> tuple[SupportedPackEvidencePlan | None, list[CapabilityIssue]]:
    """Validate one declared support pack against manifest state and traceable evidence."""

    resolved_manifest_path = _repo_relative_path(repo_root, manifest_path)
    resolved_pack_path = _repo_relative_path(repo_root, supported_pack_path)
    resolved_registry_path = _repo_relative_path(repo_root, evidence_registry_path)
    try:
        payload = _manifest_payload_from_file(resolved_manifest_path)
        pack = load_supported_capability_pack(resolved_pack_path)
        registry = load_test_evidence_registry(resolved_registry_path)
    except (OSError, UnicodeError, ValueError) as exc:
        return None, [CapabilityIssue(code="CAP-PACK-001", message=str(exc))]

    targets, records_by_id, issues = _supported_pack_manifest_targets(payload)
    if issues:
        return None, issues

    try:
        plan = build_supported_pack_evidence_plan(
            pack=pack,
            registry=registry,
            targets=targets,
        )
    except CapabilityEvidenceError as exc:
        return None, [CapabilityIssue(code="CAP-PACK-001", message=str(exc))]

    evidence_ids_by_content: dict[str, tuple[str, ...]] = {}
    for evidence in registry.evidence:
        evidence_ids_by_content.setdefault(evidence.content_id, ())
        evidence_ids_by_content[evidence.content_id] = (
            *evidence_ids_by_content[evidence.content_id],
            evidence.evidence_id,
        )

    for entry in pack.entries:
        raw_record = records_by_id[entry.content_id]
        states = raw_record["states"]
        assert isinstance(states, Mapping)  # established by _supported_pack_manifest_targets
        state_violations: list[str] = []
        for field_name in ("cataloged", "schema_valid", "executable", "tested"):
            if states.get(field_name) is not True:
                state_violations.append(f"{field_name}=true")
        if states.get("blocked") is not False:
            state_violations.append("blocked=false")
        if states.get("unsupported_reason") is not None:
            state_violations.append("unsupported_reason=null")
        if state_violations:
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-002",
                    message=(
                        "supported-pack content requires green manifest state: "
                        + ", ".join(state_violations)
                    ),
                    content_id=entry.content_id,
                )
            )

        expected_evidence_ids = tuple(
            sorted(evidence_ids_by_content.get(entry.content_id, ()), key=str.casefold)
        )
        raw_evidence_ids = raw_record.get("evidence_ids")
        if raw_evidence_ids != list(expected_evidence_ids):
            issues.append(
                CapabilityIssue(
                    code="CAP-PACK-003",
                    message=(
                        "manifest evidence_ids must exactly match the sorted evidence registry "
                        f"entries for this content (expected: {list(expected_evidence_ids)!r})."
                    ),
                    content_id=entry.content_id,
                )
            )

    if issues:
        return None, issues
    return plan, []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify structural integrity and complete catalog coverage for shipped 2014 "
            "capability records. Optionally execute traceable evidence for one declared "
            "supported pack."
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
    verification_mode = parser.add_mutually_exclusive_group()
    verification_mode.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Legacy all-shipped strict mode: every shipped record must be executable+tested "
            "and must not remain blocked."
        ),
    )
    verification_mode.add_argument(
        "--supported-pack",
        type=Path,
        default=None,
        help=(
            "Path to a supported-pack JSON contract. Validate its manifest records and run "
            "the registry's exact behavioral evidence tests."
        ),
    )
    parser.add_argument(
        "--evidence-registry",
        type=Path,
        default=None,
        help=(
            "Optional evidence registry path for --supported-pack (defaults to "
            "db/rules/2014/capability_test_evidence.json below --repo-root)."
        ),
    )
    args = parser.parse_args(argv)

    if args.evidence_registry is not None and args.supported_pack is None:
        print("CAP-PACK-001: --evidence-registry requires --supported-pack.")
        return 1

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

    if args.supported_pack is not None:
        manifest_path = args.manifest_path or (args.repo_root / DEFAULT_MANIFEST_PATH)
        evidence_registry_path = (
            args.evidence_registry
            if args.evidence_registry is not None
            else DEFAULT_EVIDENCE_REGISTRY_PATH
        )
        plan, pack_issues = verify_supported_pack_capabilities(
            repo_root=args.repo_root,
            manifest_path=manifest_path,
            supported_pack_path=args.supported_pack,
            evidence_registry_path=evidence_registry_path,
        )
        if pack_issues:
            for issue in pack_issues:
                if issue.content_id is None:
                    print(f"{issue.code}: {issue.message}")
                else:
                    print(f"{issue.code} [{issue.content_id}]: {issue.message}")
            return 1
        assert plan is not None
        try:
            evidence_run = run_exact_pytest_nodes(
                plan.pytest_node_ids,
                repo_root=args.repo_root,
            )
        except CapabilityEvidenceError as exc:
            print(f"CAP-PACK-004: {exc}")
            return 1
        test_label = "test" if evidence_run.passed_count == 1 else "tests"
        print(
            f"Supported capability pack {plan.pack_id!r} passed with "
            f"{evidence_run.passed_count} exact behavioral evidence {test_label}."
        )
        return 0

    if args.strict:
        print("Strict capability support gate passed.")
    else:
        print(
            "Capability catalog structural integrity gate passed; "
            "blocked and untested records are permitted."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
