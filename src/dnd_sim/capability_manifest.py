from __future__ import annotations

import argparse
from functools import lru_cache
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnd_sim.mechanics_schema import (
    EXECUTABLE_EFFECT_TYPES,
    SPELL_METADATA_EFFECT_TYPES,
    validate_rule_mechanics_payload,
)
from dnd_sim.spells import canonicalize_spell_payload, slugify_spell_name

MANIFEST_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MONSTERS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "monsters"
DEFAULT_FEATURES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
DEFAULT_SPELLS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "spells"
MONSTER_POLICY_PATH = REPO_ROOT / "db" / "rules" / "2014" / "monster_capability_policy.json"
CAPABILITY_STATE_KEYS = (
    "cataloged",
    "schema_valid",
    "executable",
    "tested",
    "blocked",
    "unsupported_reason",
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
FEATURE_SUPPORT_STATES = {"supported", "unsupported"}


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
    runtime_hook_family: str | None = None
    support_state: str | None = None

    @field_validator("content_id", "content_type")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be non-empty")
        return normalized

    @field_validator("runtime_hook_family", "support_state")
    @classmethod
    def validate_optional_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be non-empty when provided")
        return normalized

    @model_validator(mode="after")
    def validate_support_state_consistency(self) -> CapabilityRecord:
        if self.support_state is None:
            return self
        normalized = self.support_state.strip().lower()
        if normalized not in FEATURE_SUPPORT_STATES:
            raise ValueError(f"unsupported support_state: {self.support_state}")
        self.support_state = normalized
        if normalized == "supported" and self.states.blocked:
            raise ValueError("support_state supported cannot map to blocked states")
        if normalized == "unsupported" and not self.states.blocked:
            raise ValueError("support_state unsupported must map to blocked states")
        if normalized == "unsupported" and self.states.unsupported_reason is None:
            raise ValueError("unsupported records must declare states.unsupported_reason")
        return self


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


class MonsterCapabilityPolicy(BaseModel):
    """Rules for mapping monster payload entries to capability support states."""

    model_config = ConfigDict(extra="forbid")

    supported_action_types: set[str]
    supported_action_costs: set[str]
    unsupported_reason_codes: set[str] = Field(default_factory=set)

    @field_validator(
        "supported_action_types",
        "supported_action_costs",
        "unsupported_reason_codes",
        mode="before",
    )
    @classmethod
    def normalize_string_sets(cls, value: Any) -> set[str]:
        if value is None:
            return set()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("policy entries must be an array of strings")
        normalized: set[str] = set()
        for item in value:
            text = str(item).strip().lower()
            if text:
                normalized.add(text)
        return normalized


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


@lru_cache(maxsize=1)
def load_monster_capability_policy(path: Path | None = None) -> MonsterCapabilityPolicy:
    source = (path or MONSTER_POLICY_PATH).resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return MonsterCapabilityPolicy.model_validate(payload)


def _slug_token(value: Any, fallback: str) -> str:
    text = str(value).strip().lower()
    text = _SLUG_RE.sub("_", text).strip("_")
    return text or fallback


def _supported_states() -> CapabilityStates:
    return CapabilityStates(
        cataloged=True,
        schema_valid=True,
        executable=True,
        tested=True,
        blocked=False,
        unsupported_reason=None,
    )


def _blocked_states(*, reason: str, schema_valid: bool) -> CapabilityStates:
    return CapabilityStates(
        cataloged=True,
        schema_valid=schema_valid,
        executable=False,
        tested=False,
        blocked=True,
        unsupported_reason=reason,
    )


def _monster_identifier(payload: dict[str, Any], *, index: int) -> str:
    identity = payload.get("identity")
    if isinstance(identity, dict):
        candidate = identity.get("enemy_id") or identity.get("name")
        if candidate:
            return _slug_token(candidate, f"monster_{index}")

    if payload.get("name"):
        return _slug_token(payload.get("name"), f"monster_{index}")
    return f"monster_{index}"


def load_monster_payloads(monsters_dir: Path = DEFAULT_MONSTERS_DIR) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(monsters_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def load_feature_payloads(features_dir: Path = DEFAULT_FEATURES_DIR) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(features_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        normalized = dict(payload)
        normalized["_manifest_path"] = str(path)
        payloads.append(normalized)
    return payloads


def load_spell_payloads(spells_dir: Path = DEFAULT_SPELLS_DIR) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(spells_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        normalized = canonicalize_spell_payload(payload, source_path=path)
        normalized["_manifest_path"] = str(path)
        payloads.append(normalized)
    return payloads


def _feature_content_type(payload: dict[str, Any]) -> str:
    source_type = str(payload.get("source_type", "")).strip().lower()
    if source_type == "feat":
        return "feat"
    if source_type == "background":
        return "background"
    if source_type == "species":
        return "species"
    return "trait"


def _feature_identifier(payload: dict[str, Any], *, index: int) -> str:
    explicit = str(payload.get("content_id", "")).strip()
    if explicit:
        return explicit

    path_hint = str(payload.get("_manifest_path", "")).strip()
    if path_hint:
        stem = Path(path_hint).stem
        token = _slug_token(stem, f"feature_{index}")
        if token:
            return token

    if payload.get("name"):
        return _slug_token(payload.get("name"), f"feature_{index}")
    return f"feature_{index}"


def _feature_hook_family_and_state(payload: dict[str, Any]) -> tuple[str, str, str | None, bool]:
    if not str(payload.get("name", "")).strip():
        return "invalid", "unsupported", "missing_feature_name", False

    mechanics = payload.get("mechanics")
    if mechanics is None:
        return "narrative", "unsupported", "missing_runtime_hook_family", True
    if not isinstance(mechanics, list):
        return "invalid", "unsupported", "malformed_mechanics_payload", False
    if not mechanics:
        return "narrative", "unsupported", "missing_runtime_hook_family", True

    has_effect_type = False
    has_meta_type = False
    for row in mechanics:
        if not isinstance(row, dict):
            return "invalid", "unsupported", "malformed_mechanics_payload", False
        if str(row.get("effect_type", "")).strip():
            has_effect_type = True
        if str(row.get("meta_type", "")).strip():
            has_meta_type = True

    if has_effect_type and has_meta_type:
        return "effect_meta", "supported", None, True
    if has_effect_type:
        return "effect", "supported", None, True
    if has_meta_type:
        return "meta", "supported", None, True
    return "narrative", "unsupported", "missing_runtime_hook_family", True


def build_feature_capability_records(
    *,
    feature_payloads: list[dict[str, Any]],
) -> list[CapabilityRecord]:
    records: list[CapabilityRecord] = []
    for index, payload in enumerate(feature_payloads, start=1):
        content_type = _feature_content_type(payload)
        identifier = _feature_identifier(payload, index=index)
        content_id = identifier if ":" in identifier else f"{content_type}:{identifier}"
        runtime_hook_family, support_state, unsupported_reason, schema_valid = (
            _feature_hook_family_and_state(payload)
        )

        states = (
            _supported_states()
            if support_state == "supported"
            else _blocked_states(
                reason=unsupported_reason or "unsupported_feature_payload",
                schema_valid=schema_valid,
            )
        )

        records.append(
            CapabilityRecord(
                content_id=content_id,
                content_type=content_type,
                runtime_hook_family=runtime_hook_family,
                support_state=support_state,
                states=states,
            )
        )
    return records


def build_feature_capability_manifest(
    *,
    feature_payloads: list[dict[str, Any]] | None = None,
    features_dir: Path = DEFAULT_FEATURES_DIR,
    manifest_version: str = MANIFEST_VERSION,
    generated_at: str | None = None,
) -> CapabilityManifest:
    payloads = (
        feature_payloads if feature_payloads is not None else load_feature_payloads(features_dir)
    )
    records = build_feature_capability_records(feature_payloads=payloads)
    return build_manifest(
        records=records,
        manifest_version=manifest_version,
        generated_at=generated_at,
    )


def _spell_identifier(payload: dict[str, Any], *, index: int) -> str:
    explicit = str(payload.get("content_id", "")).strip()
    if explicit:
        return explicit

    path_hint = str(payload.get("_manifest_path", "")).strip()
    if path_hint:
        stem = Path(path_hint).stem
        token = _slug_token(stem, f"spell_{index}")
        if token:
            return token

    spell_name = str(payload.get("name", "")).strip()
    if spell_name:
        return slugify_spell_name(spell_name) or f"spell_{index}"
    return f"spell_{index}"


def _spell_supports_extra_damage_runtime(payload: dict[str, Any]) -> bool:
    name = str(payload.get("name", "")).strip().lower()
    # Runtime currently resolves `extra_damage` through pending smite setup flow.
    return bool(name) and name.endswith("smite")


def _spell_mechanics_executable(payload: dict[str, Any], mechanics: list[Any]) -> bool:
    has_runtime_effect = False
    for row in mechanics:
        if not isinstance(row, dict):
            return False
        effect_type = str(row.get("effect_type", "")).strip().lower()
        if not effect_type:
            return False
        if effect_type in SPELL_METADATA_EFFECT_TYPES:
            continue
        if effect_type == "extra_damage":
            if not _spell_supports_extra_damage_runtime(payload):
                return False
            has_runtime_effect = True
            continue
        if effect_type not in EXECUTABLE_EFFECT_TYPES:
            return False
        has_runtime_effect = True
    return has_runtime_effect


def _spell_hook_family_and_state(payload: dict[str, Any]) -> tuple[str, str, str | None, bool]:
    spell_name = str(payload.get("name", "")).strip()
    if not spell_name:
        return "invalid", "unsupported", "missing_spell_name", False

    mechanics = payload.get("mechanics")
    if mechanics is None:
        return "narrative", "unsupported", "missing_runtime_mechanics", True
    if not isinstance(mechanics, list):
        return "invalid", "unsupported", "malformed_mechanics_payload", False
    if not mechanics:
        return "narrative", "unsupported", "missing_runtime_mechanics", True

    issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
    if issues:
        if any("unsupported" in issue for issue in issues):
            return "effect", "unsupported", "unsupported_effect_type", True
        return "invalid", "unsupported", "invalid_mechanics_schema", False

    if not _spell_mechanics_executable(payload, mechanics):
        return "effect", "unsupported", "non_executable_mechanics", True
    return "effect", "supported", None, True


def build_spell_capability_records(
    *,
    spell_payloads: list[dict[str, Any]],
) -> list[CapabilityRecord]:
    records: list[CapabilityRecord] = []
    for index, payload in enumerate(spell_payloads, start=1):
        identifier = _spell_identifier(payload, index=index)
        content_id = identifier if ":" in identifier else f"spell:{identifier}"
        runtime_hook_family, support_state, unsupported_reason, schema_valid = (
            _spell_hook_family_and_state(payload)
        )

        states = (
            _supported_states()
            if support_state == "supported"
            else _blocked_states(
                reason=unsupported_reason or "unsupported_spell_payload",
                schema_valid=schema_valid,
            )
        )

        records.append(
            CapabilityRecord(
                content_id=content_id,
                content_type="spell",
                runtime_hook_family=runtime_hook_family,
                support_state=support_state,
                states=states,
            )
        )
    return records


def build_spell_capability_manifest(
    *,
    spell_payloads: list[dict[str, Any]] | None = None,
    spells_dir: Path = DEFAULT_SPELLS_DIR,
    manifest_version: str = MANIFEST_VERSION,
    generated_at: str | None = None,
) -> CapabilityManifest:
    payloads = spell_payloads if spell_payloads is not None else load_spell_payloads(spells_dir)
    records = build_spell_capability_records(spell_payloads=payloads)
    return build_manifest(
        records=records,
        manifest_version=manifest_version,
        generated_at=generated_at,
    )


def _action_entry_states(
    *,
    action_payload: dict[str, Any],
    policy: MonsterCapabilityPolicy,
    default_action_cost: str,
) -> CapabilityStates:
    action_name = str(action_payload.get("name", "")).strip()
    if not action_name:
        return _blocked_states(reason="missing_action_name", schema_valid=False)

    action_type = str(action_payload.get("action_type", "")).strip().lower()
    if not action_type:
        return _blocked_states(reason="missing_action_type", schema_valid=False)
    if action_type not in policy.supported_action_types:
        return _blocked_states(reason="unsupported_action_type", schema_valid=True)

    action_cost = str(action_payload.get("action_cost", default_action_cost)).strip().lower()
    if not action_cost:
        return _blocked_states(reason="missing_action_cost", schema_valid=False)
    if action_cost not in policy.supported_action_costs:
        return _blocked_states(reason="unsupported_action_cost", schema_valid=True)

    return _supported_states()


def _monster_base_states(payload: dict[str, Any]) -> CapabilityStates:
    identity = payload.get("identity")
    stat_block = payload.get("stat_block")
    if not isinstance(identity, dict):
        return _blocked_states(reason="missing_monster_identity", schema_valid=False)
    if not str(identity.get("enemy_id", "")).strip():
        return _blocked_states(reason="missing_monster_identity", schema_valid=False)
    if not isinstance(stat_block, dict):
        return _blocked_states(reason="missing_monster_stat_block", schema_valid=False)
    return _supported_states()


def _add_action_family_records(
    *,
    records: list[CapabilityRecord],
    monster_id: str,
    family: str,
    entries: list[Any],
    policy: MonsterCapabilityPolicy,
    default_action_cost: str,
) -> None:
    family_slug = family.split("monster_", 1)[-1]
    for index, entry in enumerate(entries, start=1):
        fallback_name = f"{family_slug}_{index}"
        if isinstance(entry, dict):
            action_name = str(entry.get("name", "")).strip()
            token = _slug_token(action_name, fallback_name)
            states = _action_entry_states(
                action_payload=entry,
                policy=policy,
                default_action_cost=default_action_cost,
            )
            has_recharge = "recharge" in entry
            recharge_text = str(entry.get("recharge", "")).strip()
        else:
            token = fallback_name
            states = _blocked_states(reason="malformed_action_payload", schema_valid=False)
            has_recharge = False
            recharge_text = ""

        if states.blocked and states.unsupported_reason not in policy.unsupported_reason_codes:
            states = _blocked_states(reason="unsupported_action_payload", schema_valid=False)

        records.append(
            CapabilityRecord(
                content_id=f"{family}:{monster_id}:{token}:{index}",
                content_type=family,
                states=states,
            )
        )

        if not has_recharge:
            continue
        if not recharge_text:
            recharge_states = _blocked_states(reason="malformed_recharge_entry", schema_valid=False)
        elif states.blocked:
            # Recharge support depends on the source action being supported.
            recharge_states = _blocked_states(
                reason="source_action_blocked",
                schema_valid=states.schema_valid,
            )
        else:
            recharge_states = _supported_states()
        if (
            recharge_states.blocked
            and recharge_states.unsupported_reason not in policy.unsupported_reason_codes
        ):
            recharge_states = _blocked_states(
                reason="unsupported_action_payload", schema_valid=False
            )
        records.append(
            CapabilityRecord(
                content_id=f"monster_recharge:{monster_id}:{token}:{index}",
                content_type="monster_recharge",
                states=recharge_states,
            )
        )


def _add_innate_spellcasting_records(
    *,
    records: list[CapabilityRecord],
    monster_id: str,
    entries: list[Any],
    policy: MonsterCapabilityPolicy,
) -> None:
    for index, entry in enumerate(entries, start=1):
        fallback = f"innate_spell_{index}"
        if isinstance(entry, dict):
            spell_name = str(entry.get("spell", "")).strip()
            token = _slug_token(spell_name, fallback)
            if spell_name:
                states = _supported_states()
            else:
                states = _blocked_states(reason="missing_innate_spell_name", schema_valid=False)
        else:
            token = fallback
            states = _blocked_states(
                reason="malformed_innate_spellcasting_entry",
                schema_valid=False,
            )

        if states.blocked and states.unsupported_reason not in policy.unsupported_reason_codes:
            states = _blocked_states(reason="unsupported_action_payload", schema_valid=False)
        records.append(
            CapabilityRecord(
                content_id=f"monster_innate_spellcasting:{monster_id}:{token}:{index}",
                content_type="monster_innate_spellcasting",
                states=states,
            )
        )


def build_monster_capability_records(
    *,
    monster_payloads: list[dict[str, Any]],
    policy: MonsterCapabilityPolicy | None = None,
) -> list[CapabilityRecord]:
    active_policy = policy or load_monster_capability_policy()
    records: list[CapabilityRecord] = []

    for index, payload in enumerate(monster_payloads, start=1):
        monster_id = _monster_identifier(payload, index=index)
        records.append(
            CapabilityRecord(
                content_id=f"monster:{monster_id}",
                content_type="monster",
                states=_monster_base_states(payload),
            )
        )

        _add_action_family_records(
            records=records,
            monster_id=monster_id,
            family="monster_action",
            entries=list(payload.get("actions", [])),
            policy=active_policy,
            default_action_cost="action",
        )
        _add_action_family_records(
            records=records,
            monster_id=monster_id,
            family="monster_reaction",
            entries=list(payload.get("reactions", [])),
            policy=active_policy,
            default_action_cost="reaction",
        )
        _add_action_family_records(
            records=records,
            monster_id=monster_id,
            family="monster_legendary_action",
            entries=list(payload.get("legendary_actions", [])),
            policy=active_policy,
            default_action_cost="legendary",
        )
        _add_action_family_records(
            records=records,
            monster_id=monster_id,
            family="monster_lair_action",
            entries=list(payload.get("lair_actions", [])),
            policy=active_policy,
            default_action_cost="lair",
        )
        _add_innate_spellcasting_records(
            records=records,
            monster_id=monster_id,
            entries=list(payload.get("innate_spellcasting", [])),
            policy=active_policy,
        )
    return records


def build_monster_capability_manifest(
    *,
    monster_payloads: list[dict[str, Any]] | None = None,
    monsters_dir: Path = DEFAULT_MONSTERS_DIR,
    manifest_version: str = MANIFEST_VERSION,
    generated_at: str | None = None,
) -> CapabilityManifest:
    payloads = (
        monster_payloads if monster_payloads is not None else load_monster_payloads(monsters_dir)
    )
    records = build_monster_capability_records(monster_payloads=payloads)
    return build_manifest(
        records=records,
        manifest_version=manifest_version,
        generated_at=generated_at,
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
    parser.add_argument(
        "--monster-dir",
        type=Path,
        default=None,
        help="Optional directory of canonical monster payload JSON files for CAP-04 emission.",
    )
    parser.add_argument(
        "--spell-dir",
        type=Path,
        default=None,
        help="Optional directory of canonical spell payload JSON files for CAP-02 emission.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    selected_inputs = sum(
        option is not None for option in (args.input, args.monster_dir, args.spell_dir)
    )
    if selected_inputs > 1:
        raise SystemExit("--input, --monster-dir, and --spell-dir are mutually exclusive")

    if args.spell_dir is not None:
        manifest = build_spell_capability_manifest(
            spells_dir=args.spell_dir,
            manifest_version=args.manifest_version,
            generated_at=args.generated_at,
        )
    elif args.monster_dir is not None:
        manifest = build_monster_capability_manifest(
            monsters_dir=args.monster_dir,
            manifest_version=args.manifest_version,
            generated_at=args.generated_at,
        )
    elif args.input is not None:
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
