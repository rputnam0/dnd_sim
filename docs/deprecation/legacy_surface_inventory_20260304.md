# Legacy Surface Inventory (2026-03-04)

- Generated at: `2026-03-04 08:02:46Z`
- Scope: strategy runtime contract, runtime alias paths, and canonical-data readiness counts.
- Repro command: run the command block below from repository root.

```bash
uv run python scripts/migrations/report_legacy_surface.py --date 20260304
```

## Strategy Legacy Method Definitions
- Total definitions (`choose_action`/`choose_targets`/`decide_resource_spend`): `3`

| File | Line | Method |
|---|---:|---|
| `tests/test_fnd06_turn_declaration.py` | 100 | `choose_action` |
| `tests/test_fnd06_turn_declaration.py` | 103 | `choose_targets` |
| `tests/test_fnd06_turn_declaration.py` | 106 | `decide_resource_spend` |

## Runtime/Validation Alias Markers (sampled canonical files)
| File | Line | Marker |
|---|---:|---|
| `src/dnd_sim/engine.py` | 3812 | `event_trigger` |
| `src/dnd_sim/engine.py` | 3812 | `event_trigger` |
| `src/dnd_sim/engine.py` | 5865 | `event_trigger` |
| `src/dnd_sim/engine.py` | 5865 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10733 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10746 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10760 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10763 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10766 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10769 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10772 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10776 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10777 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10778 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10781 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10788 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10792 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10795 | `event_trigger` |
| `src/dnd_sim/engine.py` | 10798 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11057 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11062 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11067 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11081 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11082 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11107 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11158 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11225 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11441 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11449 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11450 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11480 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11596 | `event_trigger` |
| `src/dnd_sim/engine.py` | 11596 | `event_trigger` |
| `src/dnd_sim/engine.py` | 14260 | `event_trigger` |
| `src/dnd_sim/engine.py` | 14404 | `event_trigger` |
| `src/dnd_sim/engine.py` | 14404 | `event_trigger` |
| `src/dnd_sim/io.py` | 232 | `event_trigger` |

## Dataset Counts Snapshot
- See `docs/deprecation/legacy_data_counts_20260304.tsv` for full machine-readable counts.
- Traits: `1742` files; top-level `type`: `0`, `source_type`: `1742`.
- Spells: `594` files; `meta` present: `0`; duplicate lookup key groups: `0`.
- Monsters: `191` files; `identity`: `191`, `stat_block`: `191`.
- Characters: `3` files; `class_level`: `0`, `class_levels`: `3`.

## Duplicate Spell Lookup Keys
