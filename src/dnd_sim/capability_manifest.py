from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MANIFEST_VERSION = "1.0"
CAPABILITY_STATE_KEYS = (
    "cataloged",
    "schema_valid",
    "executable",
    "tested",
    "blocked",
    "unsupported_reason",
)


class CapabilityStates(BaseModel):
    """Canonical capability state set for each manifest record."""

    model_config = ConfigDict(extra="forbid")

    cataloged: bool
    schema_valid: bool
    executable: bool
    tested: bool
    blocked: bool
    unsupported_reason: str | None = None

    @field_validator("unsupported_reason")
    @classmethod
    def validate_unsupported_reason_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("unsupported_reason must be non-empty when provided")
        return normalized

    @model_validator(mode="after")
    def validate_blocked_reason_consistency(self) -> CapabilityStates:
        if self.blocked and self.unsupported_reason is None:
            raise ValueError("blocked records must declare unsupported_reason")
        if not self.blocked and self.unsupported_reason is not None:
            raise ValueError("unsupported_reason is only allowed when blocked is true")
        return self


class CapabilityRecord(BaseModel):
    """Single manifest record for one canonical content item."""

    model_config = ConfigDict(extra="forbid")

    content_id: str
    content_type: str
    states: CapabilityStates

    @field_validator("content_id", "content_type")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be non-empty")
        return normalized


class CapabilityManifest(BaseModel):
    """Canonical manifest schema for capability support state tracking."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: str = MANIFEST_VERSION
    generated_at: str | None = None
    records: list[CapabilityRecord] = Field(default_factory=list)

    @field_validator("manifest_version")
    @classmethod
    def validate_manifest_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("manifest_version must be non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_record_uniqueness_and_order(self) -> CapabilityManifest:
        seen_ids: set[str] = set()
        duplicates: set[str] = set()
        for record in self.records:
            if record.content_id in seen_ids:
                duplicates.add(record.content_id)
            seen_ids.add(record.content_id)
        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate content_id entries: {duplicate_list}")

        self.records = sorted(
            self.records,
            key=lambda row: (row.content_type.casefold(), row.content_id.casefold()),
        )
        return self


def build_manifest(
    *,
    records: list[CapabilityRecord | dict[str, Any]],
    manifest_version: str = MANIFEST_VERSION,
    generated_at: str | None = None,
) -> CapabilityManifest:
    """Build and validate a canonical manifest from record payloads."""

    normalized_records = [CapabilityRecord.model_validate(row) for row in records]
    return CapabilityManifest(
        manifest_version=manifest_version,
        generated_at=generated_at,
        records=normalized_records,
    )


def manifest_to_json_text(manifest: CapabilityManifest) -> str:
    """Return canonical manifest JSON with deterministic key and record ordering."""

    canonical_manifest = CapabilityManifest.model_validate(manifest.model_dump(mode="json"))
    payload = canonical_manifest.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def read_manifest(path: Path) -> CapabilityManifest:
    """Load and validate a manifest from a JSON file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return CapabilityManifest.model_validate(payload)


def write_manifest(manifest: CapabilityManifest, path: Path) -> None:
    """Write a validated manifest to disk in canonical deterministic JSON format."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest_to_json_text(manifest), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit canonical capability manifest JSON with deterministic ordering and key layout."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional source JSON manifest to normalize and rewrite.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Output manifest JSON path.")
    parser.add_argument(
        "--manifest-version",
        default=MANIFEST_VERSION,
        help="Manifest version for empty-manifest emission when --input is not provided.",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Optional generated_at string for empty-manifest emission.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.input is not None:
        manifest = read_manifest(args.input)
    else:
        manifest = build_manifest(
            records=[],
            manifest_version=args.manifest_version,
            generated_at=args.generated_at,
        )

    out_path = args.out.resolve()
    write_manifest(manifest, out_path)
    print(f"Capability manifest written: {out_path}")


if __name__ == "__main__":
    main()
