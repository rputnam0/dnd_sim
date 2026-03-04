from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


LEGACY_METHOD_PATTERN = re.compile(
    r"^\s*def\s+(choose_action|choose_targets|decide_resource_spend)\s*\("
)
LEGACY_EFFECT_ALIASES = {
    "shapechange",
    "summon_creature",
    "command_construct_companion",
    "antimagic",
    "antimagic_zone",
}


@dataclass(slots=True)
class LegacyDef:
    path: str
    line: int
    method: str


@dataclass(slots=True)
class AliasMarker:
    path: str
    line: int
    marker: str


def _load_json(path: Path) -> dict | list | str | int | float | bool | None:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_legacy_method_defs(repo_root: Path) -> list[LegacyDef]:
    defs: list[LegacyDef] = []
    for subdir in ("src", "river_line", "tests"):
        root = repo_root / subdir
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, start=1):
                match = LEGACY_METHOD_PATTERN.search(line)
                if match:
                    defs.append(
                        LegacyDef(
                            path=path.relative_to(repo_root).as_posix(),
                            line=line_no,
                            method=match.group(1),
                        )
                    )
    defs.sort(key=lambda row: (row.path, row.line, row.method))
    return defs


def _scan_alias_markers(repo_root: Path) -> list[AliasMarker]:
    markers: list[AliasMarker] = []
    files = [
        repo_root / "src/dnd_sim/engine.py",
        repo_root / "src/dnd_sim/strategy_api.py",
        repo_root / "src/dnd_sim/io.py",
        repo_root / "src/dnd_sim/mechanics_schema.py",
    ]
    marker_tokens = (
        "choose_action",
        "choose_targets",
        "decide_resource_spend",
        'payload.get("type")',
        "event_trigger",
    )
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in marker_tokens:
            start = 0
            while True:
                index = text.find(marker, start)
                if index < 0:
                    break
                line = text.count("\n", 0, index) + 1
                markers.append(
                    AliasMarker(
                        path=path.relative_to(repo_root).as_posix(),
                        line=line,
                        marker=marker,
                    )
                )
                start = index + len(marker)
    markers.sort(key=lambda row: (row.path, row.line, row.marker))
    return markers


def _normalize_lookup_key(name: str) -> str:
    lowered = name.strip().lower()
    lowered = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return " ".join(lowered.split())


def _collect_counts(repo_root: Path) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, list[str]]]]:
    traits_dir = repo_root / "db/rules/2014/traits"
    spells_dir = repo_root / "db/rules/2014/spells"
    monsters_dir = repo_root / "db/rules/2014/monsters"
    characters_dir = repo_root / "river_line/db/characters"

    traits_files = sorted(traits_dir.glob("*.json"))
    spells_files = sorted(spells_dir.glob("*.json"))
    monsters_files = sorted(monsters_dir.glob("*.json"))
    character_files = sorted(p for p in characters_dir.glob("*.json") if p.name != "index.json")

    traits_top_type = 0
    traits_top_source_type = 0
    traits_mechanics_rows_total = 0
    traits_mechanics_type = 0
    traits_mechanics_effect_type = 0
    traits_mechanics_meta_type = 0
    traits_mechanics_event_trigger = 0
    traits_mechanics_trigger = 0
    for path in traits_files:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if "type" in payload:
            traits_top_type += 1
        if "source_type" in payload:
            traits_top_source_type += 1
        mechanics = payload.get("mechanics")
        if not isinstance(mechanics, list):
            continue
        for row in mechanics:
            if not isinstance(row, dict):
                continue
            traits_mechanics_rows_total += 1
            if "type" in row:
                traits_mechanics_type += 1
            if "effect_type" in row:
                traits_mechanics_effect_type += 1
            if "meta_type" in row:
                traits_mechanics_meta_type += 1
            if "event_trigger" in row:
                traits_mechanics_event_trigger += 1
            if "trigger" in row:
                traits_mechanics_trigger += 1

    spells_with_meta = 0
    spells_with_level = 0
    spells_with_school = 0
    spells_with_range_ft = 0
    spells_with_duration_rounds = 0
    spells_with_legacy_effect_alias = 0
    lookup_to_files: dict[str, list[str]] = {}
    for path in spells_files:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if "meta" in payload:
            spells_with_meta += 1
        if "level" in payload:
            spells_with_level += 1
        if "school" in payload:
            spells_with_school += 1
        if "range_ft" in payload:
            spells_with_range_ft += 1
        if "duration_rounds" in payload:
            spells_with_duration_rounds += 1

        key = _normalize_lookup_key(str(payload.get("name", "")))
        lookup_to_files.setdefault(key, []).append(path.name)

        effects: list[dict] = []
        for field in ("mechanics", "effects"):
            rows = payload.get(field)
            if isinstance(rows, list):
                effects.extend(row for row in rows if isinstance(row, dict))
        if any(str(row.get("effect_type", "")).strip() in LEGACY_EFFECT_ALIASES for row in effects):
            spells_with_legacy_effect_alias += 1

    duplicate_keys = sorted(
        (lookup_key, sorted(files))
        for lookup_key, files in lookup_to_files.items()
        if len(files) > 1
    )

    monsters_with_identity = 0
    monsters_with_stat_block = 0
    for path in monsters_files:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if "identity" in payload:
            monsters_with_identity += 1
        if "stat_block" in payload:
            monsters_with_stat_block += 1

    characters_with_class_level = 0
    characters_with_class_levels = 0
    for path in character_files:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if "class_level" in payload:
            characters_with_class_level += 1
        if "class_levels" in payload:
            characters_with_class_levels += 1

    rows = [
        ("traits", "files_total", str(len(traits_files)), "db/rules/2014/traits/*.json"),
        ("traits", "top_level_type", str(traits_top_type), "legacy source discriminator field"),
        (
            "traits",
            "top_level_source_type",
            str(traits_top_source_type),
            "canonical source discriminator field",
        ),
        ("traits", "mechanics_rows_total", str(traits_mechanics_rows_total), "sum mechanics[] rows"),
        ("traits", "mechanics_type", str(traits_mechanics_type), "legacy executable/metadata alias field"),
        (
            "traits",
            "mechanics_effect_type",
            str(traits_mechanics_effect_type),
            "canonical executable effect field",
        ),
        (
            "traits",
            "mechanics_meta_type",
            str(traits_mechanics_meta_type),
            "canonical metadata effect field",
        ),
        (
            "traits",
            "mechanics_event_trigger",
            str(traits_mechanics_event_trigger),
            "legacy trigger alias field",
        ),
        ("traits", "mechanics_trigger", str(traits_mechanics_trigger), "canonical trigger field"),
        ("spells", "files_total", str(len(spells_files)), "db/rules/2014/spells/*.json"),
        ("spells", "with_meta", str(spells_with_meta), "legacy compatibility metadata block"),
        ("spells", "with_level", str(spells_with_level), "canonical explicit level"),
        ("spells", "with_school", str(spells_with_school), "canonical explicit school"),
        ("spells", "with_range_ft", str(spells_with_range_ft), "canonical explicit range_ft"),
        (
            "spells",
            "with_duration_rounds",
            str(spells_with_duration_rounds),
            "canonical explicit duration_rounds",
        ),
        (
            "spells",
            "duplicate_lookup_key_groups",
            str(len(duplicate_keys)),
            "duplicate normalized spell name keys",
        ),
        (
            "spells",
            "with_legacy_effect_alias",
            str(spells_with_legacy_effect_alias),
            "effect_type in alias set slated for removal",
        ),
        ("monsters", "files_total", str(len(monsters_files)), "db/rules/2014/monsters/*.json"),
        (
            "monsters",
            "with_identity",
            str(monsters_with_identity),
            "modern EnemyConfig identity section",
        ),
        (
            "monsters",
            "with_stat_block",
            str(monsters_with_stat_block),
            "modern EnemyConfig stat_block section",
        ),
        (
            "characters",
            "files_total",
            str(len(character_files)),
            "river_line/db/characters/*.json excluding index.json",
        ),
        (
            "characters",
            "with_class_level",
            str(characters_with_class_level),
            "legacy text progression field",
        ),
        (
            "characters",
            "with_class_levels",
            str(characters_with_class_levels),
            "canonical mapping progression field",
        ),
    ]
    return rows, duplicate_keys


def _write_outputs(
    repo_root: Path,
    date_stamp: str,
    legacy_defs: list[LegacyDef],
    alias_markers: list[AliasMarker],
    data_rows: list[tuple[str, str, str, str]],
    duplicate_keys: list[tuple[str, list[str]]],
) -> None:
    out_dir = repo_root / "docs/deprecation"
    out_dir.mkdir(parents=True, exist_ok=True)

    counts_path = out_dir / f"legacy_data_counts_{date_stamp}.tsv"
    counts_lines = ["dataset\tmetric\tvalue\tnotes"]
    counts_lines.extend("\t".join(row) for row in data_rows)
    counts_path.write_text("\n".join(counts_lines) + "\n", encoding="utf-8")

    mappings_path = out_dir / f"legacy_cutover_mappings_{date_stamp}.md"
    mappings_lines = [
        f"# Legacy Cutover Mappings ({date_stamp[:4]}-{date_stamp[4:6]}-{date_stamp[6:]})",
        "",
        "## Strategy Interface",
        "| Legacy Surface | Canonical Replacement | Action |",
        "|---|---|---|",
        "| `choose_action(actor, state)` | `declare_turn(actor, state).action.action_name` | Remove legacy runtime call path |",
        "| `choose_targets(actor, intent, state)` | `declare_turn(actor, state).action.targets[]` | Remove legacy runtime call path |",
        "| `decide_resource_spend(actor, intent, state)` | `declare_turn(actor, state).action.resource_spend` | Remove legacy runtime call path |",
        "| `ActionIntent` transport | `TurnDeclaration` only | Remove from runtime contract |",
        "",
        "## Canonical Schema Mapping",
        "| Legacy Field/Value | Canonical Field/Value | Notes |",
        "|---|---|---|",
        "| top-level trait `type` | top-level trait `source_type` | `metamagic` maps to `class` source_type |",
        "| mechanics row `type` (executable) | mechanics row `effect_type` | Runtime executable rows must use `effect_type` |",
        "| mechanics row `type` (annotation) | mechanics row `meta_type` | Non-runtime metadata rows preserved as `meta_type` |",
        "| mechanics row `event_trigger` | mechanics row `trigger` | Canonical trigger field |",
        "| character `class_level` text | character `class_levels` mapping | `class_level` becomes derived output only |",
        "",
        "## Canonical Effect Alias Removal",
        "| Legacy Effect Alias | Canonical Effect Type |",
        "|---|---|",
        "| `shapechange` | `transform` |",
        "| `summon_creature` | `summon` |",
        "| `command_construct_companion` | `command_allied` |",
        "| `antimagic` | `antimagic_field` |",
        "| `antimagic_zone` | `antimagic_field` |",
        "",
        f"## Duplicate Spell Lookup Keys ({len(duplicate_keys)})",
    ]
    mappings_lines.extend(
        f"- `{lookup_key}` => `{', '.join(files)}`" for lookup_key, files in duplicate_keys
    )
    mappings_path.write_text("\n".join(mappings_lines) + "\n", encoding="utf-8")

    inventory_path = out_dir / f"legacy_surface_inventory_{date_stamp}.md"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    inventory_lines = [
        f"# Legacy Surface Inventory ({date_stamp[:4]}-{date_stamp[4:6]}-{date_stamp[6:]})",
        "",
        f"- Generated at: `{generated_at}`",
        "- Scope: strategy runtime contract, runtime alias paths, and canonical-data readiness counts.",
        "- Repro command: run the command block below from repository root.",
        "",
        "```bash",
        f"uv run python scripts/migrations/report_legacy_surface.py --date {date_stamp}",
        "```",
        "",
        "## Strategy Legacy Method Definitions",
        (
            "- Total definitions (`choose_action`/`choose_targets`/`decide_resource_spend`): "
            f"`{len(legacy_defs)}`"
        ),
        "",
        "| File | Line | Method |",
        "|---|---:|---|",
    ]
    inventory_lines.extend(
        f"| `{row.path}` | {row.line} | `{row.method}` |" for row in legacy_defs
    )

    inventory_lines.extend(
        [
            "",
            "## Runtime/Validation Alias Markers (sampled canonical files)",
            "| File | Line | Marker |",
            "|---|---:|---|",
        ]
    )
    inventory_lines.extend(
        f"| `{row.path}` | {row.line} | `{row.marker}` |" for row in alias_markers
    )

    values = {(dataset, metric): value for dataset, metric, value, _ in data_rows}
    inventory_lines.extend(
        [
            "",
            "## Dataset Counts Snapshot",
            f"- See `docs/deprecation/legacy_data_counts_{date_stamp}.tsv` for full machine-readable counts.",
            (
                "- Traits: "
                f"`{values[('traits', 'files_total')]}` files; top-level `type`: "
                f"`{values[('traits', 'top_level_type')]}`, `source_type`: "
                f"`{values[('traits', 'top_level_source_type')]}`."
            ),
            (
                "- Spells: "
                f"`{values[('spells', 'files_total')]}` files; `meta` present: "
                f"`{values[('spells', 'with_meta')]}`; duplicate lookup key groups: "
                f"`{values[('spells', 'duplicate_lookup_key_groups')]}`."
            ),
            (
                "- Monsters: "
                f"`{values[('monsters', 'files_total')]}` files; `identity`: "
                f"`{values[('monsters', 'with_identity')]}`, `stat_block`: "
                f"`{values[('monsters', 'with_stat_block')]}`."
            ),
            (
                "- Characters: "
                f"`{values[('characters', 'files_total')]}` files; `class_level`: "
                f"`{values[('characters', 'with_class_level')]}`, `class_levels`: "
                f"`{values[('characters', 'with_class_levels')]}`."
            ),
            "",
            "## Duplicate Spell Lookup Keys",
        ]
    )
    inventory_lines.extend(
        f"- `{lookup_key}` => `{', '.join(files)}`" for lookup_key, files in duplicate_keys
    )
    inventory_path.write_text("\n".join(inventory_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate legacy decommission inventory artifacts.")
    parser.add_argument("--date", required=True, help="Date stamp in YYYYMMDD format.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path (defaults to current working directory).",
    )
    args = parser.parse_args()

    if not re.fullmatch(r"\d{8}", args.date):
        raise ValueError("--date must be YYYYMMDD")

    repo_root = Path(args.repo_root).resolve()
    legacy_defs = _scan_legacy_method_defs(repo_root)
    alias_markers = _scan_alias_markers(repo_root)
    data_rows, duplicate_keys = _collect_counts(repo_root)

    rows = [("strategy", "legacy_method_defs", str(len(legacy_defs)), "def choose_action|choose_targets|decide_resource_spend across src/ river_line/ tests")]
    rows.extend(data_rows)

    _write_outputs(
        repo_root=repo_root,
        date_stamp=args.date,
        legacy_defs=legacy_defs,
        alias_markers=alias_markers,
        data_rows=rows,
        duplicate_keys=duplicate_keys,
    )

    print(f"wrote docs/deprecation/legacy_surface_inventory_{args.date}.md")
    print(f"wrote docs/deprecation/legacy_cutover_mappings_{args.date}.md")
    print(f"wrote docs/deprecation/legacy_data_counts_{args.date}.tsv")


if __name__ == "__main__":
    main()
