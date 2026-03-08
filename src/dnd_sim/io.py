from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dnd_sim.capability_manifest import (
    CapabilityRecord,
    build_class_capability_manifest,
    build_feature_capability_manifest,
    build_item_capability_manifest,
    build_monster_capability_manifest,
    build_spell_capability_manifest,
    build_subclass_capability_manifest,
)
from dnd_sim.spells import (
    DuplicatePolicy as SpellDuplicatePolicy,
    canonicalize_spell_payload,
    load_spell_database as _load_spell_database,
    spell_lookup_key,
)
from dnd_sim.characters import (
    normalize_class_levels,
    total_character_level,
    validate_multiclass_prerequisites,
)
from dnd_sim.io_models import (
    ActionConfig,
    ApplyConditionEffectConfig,
    CommandAlliedEffectConfig,
    CustomSimulationConfig,
    DamageEffectConfig,
    EffectConfig,
    EncounterConfig,
    EnemyConfig,
    EnemyIdentityConfig,
    EnemyStatBlockConfig,
    ForcedMovementEffectConfig,
    HealEffectConfig,
    InnateSpellConfig,
    LoadedScenario,
    MountEffectConfig,
    NextAttackAdvantageEffectConfig,
    NextAttackDisadvantageEffectConfig,
    NoteEffectConfig,
    RemoveConditionEffectConfig,
    ResourceChangeEffectConfig,
    ScenarioConfig,
    StrategyModuleConfig,
    SummonEffectConfig,
    TempHPEffectConfig,
    TransformEffectConfig,
    _spell_root_dir as _canonical_spell_root_dir,
)
from dnd_sim.io_runtime import (
    build_run_dir,
    default_results_dir,
    load_custom_simulation_runner,
    load_strategy_registry,
    load_summary,
    write_json,
    write_trial_rows,
)

logger = logging.getLogger(__name__)

_GLOBAL_CONTENT_ID_RE = re.compile(
    r"^(?P<kind>[a-z_]+)\s*:\s*(?P<slug>[a-z0-9_]+)\s*\|\s*(?P<source>[a-z0-9_]+)\s*$",
    flags=re.IGNORECASE,
)
_GLOBAL_CONTENT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GLOBAL_CONTENT_KIND_ALIASES = {
    "enemy": "monster",
    "race": "species",
}
_GLOBAL_CONTENT_KINDS = frozenset(
    {
        "character",
        "spell",
        "feat",
        "trait",
        "monster",
        "item",
        "class",
        "subclass",
        "world_object",
        "species",
        "background",
    }
)
_GLOBAL_CONTENT_SCHEMA_VERSION = "wld11.v1"
_DEFAULT_RULES_SOURCE_BOOK = "2014"
_NON_CLASS_CONTENT_ID_RE = re.compile(
    r"^(?P<kind>[a-z_]+)\s*:\s*(?P<name>[^|]+?)\s*\|\s*(?P<source>[a-z0-9_]+)\s*$",
    flags=re.IGNORECASE,
)
_NON_CLASS_CONTENT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NON_CLASS_CONTENT_KINDS = frozenset({"feat", "species", "background"})
# 2024 core source tags should be excluded from the 2014 content catalog.
_EDITION_ONE_SOURCE_IDS = frozenset({"XPHB", "XDMG", "XMM"})
_CAPABILITY_REASON_CODE_RE = re.compile(r"^[a-z0-9_]+$")
_CAPABILITY_FEATURE_CONTENT_TYPES = frozenset({"feat", "trait", "background", "species"})
_CAPABILITY_MONSTER_CONTENT_TYPES = frozenset(
    {
        "monster",
        "monster_action",
        "monster_reaction",
        "monster_legendary_action",
        "monster_lair_action",
        "monster_recharge",
        "monster_innate_spellcasting",
    }
)
_CAPABILITY_ITEM_CONTENT_TYPES = frozenset({"item"})
_CAPABILITY_CLASS_CONTENT_TYPES = frozenset({"class", "subclass"})


def _canonical_hash_json_text(payload: Any) -> str:
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return payload.strip()
        return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def stable_content_hash(payload: Any) -> str:
    """Return deterministic SHA-256 hash for a JSON-like payload."""
    canonical_text = _canonical_hash_json_text(payload)
    digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def persist_content_lineage_record(
    conn: Any,
    *,
    content_id: str,
    content_type: str,
    source_book: str,
    schema_version: str,
    source_path: str,
    source_payload: Any,
    canonical_payload: Any,
    imported_at: str | None = None,
) -> dict[str, str]:
    """Persist one content record with deterministic lineage hashes."""
    from dnd_sim.db import upsert_content_record

    imported = imported_at if isinstance(imported_at, str) and imported_at.strip() else None
    if imported is None:
        imported = datetime.now(UTC).isoformat()

    source_hash = stable_content_hash(source_payload)
    canonicalization_hash = stable_content_hash(canonical_payload)
    upsert_content_record(
        conn,
        content_id=content_id,
        content_type=content_type,
        source_book=source_book,
        schema_version=schema_version,
        source_path=source_path,
        source_hash=source_hash,
        canonicalization_hash=canonicalization_hash,
        payload_json=canonical_payload,
        imported_at=imported,
    )
    return {
        "source_hash": source_hash,
        "canonicalization_hash": canonicalization_hash,
        "imported_at": imported,
    }


def replay_content_lineage(conn: Any, *, content_type: str | None = None) -> list[dict[str, Any]]:
    """Load persisted content lineage rows in deterministic replay order."""
    from dnd_sim.db import fetch_content_lineage

    return fetch_content_lineage(conn, content_type=content_type)


def _non_class_raw_root_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "raw" / "5etools"


def _traits_root_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "rules" / "2014" / "traits"


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _canonical_content_kind(raw_kind: str) -> str:
    normalized = str(raw_kind).strip().lower()
    if not normalized:
        raise ValueError("unsupported content kind ''")
    normalized = _GLOBAL_CONTENT_KIND_ALIASES.get(normalized, normalized)
    if normalized not in _GLOBAL_CONTENT_KINDS:
        raise ValueError(
            "unsupported content kind "
            f"'{normalized}' (supported: {', '.join(sorted(_GLOBAL_CONTENT_KINDS))})"
        )
    return normalized


def _slugify_content_name(name: str) -> str:
    return _GLOBAL_CONTENT_SLUG_RE.sub("_", str(name).strip().lower()).strip("_")


def _normalize_source_book(source: Any, *, default: str) -> str:
    if source is None:
        return str(default).strip().upper()
    if not isinstance(source, str):
        raise ValueError("source must be a string")
    normalized = source.strip().upper()
    if not normalized:
        return str(default).strip().upper()
    normalized = _slugify_content_name(normalized).upper()
    if not normalized:
        raise ValueError("source must be non-empty")
    return normalized


def canonical_content_id(*, kind: str, name: str, source: str) -> str:
    canonical_kind = _canonical_content_kind(kind)
    canonical_name = _required_text(name, field_name="name")
    if not isinstance(source, str):
        raise ValueError("source must be a string")
    canonical_source = _normalize_source_book(source, default="")
    if not canonical_source:
        raise ValueError("source must be non-empty")
    slug = _slugify_content_name(canonical_name)
    if not slug:
        raise ValueError("name must be non-empty")
    return f"{canonical_kind}:{slug}|{canonical_source}"


def _validate_content_id_contract(
    *,
    raw_content_id: Any,
    expected_content_id: str,
    kind: str,
) -> str:
    if raw_content_id is None:
        return expected_content_id
    if not isinstance(raw_content_id, str):
        raise ValueError("content_id must be a string when provided")
    normalized = raw_content_id.strip()
    if not normalized:
        raise ValueError("content_id must be non-empty when provided")
    if _GLOBAL_CONTENT_ID_RE.fullmatch(normalized) is None:
        raise ValueError("content_id must match '<kind>:<slug>|<source>'")
    if normalized != expected_content_id:
        raise ValueError(
            f"invalid content_id '{normalized}' for {kind}: expected '{expected_content_id}'"
        )
    return expected_content_id


def _apply_content_metadata(
    payload: dict[str, Any],
    *,
    kind: str,
    name: str,
    source_book: Any = None,
    schema_version: Any = None,
    source_path: Path | None = None,
    default_source_book: str = _DEFAULT_RULES_SOURCE_BOOK,
) -> dict[str, Any]:
    canonical_kind = _canonical_content_kind(kind)
    canonical_source = _normalize_source_book(source_book, default=default_source_book)
    canonical_id = canonical_content_id(kind=canonical_kind, name=name, source=canonical_source)
    content_id = _validate_content_id_contract(
        raw_content_id=payload.get("content_id"),
        expected_content_id=canonical_id,
        kind=canonical_kind,
    )

    normalized_schema = (
        _required_text(schema_version, field_name="schema_version")
        if schema_version is not None
        else _GLOBAL_CONTENT_SCHEMA_VERSION
    )

    normalized = dict(payload)
    normalized["content_id"] = content_id
    normalized["content_type"] = canonical_kind
    normalized["source_book"] = canonical_source
    normalized["schema_version"] = normalized_schema
    if source_path is not None:
        normalized["source_path"] = str(source_path)
    return normalized


def _reject_legacy_alias_fields(
    payload: dict[str, Any],
    *,
    source_path: Path,
    aliases: tuple[str, ...],
) -> None:
    for alias in aliases:
        if alias in payload:
            raise ValueError(
                f"invalid schema in {source_path}: legacy alias field '{alias}' is not allowed; "
                "use canonical 'content_id'"
            )


def _slugify_non_class_content_name(name: str) -> str:
    return _NON_CLASS_CONTENT_SLUG_RE.sub("_", str(name).strip().lower()).strip("_")


def _is_2014_non_class_source(*, row: dict[str, Any], source: str) -> bool:
    edition = str(row.get("edition", "")).strip().lower()
    if edition == "one":
        return False
    if source in _EDITION_ONE_SOURCE_IDS:
        return False
    return True


def _canonical_non_class_content_id(*, kind: str, name: str, source: str) -> str:
    try:
        return canonical_content_id(kind=kind, name=name, source=source)
    except ValueError as exc:
        raise ValueError(
            "invalid content_refs: content references must include name and source"
        ) from exc


def _load_non_class_json_rows(raw_path: Path, key: str) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []
    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@lru_cache(maxsize=4)
def _load_non_class_content_catalog(raw_root: str | None = None) -> dict[str, dict[str, str]]:
    root = Path(raw_root) if raw_root else _non_class_raw_root_dir()
    catalog: dict[str, dict[str, str]] = {}

    def add_rows(rows: list[dict[str, Any]], *, kind: str) -> None:
        for row in rows:
            name = str(row.get("name", "")).strip()
            source = str(row.get("source", "")).strip().upper()
            if not name or not source:
                continue
            if not _is_2014_non_class_source(row=row, source=source):
                continue
            content_id = _canonical_non_class_content_id(
                kind=kind,
                name=name,
                source=source,
            )
            catalog.setdefault(
                content_id,
                {
                    "content_id": content_id,
                    "kind": kind,
                    "name": name,
                    "source": source,
                },
            )

    add_rows(_load_non_class_json_rows(root / "feats.json", "feat"), kind="feat")
    add_rows(_load_non_class_json_rows(root / "races" / "races.json", "race"), kind="species")
    add_rows(
        _load_non_class_json_rows(root / "backgrounds" / "backgrounds.json", "background"),
        kind="background",
    )
    return catalog


def build_global_content_index(
    *,
    rules_root: Path | None = None,
    include_non_class_catalog: bool = True,
) -> dict[str, dict[str, Any]]:
    root = (
        Path(rules_root).resolve()
        if rules_root is not None
        else Path(__file__).resolve().parents[2] / "db" / "rules" / "2014"
    )
    catalog: dict[str, dict[str, Any]] = {}

    def add_record(record: dict[str, Any]) -> None:
        content_id = str(record.get("content_id") or "").strip()
        if not content_id:
            raise ValueError("content_id must be non-empty")
        if content_id in catalog:
            first_path = str(catalog[content_id].get("source_path", "<unknown>"))
            second_path = str(record.get("source_path", "<unknown>"))
            raise ValueError(
                f"duplicate content_id '{content_id}' across {first_path} and {second_path}"
            )
        catalog[content_id] = record

    spells_dir = root / "spells"
    if spells_dir.exists():
        for path in sorted(spells_dir.glob("*.json")):
            payload = _load_json(path)
            _reject_legacy_alias_fields(
                payload,
                source_path=path,
                aliases=("id", "spell_id"),
            )
            normalized_spell = canonicalize_spell_payload(payload, source_path=path)
            metadata_spell = _apply_content_metadata(
                normalized_spell,
                kind="spell",
                name=str(normalized_spell.get("name", "")),
                source_book=payload.get("source_book", payload.get("source")),
                schema_version=payload.get("schema_version"),
                source_path=path,
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )
            add_record(metadata_spell)

    traits_dir = root / "traits"
    if traits_dir.exists():
        for path in sorted(traits_dir.glob("*.json")):
            payload = _load_json(path)
            _reject_legacy_alias_fields(
                payload,
                source_path=path,
                aliases=("id", "trait_id"),
            )
            normalized_trait = _normalize_trait_payload(payload)
            metadata_trait = _apply_content_metadata(
                normalized_trait,
                kind="trait",
                name=path.stem,
                source_book=payload.get("source_book", payload.get("source")),
                schema_version=payload.get("schema_version"),
                source_path=path,
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )
            add_record(metadata_trait)

    monsters_dir = root / "monsters"
    if monsters_dir.exists():
        for path in sorted(monsters_dir.glob("*.json")):
            payload = _load_json(path)
            _reject_legacy_alias_fields(
                payload,
                source_path=path,
                aliases=("id", "monster_id"),
            )
            identity = payload.get("identity", {})
            monster_name = (
                identity.get("enemy_id")
                if isinstance(identity, dict) and identity.get("enemy_id") is not None
                else path.stem
            )
            metadata_monster = _apply_content_metadata(
                payload,
                kind="monster",
                name=str(monster_name),
                source_book=payload.get("source_book", payload.get("source")),
                schema_version=payload.get("schema_version"),
                source_path=path,
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )
            add_record(metadata_monster)

    for directory_name, kind, aliases in (
        ("items", "item", ("id",)),
        ("classes", "class", ("id",)),
        ("subclasses", "subclass", ("id",)),
        ("world_objects", "world_object", ("id", "world_object_id")),
        ("characters", "character", ("id",)),
    ):
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            payload = _load_json(path)
            _reject_legacy_alias_fields(
                payload,
                source_path=path,
                aliases=aliases,
            )
            identifier = _content_index_identifier(
                kind=kind,
                payload=payload,
                default=path.stem,
            )
            metadata_payload = _apply_content_metadata(
                payload,
                kind=kind,
                name=str(identifier),
                source_book=payload.get("source_book", payload.get("source")),
                schema_version=payload.get("schema_version"),
                source_path=path,
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )
            add_record(metadata_payload)

    if include_non_class_catalog:
        non_class_catalog = _load_non_class_content_catalog(str(_non_class_raw_root_dir()))
        for _, row in sorted(non_class_catalog.items()):
            non_class_record = _apply_content_metadata(
                dict(row),
                kind=str(row["kind"]),
                name=str(row["name"]),
                source_book=str(row["source"]),
                schema_version=_GLOBAL_CONTENT_SCHEMA_VERSION,
                source_path=_non_class_raw_root_dir(),
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )
            add_record(non_class_record)

    return catalog


def _normalize_content_reference_id(raw_reference: Any) -> str:
    text = str(raw_reference or "").strip()
    if not text:
        raise ValueError("invalid content_refs: content references must not be empty")

    match = _NON_CLASS_CONTENT_ID_RE.fullmatch(text)
    if match is None:
        raise ValueError(
            "invalid content_refs: content_refs entries must match '<kind>:<name>|<source>'"
        )

    kind = str(match.group("kind")).strip().lower()
    if kind not in _NON_CLASS_CONTENT_KINDS:
        raise ValueError(
            "invalid content_refs: unsupported kind "
            f"'{kind}' (supported: {', '.join(sorted(_NON_CLASS_CONTENT_KINDS))})"
        )

    source = str(match.group("source")).strip().upper()
    if source in _EDITION_ONE_SOURCE_IDS:
        raise ValueError(f"invalid content_refs: source '{source}' is not part of the 2014 catalog")

    return _canonical_non_class_content_id(
        kind=kind,
        name=str(match.group("name")),
        source=source,
    )


def _normalize_character_content_references(
    *,
    payload: dict[str, Any],
    content_catalog: dict[str, dict[str, str]],
) -> dict[str, Any]:
    raw_refs = payload.get("content_refs")
    if raw_refs is None:
        return payload
    if not isinstance(raw_refs, list):
        raise ValueError(
            "invalid content_refs: content_refs must be a list of '<kind>:<name>|<source>' values"
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for idx, raw_reference in enumerate(raw_refs):
        content_id = _normalize_content_reference_id(raw_reference)
        if content_id in seen:
            raise ValueError(
                f"invalid content_refs: duplicate content reference '{content_id}' at "
                f"content_refs[{idx}]"
            )
        if content_id not in content_catalog:
            raise ValueError(
                f"invalid content_refs: unknown content reference '{content_id}' at "
                f"content_refs[{idx}]"
            )
        seen.add(content_id)
        normalized.append(content_id)

    normalized.sort()
    payload["content_refs"] = normalized
    payload["content_reference_details"] = [dict(content_catalog[row]) for row in normalized]
    return payload


def _spell_root_dir() -> Path:
    # Canonical spell-root path lives in io_models to avoid duplicate definitions.
    return _canonical_spell_root_dir()


@lru_cache(maxsize=1)
def _canonical_capability_records() -> tuple[CapabilityRecord, ...]:
    records: list[CapabilityRecord] = []
    for manifest in (
        build_spell_capability_manifest(),
        build_feature_capability_manifest(),
        build_monster_capability_manifest(),
        build_item_capability_manifest(),
        build_class_capability_manifest(),
        build_subclass_capability_manifest(),
    ):
        records.extend(manifest.records)
    return tuple(records)


def validate_capability_gate_records(
    *,
    records: list[CapabilityRecord | dict[str, Any]],
    required_content_types: set[str] | None = None,
) -> list[str]:
    normalized_types = (
        {str(value).strip().lower() for value in required_content_types}
        if required_content_types is not None
        else None
    )

    issues: list[str] = []
    for index, raw_record in enumerate(records):
        try:
            record = (
                raw_record
                if isinstance(raw_record, CapabilityRecord)
                else CapabilityRecord.model_validate(raw_record)
            )
        except ValidationError as exc:
            issues.append(f"capability record index {index} failed schema validation: {exc}")
            continue

        if normalized_types is not None and record.content_type not in normalized_types:
            continue

        states = record.states
        if states.blocked:
            reason = str(states.unsupported_reason or "").strip()
            if not reason:
                issues.append(
                    f"{record.content_id} blocked record must declare states.unsupported_reason"
                )
            elif _CAPABILITY_REASON_CODE_RE.fullmatch(reason) is None:
                issues.append(
                    f"{record.content_id} blocked record unsupported_reason must be a single code"
                )
            continue

        if not states.schema_valid:
            issues.append(f"{record.content_id} supported-scope record must set schema_valid=true")
        if not states.tested:
            issues.append(f"{record.content_id} supported-scope record must set tested=true")
        if states.unsupported_reason is not None:
            issues.append(
                f"{record.content_id} supported-scope record must not set unsupported_reason"
            )
    return issues


def capability_gate_issues_for_types(
    required_content_types: set[str] | None = None,
) -> list[str]:
    return validate_capability_gate_records(
        records=list(_canonical_capability_records()),
        required_content_types=required_content_types,
    )


def _assert_capability_gate(
    *,
    required_content_types: set[str] | None,
    source: str,
) -> None:
    issues = capability_gate_issues_for_types(required_content_types=required_content_types)
    if not issues:
        return
    preview = "\n".join(f"- {issue}" for issue in issues[:12])
    raise ValueError(
        f"Capability manifest gate failed during {source} with {len(issues)} issue(s):\n{preview}"
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _content_index_identifier(*, kind: str, payload: dict[str, Any], default: str) -> str:
    if kind == "item":
        return str(payload.get("item_id") or payload.get("name") or default)
    if kind == "class":
        return str(payload.get("class_id") or payload.get("name") or default)
    if kind == "subclass":
        subclass_id = str(payload.get("subclass_id") or payload.get("name") or "").strip()
        class_id = str(payload.get("class_id") or payload.get("class_name") or "").strip()
        if subclass_id and class_id:
            return f"{subclass_id}_{class_id}"
        if subclass_id:
            return subclass_id
        return default
    return str(payload.get("name") or payload.get("character_id") or default)


def load_scenario(scenario_path: Path) -> LoadedScenario:
    raw = _load_json(scenario_path)
    try:
        scenario = ScenarioConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid scenario schema at {scenario_path}: {exc}") from exc
    _assert_capability_gate(
        required_content_types=set(_CAPABILITY_MONSTER_CONTENT_TYPES),
        source="load_scenario",
    )

    enemies: dict[str, EnemyConfig] = {}
    enemy_dir = scenario_path.parent.parent / "enemies"

    # Normalize single encounter into the campaign array if used
    if scenario.enemies and not scenario.encounters:
        scenario.encounters.append(EncounterConfig(enemies=scenario.enemies))

    all_enemy_ids = set()
    for enc in scenario.encounters:
        all_enemy_ids.update(enc.enemies)

    from .db import execute_query

    for enemy_id in all_enemy_ids:
        # 1. Check local file first (for tests running via tmp_path or local overrides)
        path = enemy_dir / f"{enemy_id}.json"

        enemy_payload = None
        source_path: Path | None = None
        if path.exists():
            enemy_payload = _load_json(path)
            source_path = path
        else:
            # 2. Fallback to SQLite Database for built-ins
            rows = execute_query("SELECT data_json FROM enemies WHERE enemy_id = ?", (enemy_id,))
            if rows:
                enemy_payload = json.loads(rows[0]["data_json"])
            else:
                raise ValueError(f"Enemy definition not found on disk or SQLite DB: {enemy_id}")

        if isinstance(enemy_payload, dict):
            if source_path is not None:
                _reject_legacy_alias_fields(
                    enemy_payload,
                    source_path=source_path,
                    aliases=("id", "monster_id"),
                )
            enemy_payload = _apply_content_metadata(
                enemy_payload,
                kind="monster",
                name=enemy_id,
                source_book=enemy_payload.get("source_book", enemy_payload.get("source")),
                schema_version=enemy_payload.get("schema_version"),
                source_path=source_path,
                default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
            )

        try:
            enemy = EnemyConfig.model_validate(enemy_payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid enemy schema for {enemy_id}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON blob for {enemy_id}: {exc}") from exc

        enemies[enemy_id] = enemy

    return LoadedScenario(
        scenario_path=str(scenario_path),
        config=scenario,
        enemies=enemies,
    )


def load_character_db(db_dir: Path) -> dict[str, dict[str, Any]]:
    from .db import execute_query

    out: dict[str, dict[str, Any]] = {}
    non_class_content_catalog = _load_non_class_content_catalog(str(_non_class_raw_root_dir()))

    def _normalize_character_progression(
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        character_id = _required_text(payload.get("character_id"), field_name="character_id")
        class_levels_payload = payload.get("class_levels")
        if not isinstance(class_levels_payload, dict):
            raise ValueError("invalid class_levels: class_levels mapping is required")
        class_levels = normalize_class_levels(class_levels_payload)
        if not class_levels:
            raise ValueError("invalid class_levels: class_levels mapping is required")
        payload.pop("class_level", None)
        payload["class_levels"] = class_levels
        payload["character_level"] = total_character_level(class_levels)
        prereq_errors = validate_multiclass_prerequisites(
            class_levels=class_levels,
            ability_scores=payload.get("ability_scores") if isinstance(payload, dict) else {},
        )
        if prereq_errors:
            payload["multiclass_prerequisite_errors"] = prereq_errors
        payload = _normalize_character_content_references(
            payload=payload,
            content_catalog=non_class_content_catalog,
        )
        payload = _apply_content_metadata(
            payload,
            kind="character",
            name=character_id,
            source_book=payload.get("source_book"),
            schema_version=payload.get("schema_version"),
            default_source_book="CUSTOM",
        )
        return payload

    # 1. Base load from SQLite
    rows = execute_query("SELECT character_id, data_json FROM characters")
    for row in rows:
        try:
            payload = json.loads(row["data_json"])
            if isinstance(payload, dict):
                out[row["character_id"]] = _normalize_character_progression(
                    payload=payload,
                )
        except json.JSONDecodeError:
            pass
        except ValueError as exc:
            character_id = str(row["character_id"])
            if str(exc).startswith("invalid content_refs"):
                raise ValueError(f"invalid content_refs for {character_id}: {exc}") from exc
            # Ignore malformed persisted rows so local file overrides can still load.
            pass

    # 2. Local overriding from db_dir (crucial for pytests using tmp_path configurations)
    index_path = db_dir / "index.json"
    if index_path.exists():
        index = _load_json(index_path)
        for row in index.get("characters", []):
            character_id = row["character_id"]
            character_path = db_dir / f"{character_id}.json"
            if character_path.exists():
                payload = _load_json(character_path)
                try:
                    out[character_id] = _normalize_character_progression(
                        payload=payload,
                    )
                except ValueError as exc:
                    if str(exc).startswith("invalid content_refs"):
                        raise ValueError(f"invalid content_refs for {character_id}: {exc}") from exc
                    raise ValueError(f"invalid class_levels for {character_id}: {exc}") from exc

    return out


def _normalize_trait_source_type(raw_type: Any) -> str:
    key = str(raw_type or "").strip().lower()
    if key in {"feat", "species", "background", "subclass", "class", "other"}:
        return key
    raise ValueError(
        "invalid trait source_type: expected one of "
        "'feat', 'species', 'background', 'subclass', 'class', or 'other'"
    )


def _normalize_trait_mechanics(raw_mechanics: Any) -> list[Any]:
    if not isinstance(raw_mechanics, list):
        return []

    normalized: list[Any] = []
    for mechanic in raw_mechanics:
        if not isinstance(mechanic, dict):
            normalized.append(mechanic)
            continue

        payload = dict(mechanic)
        effect_type = payload.get("effect_type")
        if isinstance(effect_type, str):
            payload["effect_type"] = effect_type.strip().lower()

        trigger = payload.get("trigger")
        if isinstance(trigger, str):
            payload["trigger"] = trigger.strip().lower()
        normalized.append(payload)
    return normalized


def _normalize_trait_payload(trait_data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(trait_data)
    payload["source_type"] = _normalize_trait_source_type(payload.get("source_type"))
    payload["mechanics"] = _normalize_trait_mechanics(payload.get("mechanics"))
    return payload


def load_traits_db(traits_dir: Path) -> dict[str, dict[str, Any]]:
    from .db import execute_query

    resolved_traits_dir = Path(traits_dir).resolve()
    canonical_traits_dir = _traits_root_dir().resolve()
    if resolved_traits_dir == canonical_traits_dir:
        _assert_capability_gate(
            required_content_types=set(_CAPABILITY_FEATURE_CONTENT_TYPES),
            source="load_traits_db",
        )

    out: dict[str, dict[str, Any]] = {}

    # 1. Base SQLite load
    rows = execute_query("SELECT id, data_json FROM traits")
    for row in rows:
        try:
            trait_data = json.loads(row["data_json"])
            if not isinstance(trait_data, dict):
                continue
            trait_name = str(trait_data.get("name", "")).strip().lower()
            if trait_name:
                normalized_trait = _normalize_trait_payload(trait_data)
                normalized_trait = _apply_content_metadata(
                    normalized_trait,
                    kind="trait",
                    name=str(row["id"]),
                    source_book=normalized_trait.get("source_book", normalized_trait.get("source")),
                    schema_version=normalized_trait.get("schema_version"),
                    default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
                )
                out[trait_name] = normalized_trait
        except json.JSONDecodeError:
            pass

    # 2. Local Path Load overriding
    if traits_dir.exists():
        for path in traits_dir.glob("*.json"):
            trait_data = _load_json(path)
            _reject_legacy_alias_fields(
                trait_data,
                source_path=path,
                aliases=("id", "trait_id"),
            )
            trait_name = str(trait_data.get("name", "")).strip().lower()
            if trait_name:
                normalized_trait = _normalize_trait_payload(trait_data)
                normalized_trait = _apply_content_metadata(
                    normalized_trait,
                    kind="trait",
                    name=path.stem,
                    source_book=normalized_trait.get("source_book", normalized_trait.get("source")),
                    schema_version=normalized_trait.get("schema_version"),
                    source_path=path,
                    default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
                )
                out[trait_name] = normalized_trait

    return out


def load_spell_db(
    spells_dir: Path, *, duplicate_policy: SpellDuplicatePolicy = "fail_fast"
) -> dict[str, dict[str, Any]]:
    """Load canonical spell records keyed by normalized spell lookup key."""

    canonical_dir = _spell_root_dir().resolve()
    resolved_dir = Path(spells_dir).resolve()
    if resolved_dir != canonical_dir:
        raise ValueError(
            f"Spell database path must be canonical: expected {canonical_dir}, got {resolved_dir}"
        )
    if duplicate_policy != "fail_fast":
        raise ValueError("Spell duplicate policy must be 'fail_fast' for canonical loads")
    _assert_capability_gate(required_content_types={"spell"}, source="load_spell_db")

    metadata_by_key: dict[str, dict[str, Any]] = {}
    for path in sorted(canonical_dir.glob("*.json")):
        raw_payload = _load_json(path)
        _reject_legacy_alias_fields(
            raw_payload,
            source_path=path,
            aliases=("id", "spell_id"),
        )
        canonical_payload = canonicalize_spell_payload(raw_payload, source_path=path)
        lookup_key = spell_lookup_key(str(canonical_payload["name"]))
        if lookup_key in metadata_by_key:
            first = metadata_by_key[lookup_key]["source_path"]
            raise ValueError(f"duplicate spell lookup key '{lookup_key}' across {first} and {path}")
        metadata_by_key[lookup_key] = {
            "source_book": raw_payload.get("source_book", raw_payload.get("source")),
            "schema_version": raw_payload.get("schema_version"),
            "source_path": path,
        }

    records = _load_spell_database(canonical_dir, duplicate_policy="fail_fast")
    normalized_records: dict[str, dict[str, Any]] = {}
    for key, record in records.items():
        metadata = metadata_by_key.get(key, {})
        normalized_records[key] = _apply_content_metadata(
            dict(record),
            kind="spell",
            name=str(record.get("name", "")),
            source_book=metadata.get("source_book"),
            schema_version=metadata.get("schema_version"),
            source_path=metadata.get("source_path"),
            default_source_book=_DEFAULT_RULES_SOURCE_BOOK,
        )
    return normalized_records
