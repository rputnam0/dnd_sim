"""Traceable behavioral evidence for canonical content capability records.

This module deliberately does not import the capability manifest models.  It produces a small,
content-id keyed overlay that artifact tooling can apply later without making the runtime depend
on pytest or on repository test files.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVIDENCE_SCHEMA_VERSION = "1.0"
SUPPORTED_PACK_SCHEMA_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_REGISTRY_PATH = (
    REPO_ROOT / "db" / "rules" / "2014" / "capability_test_evidence.json"
)
DEFAULT_SUPPORTED_PACKS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "supported_packs"

_CONTENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*:\S+$")
_EVIDENCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RULESET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GLOB_CHARACTERS = frozenset("*?[")


class CapabilityEvidenceError(ValueError):
    """Raised when independently valid evidence inputs do not form a sound support claim."""


class _StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _normalized_nonempty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _validated_content_id(value: str) -> str:
    normalized = _normalized_nonempty(value, field_name="content_id")
    if _CONTENT_ID_RE.fullmatch(normalized) is None:
        raise ValueError("content_id must use canonical '<content_type>:<identifier>' syntax")
    return normalized


def _validated_slug(value: str, *, field_name: str) -> str:
    normalized = _normalized_nonempty(value, field_name=field_name)
    if _SLUG_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must use lowercase snake_case")
    return normalized


def _validated_ruleset(value: str) -> str:
    normalized = _normalized_nonempty(value, field_name="ruleset")
    if _RULESET_RE.fullmatch(normalized) is None:
        raise ValueError("ruleset contains unsupported characters")
    return normalized


def _validate_pytest_node_shape(node_id: str) -> str:
    normalized = _normalized_nonempty(node_id, field_name="pytest_node_id")
    if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
        raise CapabilityEvidenceError("pytest node ID contains control characters")

    segments = normalized.split("::")
    if len(segments) < 2 or any(not segment for segment in segments):
        raise CapabilityEvidenceError("pytest evidence must name an exact test leaf with '::'")

    path_text = segments[0]
    if "\\" in path_text or any(character in path_text for character in _GLOB_CHARACTERS):
        raise CapabilityEvidenceError("pytest test paths must not contain globs or backslashes")
    test_path = PurePosixPath(path_text)
    if test_path.is_absolute() or ".." in test_path.parts:
        raise CapabilityEvidenceError("pytest test paths must be safe repository-relative paths")
    if not test_path.parts or test_path.parts[0] != "tests" or test_path.suffix != ".py":
        raise CapabilityEvidenceError("pytest evidence paths must be Python files below tests/")

    leaf_name = segments[-1].split("[", maxsplit=1)[0]
    if not leaf_name.startswith("test_"):
        raise CapabilityEvidenceError("pytest evidence must name an exact test function leaf")
    return normalized


class EvidenceRecord(_StrictEvidenceModel):
    """One stable evidence identifier proving claims for exactly one content record."""

    evidence_id: str
    kind: Literal["pytest"]
    content_id: str
    claims: tuple[str, ...] = Field(min_length=1)
    pytest_node_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_id")
    @classmethod
    def validate_evidence_id(cls, value: str) -> str:
        normalized = _normalized_nonempty(value, field_name="evidence_id")
        if _EVIDENCE_ID_RE.fullmatch(normalized) is None:
            raise ValueError("evidence_id contains unsupported characters")
        return normalized

    @field_validator("content_id")
    @classmethod
    def validate_content_id(cls, value: str) -> str:
        return _validated_content_id(value)

    @field_validator("claims")
    @classmethod
    def validate_claims(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_validated_slug(value, field_name="claim") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate claims are not allowed")
        return normalized

    @field_validator("pytest_node_ids")
    @classmethod
    def validate_pytest_node_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            try:
                normalized.append(_validate_pytest_node_shape(value))
            except CapabilityEvidenceError as exc:
                raise ValueError(str(exc)) from exc
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate pytest_node_ids are not allowed")
        return tuple(normalized)


class CapabilityTestEvidenceRegistry(_StrictEvidenceModel):
    """Canonical mapping from stable evidence IDs to exact behavioral tests."""

    schema_version: Literal["1.0"]
    ruleset: str
    evidence: tuple[EvidenceRecord, ...] = Field(min_length=1)

    @field_validator("ruleset")
    @classmethod
    def validate_ruleset(cls, value: str) -> str:
        return _validated_ruleset(value)

    @model_validator(mode="after")
    def validate_uniqueness(self) -> CapabilityTestEvidenceRegistry:
        evidence_ids = [record.evidence_id for record in self.evidence]
        duplicate_evidence_ids = sorted(
            {value for value in evidence_ids if evidence_ids.count(value) > 1}
        )
        if duplicate_evidence_ids:
            raise ValueError("duplicate evidence_id entries: " + ", ".join(duplicate_evidence_ids))

        node_owners: dict[str, str] = {}
        for record in self.evidence:
            for node_id in record.pytest_node_ids:
                existing = node_owners.get(node_id)
                if existing is not None:
                    raise ValueError(
                        "pytest node cannot belong to more than one evidence record: "
                        f"{node_id} ({existing}, {record.evidence_id})"
                    )
                node_owners[node_id] = record.evidence_id
        return self


class SupportedPackEntry(_StrictEvidenceModel):
    """Required behavioral claims for one member of a declared supported pack."""

    content_id: str
    required_claims: tuple[str, ...] = Field(min_length=1)

    @field_validator("content_id")
    @classmethod
    def validate_content_id(cls, value: str) -> str:
        return _validated_content_id(value)

    @field_validator("required_claims")
    @classmethod
    def validate_required_claims(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_validated_slug(value, field_name="required_claim") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate required_claims are not allowed")
        return normalized


class SupportedCapabilityPack(_StrictEvidenceModel):
    """A nonempty, explicitly scoped content support contract."""

    schema_version: Literal["1.0"]
    pack_id: str
    ruleset: str
    support_contract: str
    entries: tuple[SupportedPackEntry, ...] = Field(min_length=1)

    @field_validator("pack_id")
    @classmethod
    def validate_pack_id(cls, value: str) -> str:
        return _validated_slug(value, field_name="pack_id")

    @field_validator("ruleset")
    @classmethod
    def validate_ruleset(cls, value: str) -> str:
        return _validated_ruleset(value)

    @field_validator("support_contract")
    @classmethod
    def validate_support_contract(cls, value: str) -> str:
        return _validated_slug(value, field_name="support_contract")

    @model_validator(mode="after")
    def validate_entry_uniqueness(self) -> SupportedCapabilityPack:
        content_ids = [entry.content_id for entry in self.entries]
        duplicates = sorted({value for value in content_ids if content_ids.count(value) > 1})
        if duplicates:
            raise ValueError("duplicate content_id pack entries: " + ", ".join(duplicates))
        return self


class CapabilityEvidenceTarget(_StrictEvidenceModel):
    """Minimal manifest-independent input needed to determine evidence eligibility."""

    content_id: str
    schema_valid: bool
    executable: bool
    blocked: bool

    @field_validator("content_id")
    @classmethod
    def validate_content_id(cls, value: str) -> str:
        return _validated_content_id(value)


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceOverlay:
    """Derived evidence fields for one canonical capability record."""

    content_id: str
    tested: bool
    evidence_ids: tuple[str, ...]
    claims: tuple[str, ...]
    pytest_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupportedPackEvidencePlan:
    """Resolved exact evidence that a strict supported-pack gate must execute."""

    pack_id: str
    ruleset: str
    content_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    pytest_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PytestEvidenceRun:
    """Successful result from executing an exact evidence node set."""

    node_ids: tuple[str, ...]
    passed_count: int


def load_test_evidence_registry(
    path: Path = DEFAULT_EVIDENCE_REGISTRY_PATH,
) -> CapabilityTestEvidenceRegistry:
    """Load a strict evidence registry from JSON."""

    return CapabilityTestEvidenceRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def load_supported_capability_pack(path: Path) -> SupportedCapabilityPack:
    """Load a strict supported-pack declaration from JSON."""

    return SupportedCapabilityPack.model_validate_json(path.read_text(encoding="utf-8"))


def build_evidence_overlay(
    *,
    targets: Iterable[CapabilityEvidenceTarget],
    registry: CapabilityTestEvidenceRegistry,
) -> dict[str, CapabilityEvidenceOverlay]:
    """Derive tested/evidence metadata without importing or modifying manifest models."""

    target_by_id: dict[str, CapabilityEvidenceTarget] = {}
    for target in targets:
        if target.content_id in target_by_id:
            raise CapabilityEvidenceError(
                f"duplicate capability target content_id: {target.content_id}"
            )
        target_by_id[target.content_id] = target

    evidence_by_content: dict[str, list[EvidenceRecord]] = {
        content_id: [] for content_id in target_by_id
    }
    for evidence in registry.evidence:
        target = target_by_id.get(evidence.content_id)
        if target is None:
            raise CapabilityEvidenceError(
                "evidence references unknown canonical content_id: " f"{evidence.content_id}"
            )
        if not target.schema_valid:
            raise CapabilityEvidenceError(
                f"evidence content must be schema-valid: {evidence.content_id}"
            )
        if not target.executable or target.blocked:
            raise CapabilityEvidenceError(
                "evidence content must be executable and unblocked: " f"{evidence.content_id}"
            )
        evidence_by_content[evidence.content_id].append(evidence)

    overlay: dict[str, CapabilityEvidenceOverlay] = {}
    for content_id in sorted(target_by_id, key=str.casefold):
        records = evidence_by_content[content_id]
        evidence_ids = tuple(sorted((record.evidence_id for record in records), key=str.casefold))
        claims = tuple(
            sorted(
                {claim for record in records for claim in record.claims},
                key=str.casefold,
            )
        )
        node_ids = tuple(
            sorted(
                {node_id for record in records for node_id in record.pytest_node_ids},
                key=str.casefold,
            )
        )
        overlay[content_id] = CapabilityEvidenceOverlay(
            content_id=content_id,
            tested=bool(evidence_ids),
            evidence_ids=evidence_ids,
            claims=claims,
            pytest_node_ids=node_ids,
        )
    return overlay


def build_supported_pack_evidence_plan(
    *,
    pack: SupportedCapabilityPack,
    registry: CapabilityTestEvidenceRegistry,
    targets: Iterable[CapabilityEvidenceTarget],
) -> SupportedPackEvidencePlan:
    """Resolve and validate all exact evidence required by a supported pack."""

    if pack.ruleset != registry.ruleset:
        raise CapabilityEvidenceError(
            f"supported-pack/evidence ruleset mismatch: {pack.ruleset} != {registry.ruleset}"
        )

    materialized_targets = tuple(targets)
    target_ids = {target.content_id for target in materialized_targets}
    overlay = build_evidence_overlay(targets=materialized_targets, registry=registry)
    evidence_by_id = {record.evidence_id: record for record in registry.evidence}

    selected_evidence_ids: set[str] = set()
    selected_node_ids: set[str] = set()
    content_ids: list[str] = []
    for entry in pack.entries:
        if entry.content_id not in target_ids:
            raise CapabilityEvidenceError(
                "supported pack references unknown canonical content_id: " f"{entry.content_id}"
            )
        content_overlay = overlay[entry.content_id]
        missing_claims = sorted(set(entry.required_claims) - set(content_overlay.claims))
        if missing_claims:
            raise CapabilityEvidenceError(
                f"{entry.content_id} is missing required claims: " + ", ".join(missing_claims)
            )

        content_ids.append(entry.content_id)
        for evidence_id in content_overlay.evidence_ids:
            evidence = evidence_by_id[evidence_id]
            if evidence.content_id != entry.content_id:  # defensive exact-content invariant
                raise CapabilityEvidenceError(
                    f"evidence {evidence_id} does not belong to {entry.content_id}"
                )
            selected_evidence_ids.add(evidence_id)
            selected_node_ids.update(evidence.pytest_node_ids)

    return SupportedPackEvidencePlan(
        pack_id=pack.pack_id,
        ruleset=pack.ruleset,
        content_ids=tuple(sorted(content_ids, key=str.casefold)),
        evidence_ids=tuple(sorted(selected_evidence_ids, key=str.casefold)),
        pytest_node_ids=tuple(sorted(selected_node_ids, key=str.casefold)),
    )


def validate_exact_pytest_node_id(node_id: str, *, repo_root: Path = REPO_ROOT) -> str:
    """Validate one exact, repository-contained pytest leaf node ID."""

    normalized = _validate_pytest_node_shape(node_id)
    path_text = normalized.split("::", maxsplit=1)[0]
    root = repo_root.resolve()
    resolved_path = (root / Path(path_text)).resolve()
    try:
        resolved_path.relative_to(root)
    except ValueError as exc:
        raise CapabilityEvidenceError("pytest test path escapes the repository root") from exc
    if not resolved_path.is_file():
        raise CapabilityEvidenceError(f"pytest evidence test file does not exist: {path_text}")
    return normalized


def _validated_node_set(node_ids: Iterable[str], *, repo_root: Path) -> tuple[str, ...]:
    normalized = tuple(
        validate_exact_pytest_node_id(node_id, repo_root=repo_root) for node_id in node_ids
    )
    if not normalized:
        raise CapabilityEvidenceError("at least one pytest evidence node is required")
    if len(set(normalized)) != len(normalized):
        raise CapabilityEvidenceError("duplicate pytest evidence node IDs are not allowed")
    return normalized


def _run_pytest_subprocess(
    args: list[str],
    *,
    repo_root: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapabilityEvidenceError(
            f"pytest evidence command exceeded {timeout_seconds:g} seconds"
        ) from exc


def collect_exact_pytest_nodes(
    node_ids: Iterable[str],
    *,
    repo_root: Path = REPO_ROOT,
    timeout_seconds: float = 60.0,
) -> tuple[str, ...]:
    """Collect evidence selectors and reject broad or ambiguously parameterized nodes."""

    normalized = _validated_node_set(node_ids, repo_root=repo_root)
    result = _run_pytest_subprocess(
        ["-o", "addopts=", "--collect-only", "-q", *normalized],
        repo_root=repo_root,
        timeout_seconds=timeout_seconds,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise CapabilityEvidenceError(f"pytest evidence collection failed: {detail}")

    collected = tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    )
    if len(collected) != len(set(collected)) or set(collected) != set(normalized):
        declared = ", ".join(normalized)
        actual = ", ".join(collected) or "<none>"
        raise CapabilityEvidenceError(
            "each evidence selector must resolve to one exact pytest leaf "
            f"(declared: {declared}; collected: {actual})"
        )
    return normalized


def _xml_test_cases(root: ET.Element) -> tuple[ET.Element, ...]:
    return tuple(element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "testcase")


def run_exact_pytest_nodes(
    node_ids: Iterable[str],
    *,
    repo_root: Path = REPO_ROOT,
    timeout_seconds: float = 60.0,
) -> PytestEvidenceRun:
    """Execute exact evidence nodes and require a true pass for every selected item."""

    normalized = collect_exact_pytest_nodes(
        node_ids,
        repo_root=repo_root,
        timeout_seconds=timeout_seconds,
    )
    with tempfile.TemporaryDirectory(prefix="dnd-sim-capability-evidence-") as temp_dir:
        report_path = Path(temp_dir) / "pytest-evidence.xml"
        result = _run_pytest_subprocess(
            [
                "-o",
                "addopts=",
                "-o",
                "xfail_strict=true",
                "-q",
                "-rA",
                f"--junitxml={report_path}",
                *normalized,
            ],
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise CapabilityEvidenceError(f"pytest evidence execution failed: {detail}")
        if not report_path.is_file():
            raise CapabilityEvidenceError("pytest evidence execution did not produce a report")

        test_cases = _xml_test_cases(ET.parse(report_path).getroot())
        non_passed = [
            case
            for case in test_cases
            if any(
                child.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"} for child in case
            )
        ]
        exceptional_outcomes = re.search(
            r"(?m)^(?:SKIPPED|XFAIL|XPASS)\b",
            result.stdout,
        )
        if len(test_cases) != len(normalized) or non_passed or exceptional_outcomes:
            raise CapabilityEvidenceError(
                "every pytest evidence node must pass; skipped or xfailed tests are not evidence"
            )

    return PytestEvidenceRun(node_ids=normalized, passed_count=len(normalized))


__all__ = [
    "DEFAULT_EVIDENCE_REGISTRY_PATH",
    "DEFAULT_SUPPORTED_PACKS_DIR",
    "CapabilityEvidenceError",
    "CapabilityEvidenceOverlay",
    "CapabilityEvidenceTarget",
    "CapabilityTestEvidenceRegistry",
    "EvidenceRecord",
    "PytestEvidenceRun",
    "SupportedCapabilityPack",
    "SupportedPackEntry",
    "SupportedPackEvidencePlan",
    "build_evidence_overlay",
    "build_supported_pack_evidence_plan",
    "collect_exact_pytest_nodes",
    "load_supported_capability_pack",
    "load_test_evidence_registry",
    "run_exact_pytest_nodes",
    "validate_exact_pytest_node_id",
]
