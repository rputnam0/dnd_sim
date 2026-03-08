# dnd-sim

Deterministic D&D 5e 2014 backend for combat, progression, world-state, and CRPG-core campaign flows.

## Setup

```bash
uv sync --extra dev
```

## Common Commands

```bash
uv run python -m dnd_sim.parse_characters --input river_line/character_sheets/character_sheets_extracted.md --out river_line/db/characters
uv run python -m dnd_sim.simulate --scenario river_line/encounters/ley_heart/scenarios/ley_heart_phase_1.json --trials 5000 --seed 1 --name ley_heart_phase_1_baseline
uv run python -m dnd_sim.report --run river_line/results/<run_dir>/summary.json --out river_line/results/<run_dir>
uv run python scripts/content/populate_wave7_catalogs.py
uv run python scripts/content/rebuild_capability_artifacts.py
uv run python scripts/content/verify_completion_capabilities.py --strict
```

## Engine Surface

- Canonical 2014 content lives under `db/rules/2014/` and includes items, classes, subclasses, spells, monsters, traits, feats, backgrounds, and species.
- Runtime CRPG-core support includes class/subclass progression, item attunement/equipment/charges, stealth/surprise/search, traps, locks, containers, and persistent exploration world state.
- Program truth and release state live under `docs/program/`.

## Tests

```bash
uv run python -m pytest
```
