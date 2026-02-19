from __future__ import annotations

import argparse
import itertools
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dnd_sim.io import load_character_db, load_custom_simulation_runner, load_scenario


@dataclass(frozen=True)
class CandidateResult:
    idx: int
    overrides: dict[str, Any]
    mean_rounds: float
    median_rounds: float
    mean_damage_taken: dict[str, float]
    down_probabilities: dict[str, float]
    mean_ki_spent: dict[str, float]


def _deep_get(dct: dict[str, Any], path: str) -> Any:
    cur: Any = dct
    for part in path.split("."):
        if not isinstance(cur, dict):
            raise KeyError(path)
        cur = cur[part]
    return cur


def _deep_set(dct: dict[str, Any], path: str, value: Any) -> None:
    cur: Any = dct
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _product_dict(items: dict[str, list[Any]]) -> Iterable[dict[str, Any]]:
    keys = list(items.keys())
    vals = [items[k] for k in keys]
    for combo in itertools.product(*vals):
        yield {k: v for k, v in zip(keys, combo, strict=True)}


def _score(
    result: CandidateResult,
    *,
    target_rounds: float,
    target_down_rate: float,
) -> float:
    down_mean = sum(result.down_probabilities.values()) / max(
        1.0, float(len(result.down_probabilities))
    )
    return (result.mean_rounds - target_rounds) ** 2 + 4.0 * (down_mean - target_down_rate) ** 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sweep Phase 1 tuning parameters and optionally promote a candidate to canonical.\n\n"
            "This tool is designed to avoid 'offset confusion': you can sweep changes, then write "
            "the chosen values directly into the canonical scenario + DM card."
        )
    )
    p.add_argument(
        "--scenario",
        required=True,
        type=Path,
        help="Base scenario JSON (usually ley_heart_phase_1.json).",
    )
    p.add_argument(
        "--character-db",
        type=Path,
        default=None,
        help="Character DB dir (defaults to scenario.character_db_dir).",
    )
    p.add_argument("--trials", type=int, default=5000)
    p.add_argument("--seed", type=int, default=20260219)
    p.add_argument(
        "--grid",
        required=True,
        type=Path,
        help=(
            "JSON file mapping dot-path keys under assumption_overrides.custom_sim to lists of "
            "candidate values. Example key: boss_phase_1.guilt_fog_dc"
        ),
    )
    p.add_argument(
        "--allow-large",
        action="store_true",
        help="Allow very large sweep grids (otherwise the tool refuses to run).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON/MD directory (defaults to a temp dir).",
    )
    p.add_argument("--target-rounds", type=float, default=6.0)
    p.add_argument("--target-down-rate", type=float, default=0.02)
    p.add_argument(
        "--promote",
        type=int,
        default=None,
        help=(
            "Candidate index to promote. Writes values into the scenario JSON and updates the "
            "Phase 1 DM encounter card."
        ),
    )
    p.add_argument(
        "--dm-card",
        type=Path,
        default=Path(
            "/Users/rexputnam/Documents/projects/dnd_sim/river_line/encounters/ley_heart/phase_1/phase_1_dm_encounter_card.md"
        ),
        help="Path to DM encounter card markdown.",
    )
    return p


def _update_dm_card(dm_path: Path, boss_cfg: dict[str, Any]) -> None:
    lines = dm_path.read_text(encoding="utf-8").splitlines()

    def find_block(marker: str) -> tuple[int, int]:
        for i, line in enumerate(lines):
            if marker in line:
                j = i + 1
                while j < len(lines) and lines[j].strip() != "":
                    j += 1
                return i, j
        raise ValueError(f"DM card update failed: heading not found: {marker}")

    def replace_first_in_block(start: int, end: int, *, startswith: str, new_line: str) -> None:
        for i in range(start, end):
            if lines[i].startswith(startswith):
                lines[i] = new_line
                return
        raise ValueError(f"DM card update failed: line not found: {startswith}")

    # Harpoon Winch
    s, e = find_block("**Harpoon Winch (Present alive)**")
    replace_first_in_block(
        s,
        e,
        startswith="- **Attack:**",
        new_line=f"- **Attack:** +{int(boss_cfg['harpoon_to_hit'])} to hit, range 60/180, 1 target",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Hit:**",
        new_line=f"- **Hit:** {boss_cfg['harpoon_damage_expr']} piercing/force",
    )

    # Guilt Fog
    s, e = find_block("**Guilt Fog (Past alive; Recharge 5–6)**")
    replace_first_in_block(
        s,
        e,
        startswith="- **Save:**",
        new_line=f"- **Save:** DC {int(boss_cfg['guilt_fog_dc'])} Con",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Fail:**",
        new_line=(
            f"- **Fail:** {boss_cfg['guilt_fog_damage_expr']} necrotic and the target "
            "**can’t regain HP until the start of the Engine’s next turn**"
        ),
    )

    # Boiler Vent
    s, e = find_block("**Boiler Vent (Recharge 5–6)**")
    replace_first_in_block(
        s,
        e,
        startswith="- **Save:**",
        new_line=f"- **Save:** DC {int(boss_cfg['boiler_vent_dc'])} Con",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Fail:**",
        new_line=f"- **Fail:** {boss_cfg['boiler_vent_damage_expr']} fire and **pushed 10 ft**",
    )

    # Time Shear
    s, e = find_block("**Time Shear (Future alive; Recharge 4–6)**")
    replace_first_in_block(
        s,
        e,
        startswith="- **Save:**",
        new_line=f"- **Save:** DC {int(boss_cfg['time_shear_dc'])} Wis",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Fail:**",
        new_line=(
            f"- **Fail:** {boss_cfg['time_shear_damage_expr']} psychic and "
            "**Slowed until end of its next turn**:"
        ),
    )

    # Slam
    s, e = find_block("**Slam (Reach 10 ft; only if someone is in reach)**")
    replace_first_in_block(
        s,
        e,
        startswith="- **Attack:**",
        new_line=f"- **Attack:** +{int(boss_cfg['slam_to_hit'])} to hit, reach 10 ft, 1 target",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Hit:**",
        new_line=f"- **Hit:** {boss_cfg['slam_damage_expr']} bludgeoning",
    )

    # Tail Tap
    s, e = find_block("**Tail Tap (always)**")
    replace_first_in_block(
        s,
        e,
        startswith="- 1 creature within 10 ft makes",
        new_line=(
            f"- 1 creature within 10 ft makes **DC {int(boss_cfg['tail_tap_dc'])} Str** save "
            "or is **knocked prone**"
        ),
    )

    # Undertow
    s, e = find_block("**Undertow (Past alive)**")
    replace_first_in_block(
        s,
        e,
        startswith="- Choose a 10-ft square;",
        new_line=(
            f"- Choose a 10-ft square; creatures there make **DC {int(boss_cfg['undertow_dc'])} Str** "
            "save or are **restrained** until the start of their next turn"
        ),
    )

    # Arc Flash
    s, e = find_block("**Arc Flash (Present alive)**")
    replace_first_in_block(
        s,
        e,
        startswith="- Up to 2 creatures make",
        new_line=f"- Up to 2 creatures make **DC {int(boss_cfg['arc_flash_dc'])} Dex** save",
    )
    replace_first_in_block(
        s,
        e,
        startswith="- **Fail:**",
        new_line=(
            f"- **Fail:** {boss_cfg['arc_flash_damage_expr']} lightning and **no reactions** "
            "until the start of their next turn"
        ),
    )

    # Canonical setpoints line (keep stable).
    for i, line in enumerate(lines):
        if line.startswith("- Boss canonical setpoints (used by the sim):"):
            lines[i] = (
                "- Boss canonical setpoints (used by the sim): "
                "`damage_scalar=1.0`, `save_dc_offset=0`, `attack_bonus_offset=0`, "
                "`temporal_reversal_recharge_min=5`"
            )
            break
    else:
        raise ValueError("DM card update failed: canonical setpoints line not found.")

    dm_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()

    base_loaded = load_scenario(args.scenario)
    base_raw = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    custom_sim = base_raw.get("assumption_overrides", {}).get("custom_sim", {}).copy()

    grid_raw = json.loads(args.grid.read_text(encoding="utf-8"))
    if not isinstance(grid_raw, dict) or not grid_raw:
        raise ValueError("--grid must be a non-empty JSON object.")
    grid: dict[str, list[Any]] = {}
    for k, v in grid_raw.items():
        if not isinstance(k, str) or not isinstance(v, list) or not v:
            raise ValueError("Grid must map string keys to non-empty lists of values.")
        grid[k] = v

    combo_count = 1
    for values in grid.values():
        combo_count *= len(values)
    if (not args.allow_large) and combo_count > 500:
        raise ValueError(
            f"Sweep grid expands to {combo_count} candidates; reduce the grid or pass --allow-large."
        )

    # Make sweeps cheap: no plots/report/trial rows.
    custom_sim.setdefault("emit_plots", False)
    custom_sim.setdefault("emit_report", False)
    custom_sim.setdefault("emit_trial_rows", False)

    db_dir = args.character_db or Path(base_loaded.config.character_db_dir)
    character_db = load_character_db(Path(db_dir).resolve())
    runner = load_custom_simulation_runner(base_loaded)
    if runner is None:
        raise ValueError("Scenario does not define a custom simulation runner.")

    out_dir: Path
    if args.out is None:
        out_dir = Path(tempfile.mkdtemp(prefix="phase1_sweep_"))
    else:
        out_dir = args.out
        out_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[CandidateResult] = []

    for idx, combo in enumerate(_product_dict(grid)):
        candidate_sim = json.loads(json.dumps(custom_sim))
        for path, value in combo.items():
            _deep_set(candidate_sim, path, value)

        candidate_raw = json.loads(json.dumps(base_raw))
        candidate_raw.setdefault("assumption_overrides", {})
        candidate_raw["assumption_overrides"].setdefault("custom_sim", {})
        candidate_raw["assumption_overrides"]["custom_sim"] = candidate_sim

        candidate_config = base_loaded.config.model_copy(
            update={"assumption_overrides": candidate_raw.get("assumption_overrides", {})},
            deep=True,
        )
        candidate_loaded = base_loaded.model_copy(
            update={"config": candidate_config},
            deep=True,
        )

        with tempfile.TemporaryDirectory(prefix="phase1_sweep_run_") as td:
            payload = runner(
                scenario=candidate_loaded,
                character_db=character_db,
                trials=args.trials,
                seed=args.seed,
                run_dir=Path(td),
            )
        summary = payload["summary"]
        candidates.append(
            CandidateResult(
                idx=idx,
                overrides=combo,
                mean_rounds=float(summary["rounds"]["mean"]),
                median_rounds=float(summary["rounds"]["median"]),
                mean_damage_taken={
                    "isak": float(summary["damage_taken"]["isak"]["mean"]),
                    "fury": float(summary["damage_taken"]["fury"]["mean"]),
                    "squanch": float(summary["damage_taken"]["druid"]["mean"]),
                },
                down_probabilities={
                    "isak": float(summary["down_probabilities"]["isak"]),
                    "fury": float(summary["down_probabilities"]["fury"]),
                    "squanch": float(summary["down_probabilities"]["druid"]),
                },
                mean_ki_spent={
                    "isak": float(summary["isak_ki_spent"]["mean"]),
                    "fury": float(summary["fury_ki_spent"]["mean"]),
                },
            )
        )

    scored = [
        (
            cand,
            _score(cand, target_rounds=args.target_rounds, target_down_rate=args.target_down_rate),
        )
        for cand in candidates
    ]
    scored.sort(key=lambda t: t[1])

    out_json = out_dir / "sweep_results.json"
    out_md = out_dir / "sweep_results.md"

    out_json.write_text(
        json.dumps(
            {
                "scenario": str(args.scenario.resolve()),
                "trials": args.trials,
                "seed": args.seed,
                "grid": grid,
                "target_rounds": args.target_rounds,
                "target_down_rate": args.target_down_rate,
                "results": [
                    {
                        "idx": c.idx,
                        "score": s,
                        "overrides": c.overrides,
                        "mean_rounds": c.mean_rounds,
                        "median_rounds": c.median_rounds,
                        "mean_damage_taken": c.mean_damage_taken,
                        "down_probabilities": c.down_probabilities,
                        "mean_ki_spent": c.mean_ki_spent,
                    }
                    for c, s in scored
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Phase 1 Sweep Results",
        "",
        f"- Scenario: `{args.scenario.resolve()}`",
        f"- Trials per candidate: `{args.trials}`",
        f"- Seed: `{args.seed}`",
        f"- Target mean rounds: `{args.target_rounds}`",
        f"- Target mean down-rate: `{args.target_down_rate}`",
        "",
        "## Top Candidates",
        "",
        "| idx | score | mean rounds | down mean | overrides |",
        "|---:|---:|---:|---:|---|",
    ]
    for cand, score_val in scored[: min(20, len(scored))]:
        down_mean = sum(cand.down_probabilities.values()) / max(
            1.0, float(len(cand.down_probabilities))
        )
        lines.append(
            f"| {cand.idx} | {score_val:.4f} | {cand.mean_rounds:.3f} | {down_mean:.4f} | "
            f"`{cand.overrides}` |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.promote is not None:
        chosen = next((c for c, _s in scored if c.idx == args.promote), None)
        if chosen is None:
            raise ValueError(f"--promote idx not found: {args.promote}")
        # Apply chosen overrides to the scenario JSON itself.
        promote_raw = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        promote_custom = promote_raw.get("assumption_overrides", {}).get("custom_sim", {}).copy()
        for path, value in chosen.overrides.items():
            _deep_set(promote_custom, path, value)
        promote_raw.setdefault("assumption_overrides", {})
        promote_raw["assumption_overrides"].setdefault("custom_sim", {})
        promote_raw["assumption_overrides"]["custom_sim"] = promote_custom
        Path(args.scenario).write_text(json.dumps(promote_raw, indent=2) + "\n", encoding="utf-8")

        boss_cfg = _deep_get(promote_custom, "boss_phase_1")
        if not isinstance(boss_cfg, dict):
            raise ValueError("Expected custom_sim.boss_phase_1 to be an object.")
        _update_dm_card(args.dm_card, boss_cfg)

    print(f"Wrote: {out_json}")
    print(f"Wrote: {out_md}")
    if args.promote is not None:
        print(f"Promoted idx {args.promote} into: {args.scenario.resolve()}")
        print(f"Updated DM card: {args.dm_card.resolve()}")


if __name__ == "__main__":
    main()
