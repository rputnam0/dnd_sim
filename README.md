# dnd-sim

Generalized D&D encounter simulation toolkit.

## Setup

```bash
uv sync --extra dev
```

## Commands

```bash
uv run python -m dnd_sim.parse_characters --input river_line/character_sheets/character_sheets_extracted.md --out river_line/db/characters
uv run python -m dnd_sim.simulate --scenario river_line/encounters/ley_heart/scenarios/ley_heart_phase_1.json --trials 5000 --seed 1 --name ley_heart_phase_1_baseline
uv run python -m dnd_sim.report --run river_line/results/<run_dir>/summary.json --out river_line/results/<run_dir>
```

## Encounter Schema

- Full example (scenario + enemy with all supported action/effect options):
  `docs/encounter_schema_full_example.json`

## Tests

```bash
uv run python -m pytest
```
