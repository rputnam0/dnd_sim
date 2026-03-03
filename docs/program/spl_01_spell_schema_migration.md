# SPL-01 Spell Schema Migration Note

## What changed

SPL-01 introduces a canonical spell schema pipeline in `src/dnd_sim/spells.py` and routes runtime spell lookup through validated spell records.

Canonical spell records now normalize to:

- `name`
- `type` (`"spell"`)
- `level` (`0-9`)
- `school` (optional)
- `casting_time`
- `range_ft` (optional)
- `concentration`
- `duration_rounds` (optional)
- `description`
- `save_ability` (optional, `str|dex|con|int|wis|cha`)
- `damage_type` (optional)
- `mechanics` (list of objects; string mechanics are normalized to `note` effects)

## Duplicate policy

`load_spell_database()` supports deterministic duplicate handling:

- `fail_fast` (default): raises on duplicate normalized spell lookup keys.
- `prefer_richest`: chooses the richest canonical record deterministically for runtime compatibility.

Runtime lookup in `engine.py` now uses validated records and currently opts into `prefer_richest` so legacy duplicated spell files do not hard-stop simulation execution.

## Normalization behavior

Legacy spell payloads are normalized into the canonical schema, including:

- parsing `level`/`school` from `meta` when absent,
- parsing `range_ft` from textual `range`,
- deriving `concentration`/`duration_rounds` from textual duration,
- defaulting missing `casting_time` to `"action"`,
- promoting `description_raw` to `description` when needed.

## Recommended migration workflow

1. Run strict fail-fast validation to surface unresolved duplicates/data issues:
   - `uv run python -c "from pathlib import Path; from dnd_sim.spells import load_spell_database; load_spell_database(Path('db/rules/2014/spells'), duplicate_policy='fail_fast')"`
2. Resolve duplicates by consolidating to one canonical record per normalized spell key.
3. Re-run the strict validation command until clean.
4. Keep runtime on validated spell lookup only.
