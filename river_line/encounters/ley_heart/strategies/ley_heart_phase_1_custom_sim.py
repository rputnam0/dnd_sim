from __future__ import annotations

import math
import random
import statistics
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def _roll_expr(rng: random.Random, expr: str, crit: bool = False) -> int:
    value = expr.replace(" ", "")
    if "d" not in value:
        return int(value)

    if "+" in value:
        dice, flat = value.split("+", 1)
        modifier = int(flat)
    elif "-" in value[1:]:
        dice, flat = value.split("-", 1)
        modifier = -int(flat)
    else:
        dice, modifier = value, 0

    n_str, sides_str = dice.split("d", 1)
    n_dice = int(n_str)
    sides = int(sides_str)
    if crit:
        n_dice *= 2
    return sum(rng.randint(1, sides) for _ in range(n_dice)) + modifier


def _attack_roll(
    rng: random.Random,
    atk_bonus: int,
    target_ac: int,
    *,
    disadvantage: bool = False,
) -> tuple[bool, bool]:
    natural = min(rng.randint(1, 20), rng.randint(1, 20)) if disadvantage else rng.randint(1, 20)
    crit = natural == 20
    hit = crit or (natural != 1 and natural + atk_bonus >= target_ac)
    return hit, crit


def _half_damage(value: int) -> int:
    return value // 2


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": float(statistics.mean(ordered)),
        "median": float(statistics.median(ordered)),
        "p10": float(ordered[int(0.10 * (len(ordered) - 1))]),
        "p90": float(ordered[int(0.90 * (len(ordered) - 1))]),
    }


def _summary_int(values: list[int]) -> dict[str, float]:
    return _summary([float(value) for value in values])


def _infer_actor_ac(actor: dict[str, Any]) -> int:
    raw_ac = actor.get("armor_class")
    if raw_ac is not None:
        try:
            value = int(raw_ac)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    dex_mod = (int(actor["ability_scores"]["dex"]) - 10) // 2
    wis_mod = (int(actor["ability_scores"]["wis"]) - 10) // 2
    con_mod = (int(actor["ability_scores"]["con"]) - 10) // 2
    traits = set(actor.get("traits", []))

    base_ac = 10 + dex_mod
    if "Unarmored Defense" in traits:
        base_ac = max(base_ac, 10 + dex_mod + wis_mod)
    if "Natural Armor" in traits:
        base_ac = max(base_ac, 12 + con_mod)
    return base_ac


def _plot_outputs(run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, str]:
    plot_dir = run_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid")
    plot_paths: dict[str, str] = {}

    rounds = [row["rounds"] for row in rows]
    plt.figure(figsize=(8, 4))
    sns.histplot(rounds, bins=min(20, max(rounds) - min(rounds) + 1))
    plt.title("Rounds Distribution")
    plt.xlabel("Rounds")
    plt.ylabel("Count")
    rounds_path = plot_dir / "rounds_histogram.png"
    plt.tight_layout()
    plt.savefig(rounds_path)
    plt.close()
    plot_paths["rounds_histogram"] = str(rounds_path)

    pulse_rows = []
    for row in rows:
        pulse_rows.append({"actor": "isak_wissa", "pulse_damage": row["isak_pulse_damage"]})
        pulse_rows.append({"actor": "furyen_fury", "pulse_damage": row["fury_pulse_damage"]})
        pulse_rows.append({"actor": "squanch_161607569", "pulse_damage": row["druid_pulse_damage"]})

    pulse_df = pd.DataFrame(pulse_rows)
    plt.figure(figsize=(9, 4))
    sns.boxplot(data=pulse_df, x="actor", y="pulse_damage")
    plt.title("Breakpoint Pulse Damage by Actor")
    pulse_path = plot_dir / "pulse_damage_boxplot.png"
    plt.tight_layout()
    plt.savefig(pulse_path)
    plt.close()
    plot_paths["pulse_damage_boxplot"] = str(pulse_path)

    ki_rows = []
    for row in rows:
        ki_rows.append({"actor": "isak_wissa", "ki_spent": row["isak_ki_spent"]})
        ki_rows.append({"actor": "furyen_fury", "ki_spent": row["fury_ki_spent"]})

    ki_df = pd.DataFrame(ki_rows)
    plt.figure(figsize=(8, 4))
    sns.barplot(data=ki_df, x="actor", y="ki_spent", estimator="mean")
    plt.title("Average Ki Spent")
    ki_path = plot_dir / "ki_spent_bar.png"
    plt.tight_layout()
    plt.savefig(ki_path)
    plt.close()
    plot_paths["ki_spent_bar"] = str(ki_path)

    return plot_paths


def _build_report(
    *,
    summary_payload: dict[str, Any],
    scenario_id: str,
    trials: int,
    seed: int,
    assumptions: dict[str, Any],
    plot_paths: dict[str, str],
) -> str:
    procedure_actors = assumptions.get("procedure_actors", {})
    procedure_mode = assumptions.get("procedure_mode")
    initiative_mode = assumptions.get("initiative_mode")
    pulse_targeting = assumptions.get("pulse_targeting")
    prism_pulse_magical = assumptions.get("prism_pulse_magical")
    breakpoints_per_attack = assumptions.get("breakpoints_per_attack")
    breakpoint_thresholds = assumptions.get("breakpoint_thresholds")
    heal_threshold_fraction = assumptions.get("heal_threshold_fraction")
    pylon_hp = assumptions.get("pylon_hp")
    pylon_ac = assumptions.get("pylon_ac")
    procedure_dc = assumptions.get("procedure_dc")
    unexposed_damage_multiplier = assumptions.get("unexposed_damage_multiplier")
    pulse_save_dc = summary_payload.get("pulse_save_dc", 15)
    boss_enabled = assumptions.get("boss_enabled")
    boss_action_priority = assumptions.get("boss_action_priority")
    boss_lair_priority = assumptions.get("boss_lair_priority")
    boss_target_mode = assumptions.get("boss_target_mode")
    boss_lair_mode = assumptions.get("boss_lair_mode")
    boss_damage_scalar = assumptions.get("boss_damage_scalar")
    boss_save_dc_offset = assumptions.get("boss_save_dc_offset")
    boss_attack_bonus_offset = assumptions.get("boss_attack_bonus_offset")
    phase_flicker_ac_bonus = assumptions.get("phase_flicker_ac_bonus")
    phase_flicker_threshold_bonus = assumptions.get("phase_flicker_threshold_bonus")
    phase_flicker_weak_threshold = assumptions.get("phase_flicker_weak_threshold")
    temporal_reversal_reduction = assumptions.get("temporal_reversal_reduction")
    temporal_reversal_chance = assumptions.get("temporal_reversal_chance")
    temporal_reversal_recharge_min = assumptions.get("temporal_reversal_recharge_min")
    pylon_alive_rounds = summary_payload.get("pylon_alive_rounds", {})
    past_alive_mean = float(pylon_alive_rounds.get("past", {}).get("mean", 0.0))
    present_alive_mean = float(pylon_alive_rounds.get("present", {}).get("mean", 0.0))
    future_alive_mean = float(pylon_alive_rounds.get("future", {}).get("mean", 0.0))
    lines = [
        "# Encounter Simulation Report",
        "",
        "## Scenario Config Snapshot",
        "",
        f"- Scenario ID: `{scenario_id}`",
        f"- Trials: `{trials}`",
        f"- Seed: `{seed}`",
        "",
        "## Assumptions",
        "",
        "- Focus fire order: `past -> present -> future`",
        f"- Pylon HP/AC: `{pylon_hp}` / `{pylon_ac}`",
        f"- Procedure DC: `{procedure_dc}`",
        f"- Breakpoint pulse save DC: `{pulse_save_dc}`",
        f"- Positioning mode: `{summary_payload.get('positioning_mode', 'none')}`",
        f"- Pylon-to-pylon distance (ft): `{summary_payload.get('pylon_to_pylon_ft', 'n/a')}`",
        f"- Boss-to-pylon distance (ft): `{summary_payload.get('boss_to_pylon_ft', 'n/a')}`",
        f"- Avoid boss center unless pulled: `{summary_payload.get('avoid_boss_center', True)}`",
        f"- Spread out between pylons: `{summary_payload.get('spread_out_positions', True)}`",
        f"- Formation mode: `{summary_payload.get('formation_mode', 'spread')}`",
        f"- Monk flurry policy: `{summary_payload.get('monk_flurry_policy', 'exposed_only')}`",
        f"- Procedure cost mode: `{summary_payload.get('procedure_cost_mode', 'action')}`",
        f"- Procedure fail-forward: `{summary_payload.get('procedure_fail_forward', 'none')}`",
        f"- Combat mode: `{summary_payload.get('combat_mode', 'sequential')}`",
        f"- Initiative order: `{initiative_mode}`",
        f"- Procedure mode: `{procedure_mode}`",
        f"- Breakpoint pulse targeting: `{pulse_targeting}`",
        (
            "- Procedure actors: "
            f"Past=`{procedure_actors.get('past')}`, "
            f"Present=`{procedure_actors.get('present')}`, "
            f"Future=`{procedure_actors.get('future')}`"
        ),
        f"- Prism pulse treated as magical (for Gnomish Cunning): `{prism_pulse_magical}`",
        f"- Breakpoints capped to one per attack: `{breakpoints_per_attack}`",
        f"- Breakpoint thresholds: `{breakpoint_thresholds}`",
        f"- Unexposed damage multiplier: `{unexposed_damage_multiplier}`",
        f"- Healing Word threshold (fraction max HP): `{heal_threshold_fraction}`",
        f"- Boss phase-1 actions enabled: `{boss_enabled}`",
        f"- Boss damage scalar: `{boss_damage_scalar}`",
        f"- Boss save DC offset: `{boss_save_dc_offset}`",
        f"- Boss attack bonus offset: `{boss_attack_bonus_offset}`",
        f"- Phase Flicker AC/threshold bonus: `{phase_flicker_ac_bonus}` / `{phase_flicker_threshold_bonus}`",
        f"- Phase Flicker weak pylon threshold: `{phase_flicker_weak_threshold}`",
        f"- Temporal Reversal damage reduction: `{temporal_reversal_reduction}`",
        f"- Temporal Reversal recharge min (d6): `{temporal_reversal_recharge_min}`",
        f"- Temporal Reversal trigger chance (if not recharge): `{temporal_reversal_chance}`",
        f"- Boss action priority: `{boss_action_priority}`",
        f"- Boss lair priority: `{boss_lair_priority}`",
        f"- Boss target mode: `{boss_target_mode}`",
        f"- Boss lair mode: `{boss_lair_mode}`",
        "- Monk Evasion modeled for Present (DEX) pulses",
        "- Isak Savage Attacker modeled once per turn",
        "",
        "## Outcome Overview",
        "",
        f"- Party success rate: `{summary_payload['party_success_rate']:.3f}`",
        f"- Mean rounds: `{summary_payload['rounds']['mean']:.3f}`",
        "",
        "## Metrics",
        "",
        "| Metric | Isak | Fury | Druid |",
        "| --- | ---: | ---: | ---: |",
        (
            f"| Mean damage dealt | {summary_payload['damage_dealt']['isak']['mean']:.2f} | "
            f"{summary_payload['damage_dealt']['fury']['mean']:.2f} | "
            f"{summary_payload['damage_dealt']['druid']['mean']:.2f} |"
        ),
        (
            f"| Mean damage taken | {summary_payload['damage_taken']['isak']['mean']:.2f} | "
            f"{summary_payload['damage_taken']['fury']['mean']:.2f} | "
            f"{summary_payload['damage_taken']['druid']['mean']:.2f} |"
        ),
        (
            f"| Mean pulse damage | {summary_payload['isak_pulse_damage']['mean']:.2f} | "
            f"{summary_payload['fury_pulse_damage']['mean']:.2f} | "
            f"{summary_payload['druid_pulse_damage']['mean']:.2f} |"
        ),
        (
            f"| Mean remaining HP | {summary_payload['remaining_hp']['isak']['mean']:.2f} | "
            f"{summary_payload['remaining_hp']['fury']['mean']:.2f} | "
            f"{summary_payload['remaining_hp']['druid']['mean']:.2f} |"
        ),
        (
            f"| Down probability | {summary_payload['down_probabilities']['isak']:.3f} | "
            f"{summary_payload['down_probabilities']['fury']:.3f} | "
            f"{summary_payload['down_probabilities']['druid']:.3f} |"
        ),
        "",
        "## Resources",
        "",
        f"- Isak mean ki spent: `{summary_payload['isak_ki_spent']['mean']:.3f}`",
        f"- Fury mean ki spent: `{summary_payload['fury_ki_spent']['mean']:.3f}`",
        f"- Mean Healing Word casts: `{summary_payload['healing_word_casts']['mean']:.3f}`",
        f"- Mean level-1 slots spent: `{summary_payload['spell_slot_1_spent']['mean']:.3f}`",
        f"- Wholeness of Body use rate: `{summary_payload['wholeness_used_rate']:.3f}`",
        "",
        "## Procedures",
        "",
        (
            f"- Mean attempts: Isak=`{summary_payload['procedure_attempts']['isak']['mean']:.3f}`, "
            f"Fury=`{summary_payload['procedure_attempts']['fury']['mean']:.3f}`, "
            f"Druid=`{summary_payload['procedure_attempts']['druid']['mean']:.3f}`"
        ),
        (
            f"- Mean successes: Isak=`{summary_payload['procedure_successes']['isak']['mean']:.3f}`, "
            f"Fury=`{summary_payload['procedure_successes']['fury']['mean']:.3f}`, "
            f"Druid=`{summary_payload['procedure_successes']['druid']['mean']:.3f}`"
        ),
        "",
        "## Boss Pressure",
        "",
        (
            f"- Mean boss damage dealt: Isak=`{summary_payload['boss_damage_dealt']['isak']['mean']:.2f}`, "
            f"Fury=`{summary_payload['boss_damage_dealt']['fury']['mean']:.2f}`, "
            f"Druid=`{summary_payload['boss_damage_dealt']['druid']['mean']:.2f}`"
        ),
        (
            f"- Mean boss turns / lair turns: `{summary_payload['boss_turns']['mean']:.2f}` / "
            f"`{summary_payload['boss_lair_turns']['mean']:.2f}`"
        ),
        (
            f"- Mean pylon alive rounds: Past=`{past_alive_mean:.2f}`, "
            f"Present=`{present_alive_mean:.2f}`, "
            f"Future=`{future_alive_mean:.2f}`"
        ),
        "",
        "## Plots",
        "",
    ]
    for label, path in sorted(plot_paths.items()):
        lines.append(f"- {label}: `plots/{Path(path).name}`")
    lines.append("")
    return "\n".join(lines)


def run_custom_simulation(
    *,
    scenario: Any,
    character_db: dict[str, dict[str, Any]],
    trials: int,
    seed: int,
    run_dir: Path,
) -> dict[str, Any]:
    rng = random.Random(seed)

    party_ids = scenario.config.party
    by_id = {pid: character_db[pid] for pid in party_ids}
    isak = by_id.get("isak_wissa")
    fury = by_id.get("furyen_fury")
    if isak is None:
        raise ValueError("Expected party member 'isak_wissa' in scenario party.")
    if fury is None:
        raise ValueError("Expected party member 'furyen_fury' in scenario party.")
    druid_party_ids = [pid for pid in party_ids if pid not in {"isak_wissa", "furyen_fury"}]
    if len(druid_party_ids) != 1:
        raise ValueError("Expected exactly one non-monk party member for druid role.")
    druid = by_id[druid_party_ids[0]]

    custom_cfg = (scenario.config.assumption_overrides or {}).get("custom_sim", {})
    emit_plots = bool(custom_cfg.get("emit_plots", True))
    emit_report = bool(custom_cfg.get("emit_report", True))
    emit_trial_rows = bool(custom_cfg.get("emit_trial_rows", True))
    procedure_actors = custom_cfg.get(
        "procedure_actors",
        {"past": "druid", "present": "fury", "future": "druid"},
    )
    procedure_mode = custom_cfg.get("procedure_mode", "pass_on_fail")
    initiative_mode = custom_cfg.get("initiative_mode", "random_fixed")
    pulse_targeting = custom_cfg.get("pulse_targeting", "single_alternating_monk")
    prism_pulse_magical = bool(custom_cfg.get("prism_pulse_magical", True))
    breakpoints_per_attack = bool(custom_cfg.get("breakpoints_per_attack", True))
    breakpoint_thresholds_raw = custom_cfg.get("breakpoint_thresholds", [30, 15])
    breakpoint_thresholds = sorted(
        {int(value) for value in breakpoint_thresholds_raw}, reverse=True
    )
    if len(breakpoint_thresholds) != 2:
        raise ValueError("custom_sim.breakpoint_thresholds must contain exactly two values.")
    high_breakpoint, low_breakpoint = breakpoint_thresholds
    if high_breakpoint <= low_breakpoint:
        raise ValueError("custom_sim.breakpoint_thresholds must be strictly descending.")
    if low_breakpoint < 0:
        raise ValueError("custom_sim.breakpoint_thresholds must be >= 0.")
    pylon_hp = int(custom_cfg.get("pylon_hp", 45))
    pylon_ac = int(custom_cfg.get("pylon_ac", 15))
    proc_dc = int(custom_cfg.get("procedure_dc", 15))
    pulse_save_dc = int(custom_cfg.get("pulse_save_dc", 15))
    unexposed_damage_multiplier = float(custom_cfg.get("unexposed_damage_multiplier", 0.5))
    positioning_mode = str(custom_cfg.get("positioning_mode", "none"))
    pylon_to_pylon_ft = float(custom_cfg.get("pylon_to_pylon_ft", 30.0))
    avoid_boss_center = bool(custom_cfg.get("avoid_boss_center", True))
    spread_out_positions = bool(custom_cfg.get("spread_out_positions", True))
    formation_mode = str(custom_cfg.get("formation_mode", "spread"))
    monk_flurry_policy = str(custom_cfg.get("monk_flurry_policy", "exposed_only"))
    procedure_cost_mode = str(custom_cfg.get("procedure_cost_mode", "action"))
    procedure_fail_forward = str(custom_cfg.get("procedure_fail_forward", "none"))
    if procedure_fail_forward not in {"none", "next_attempt_advantage"}:
        raise ValueError(
            "custom_sim.procedure_fail_forward must be one of: 'none', 'next_attempt_advantage'"
        )
    combat_mode = str(custom_cfg.get("combat_mode", "sequential"))
    actor_focus_raw = custom_cfg.get("actor_focus", {})
    actor_focus: dict[str, list[str]] = {}
    if isinstance(actor_focus_raw, dict):
        for actor_id in ("isak", "fury", "druid"):
            raw = actor_focus_raw.get(actor_id)
            if isinstance(raw, list):
                actor_focus[actor_id] = [str(value) for value in raw]
    healing_cfg = custom_cfg.get("healing", {})
    healing_word_enabled = bool(healing_cfg.get("healing_word", True))
    healing_word_threshold = float(healing_cfg.get("threshold_fraction", 0.5))
    wholeness_enabled = bool(healing_cfg.get("wholeness_of_body", True))
    wholeness_threshold = float(healing_cfg.get("wholeness_threshold_fraction", 0.5))
    boss_cfg = custom_cfg.get("boss_phase_1", {})
    boss_enabled = bool(boss_cfg.get("enabled", True))
    boss_action_priority = [
        str(value)
        for value in boss_cfg.get(
            "action_priority",
            ["guilt_fog", "boiler_vent", "time_shear", "harpoon_winch", "slam"],
        )
    ]
    boss_target_mode = str(boss_cfg.get("target_mode", "lowest_hp"))
    boss_lair_mode = str(boss_cfg.get("lair_mode", "priority"))
    boss_lair_priority = [
        str(value)
        for value in boss_cfg.get("lair_priority", ["arc_flash", "phase_flicker", "undertow"])
    ]
    guilt_fog_targets = max(1, int(boss_cfg.get("guilt_fog_targets", 3)))
    boiler_vent_targets = max(1, int(boss_cfg.get("boiler_vent_targets", 2)))
    arc_flash_targets = max(1, int(boss_cfg.get("arc_flash_targets", 2)))
    boss_damage_scalar = float(boss_cfg.get("damage_scalar", 1.0))
    boss_save_dc_offset = int(boss_cfg.get("save_dc_offset", 0))
    boss_attack_bonus_offset = int(boss_cfg.get("attack_bonus_offset", 0))
    harpoon_to_hit = int(boss_cfg.get("harpoon_to_hit", 8))
    harpoon_damage_expr = str(boss_cfg.get("harpoon_damage_expr", "2d10+4"))
    harpoon_escape_dc = int(boss_cfg.get("harpoon_escape_dc", 16))
    guilt_fog_dc = int(boss_cfg.get("guilt_fog_dc", 16))
    guilt_fog_damage_expr = str(boss_cfg.get("guilt_fog_damage_expr", "4d8"))
    boiler_vent_dc = int(boss_cfg.get("boiler_vent_dc", 16))
    boiler_vent_damage_expr = str(boss_cfg.get("boiler_vent_damage_expr", "4d8"))
    time_shear_dc = int(boss_cfg.get("time_shear_dc", 15))
    time_shear_damage_expr = str(boss_cfg.get("time_shear_damage_expr", "3d8"))
    slam_to_hit = int(boss_cfg.get("slam_to_hit", 9))
    slam_damage_expr = str(boss_cfg.get("slam_damage_expr", "2d8+6"))
    tail_tap_dc = int(boss_cfg.get("tail_tap_dc", 15))
    undertow_dc = int(boss_cfg.get("undertow_dc", 15))
    arc_flash_dc = int(boss_cfg.get("arc_flash_dc", 15))
    arc_flash_damage_expr = str(boss_cfg.get("arc_flash_damage_expr", "2d6"))
    phase_flicker_ac_bonus = int(boss_cfg.get("phase_flicker_ac_bonus", 2))
    phase_flicker_threshold_bonus = int(boss_cfg.get("phase_flicker_threshold_bonus", 5))
    phase_flicker_weak_threshold = int(
        boss_cfg.get("phase_flicker_weak_threshold", high_breakpoint)
    )
    temporal_reversal_reduction = int(boss_cfg.get("temporal_reversal_reduction", 10))
    temporal_reversal_recharge_min_raw = boss_cfg.get("temporal_reversal_recharge_min")
    temporal_reversal_recharge_min: int | None = (
        int(temporal_reversal_recharge_min_raw)
        if temporal_reversal_recharge_min_raw is not None
        else None
    )
    if temporal_reversal_recharge_min is not None:
        if temporal_reversal_recharge_min < 2 or temporal_reversal_recharge_min > 6:
            raise ValueError("boss_phase_1.temporal_reversal_recharge_min must be between 2 and 6.")
        temporal_reversal_chance: float | None = None
    else:
        temporal_reversal_chance = float(boss_cfg.get("temporal_reversal_chance", 1.0))
        temporal_reversal_chance = max(0.0, min(1.0, temporal_reversal_chance))
    boss_to_pylon_ft = pylon_to_pylon_ft / math.sqrt(3.0)

    max_rounds = int((scenario.config.termination_rules or {}).get("max_rounds", 20))

    druid_past_bonus = max(
        druid["skill_mods"].get("performance", -999),
        druid["skill_mods"].get("persuasion", -999),
        druid["skill_mods"].get("religion", -999),
    )
    druid_future_bonus = max(
        druid["skill_mods"].get("investigation", -999),
        druid["skill_mods"].get("insight", -999),
    )
    fury_present_bonus = fury["skill_mods"].get("arcana", 0)
    druid_wis_mod = (int(druid["ability_scores"]["wis"]) - 10) // 2
    dex_mod_by_id = {
        "isak": (int(isak["ability_scores"]["dex"]) - 10) // 2,
        "fury": (int(fury["ability_scores"]["dex"]) - 10) // 2,
        "druid": (int(druid["ability_scores"]["dex"]) - 10) // 2,
    }

    has_evasion = {
        "isak": "Evasion" in isak.get("traits", []),
        "fury": "Evasion" in fury.get("traits", []),
        "druid": "Evasion" in druid.get("traits", []),
    }
    has_savage_attacker = {
        "isak": "Savage Attacker" in isak.get("traits", []),
        "fury": "Savage Attacker" in fury.get("traits", []),
        "druid": "Savage Attacker" in druid.get("traits", []),
    }
    has_gnomish_cunning = {
        "isak": "Gnomish Cunning" in isak.get("traits", []),
        "fury": "Gnomish Cunning" in fury.get("traits", []),
        "druid": "Gnomish Cunning" in druid.get("traits", []),
    }

    save_mods = {
        "isak": {
            "str": isak["save_mods"]["str"],
            "con": isak["save_mods"]["con"],
            "dex": isak["save_mods"]["dex"],
            "wis": isak["save_mods"]["wis"],
        },
        "fury": {
            "str": fury["save_mods"]["str"],
            "con": fury["save_mods"]["con"],
            "dex": fury["save_mods"]["dex"],
            "wis": fury["save_mods"]["wis"],
        },
        "druid": {
            "str": druid["save_mods"]["str"],
            "con": druid["save_mods"]["con"],
            "dex": druid["save_mods"]["dex"],
            "wis": druid["save_mods"]["wis"],
        },
    }
    player_ac = {
        "isak": _infer_actor_ac(isak),
        "fury": _infer_actor_ac(fury),
        "druid": _infer_actor_ac(druid),
    }

    druid_attack_profile = None
    for attack in druid.get("attacks", []):
        damage_expr = str(attack.get("damage", "")).strip()
        if "d" in damage_expr:
            druid_attack_profile = attack
            break
    druid_attack = (
        int(druid_attack_profile.get("to_hit", 8)) if druid_attack_profile else 8,
        str(druid_attack_profile.get("damage", "2d10+5")) if druid_attack_profile else "2d10+5",
    )
    isak_staff = (8, "1d6+5")
    isak_unarmed = (7, "1d6+4")
    fury_main = (8, "1d6+5")

    rounds_all: list[float] = []
    isak_ki_all: list[float] = []
    fury_ki_all: list[float] = []
    isak_pulse_all: list[float] = []
    fury_pulse_all: list[float] = []
    druid_pulse_all: list[float] = []
    isak_hp_all: list[float] = []
    fury_hp_all: list[float] = []
    druid_hp_all: list[float] = []
    isak_hit_all: list[float] = []
    fury_hit_all: list[float] = []
    druid_hit_all: list[float] = []
    past_kill_round_all: list[float] = []
    present_kill_round_all: list[float] = []
    future_kill_round_all: list[float] = []
    isak_damage_dealt_all: list[int] = []
    fury_damage_dealt_all: list[int] = []
    druid_damage_dealt_all: list[int] = []
    isak_damage_taken_all: list[int] = []
    fury_damage_taken_all: list[int] = []
    druid_damage_taken_all: list[int] = []
    healing_word_casts_all: list[int] = []
    spell_slot_1_spent_all: list[int] = []
    wholeness_used_all: list[int] = []
    isak_proc_attempts_all: list[int] = []
    fury_proc_attempts_all: list[int] = []
    druid_proc_attempts_all: list[int] = []
    isak_proc_successes_all: list[int] = []
    fury_proc_successes_all: list[int] = []
    druid_proc_successes_all: list[int] = []
    boss_turns_all: list[int] = []
    boss_lair_turns_all: list[int] = []
    boss_isak_damage_all: list[int] = []
    boss_fury_damage_all: list[int] = []
    boss_druid_damage_all: list[int] = []
    action_names = ("harpoon_winch", "guilt_fog", "boiler_vent", "time_shear", "slam")
    lair_names = ("undertow", "arc_flash", "phase_flicker")
    legendary_names = ("temporal_reversal", "winch_pull", "tail_tap")
    boss_action_usage_all: dict[str, list[int]] = {name: [] for name in action_names}
    boss_lair_usage_all: dict[str, list[int]] = {name: [] for name in lair_names}
    boss_legendary_usage_all: dict[str, list[int]] = {name: [] for name in legendary_names}
    deaths_all = {"isak": 0, "fury": 0, "druid": 0}

    isak_downed = 0
    fury_downed = 0
    druid_downed = 0
    party_success = 0

    trial_rows: list[dict[str, Any]] = []

    def _roll_d20(*, advantage: bool = False, disadvantage: bool = False) -> int:
        if advantage and disadvantage:
            advantage = disadvantage = False
        if advantage:
            return max(rng.randint(1, 20), rng.randint(1, 20))
        if disadvantage:
            return min(rng.randint(1, 20), rng.randint(1, 20))
        return rng.randint(1, 20)

    def _apply_unexposed_modifier(damage: int, exposed: bool) -> int:
        if exposed:
            return damage
        adjusted = int(damage * unexposed_damage_multiplier)
        return max(0, adjusted)

    actor_ids = ("isak", "fury", "druid")

    def _is_dead(pid: str, state: dict[str, Any]) -> bool:
        return bool(state.get(f"{pid}_dead", False))

    def _is_conscious(pid: str, state: dict[str, Any]) -> bool:
        return (not _is_dead(pid, state)) and state[f"{pid}_hp"] > 0

    def _is_unconscious(pid: str, state: dict[str, Any]) -> bool:
        return (not _is_dead(pid, state)) and state[f"{pid}_hp"] == 0

    def _party_defeated(state: dict[str, Any]) -> bool:
        return not any(_is_conscious(pid, state) for pid in actor_ids)

    def _apply_damage(pid: str, damage: int, *, state: dict[str, Any]) -> int:
        if damage <= 0 or _is_dead(pid, state):
            return 0

        if state[f"{pid}_hp"] == 0:
            state[f"{pid}_death_fails"] += 1
            if state[f"{pid}_death_fails"] >= 3:
                state[f"{pid}_dead"] = True
            return 0

        next_hp = state[f"{pid}_hp"] - damage
        if next_hp > 0:
            state[f"{pid}_hp"] = next_hp
            state[f"{pid}_damage_taken"] += damage
            return damage

        applied = state[f"{pid}_hp"]
        state[f"{pid}_damage_taken"] += applied
        state[f"{pid}_hp"] = 0
        state[f"{pid}_downed"] = True
        state[f"{pid}_death_successes"] = 0
        state[f"{pid}_death_fails"] = 0
        state[f"{pid}_stabilized"] = False
        return applied

    def _apply_heal(
        pid: str,
        amount: int,
        *,
        state: dict[str, Any],
        max_hp_by_id: dict[str, int],
    ) -> None:
        if amount <= 0 or _is_dead(pid, state):
            return
        if state.get(f"{pid}_no_heal_until_boss_turn", False):
            return

        if state[f"{pid}_hp"] == 0:
            state[f"{pid}_hp"] = min(max_hp_by_id[pid], amount)
            state[f"{pid}_downed"] = False
            state[f"{pid}_death_successes"] = 0
            state[f"{pid}_death_fails"] = 0
            state[f"{pid}_stabilized"] = False
            state[f"{pid}_healing_received"] += min(max_hp_by_id[pid], amount)
            return

        before = state[f"{pid}_hp"]
        state[f"{pid}_hp"] = min(max_hp_by_id[pid], before + amount)
        state[f"{pid}_healing_received"] += state[f"{pid}_hp"] - before

    def _death_save(pid: str, *, state: dict[str, Any]) -> None:
        if (
            not _is_unconscious(pid, state)
            or _is_dead(pid, state)
            or state.get(f"{pid}_stabilized")
        ):
            return

        roll = _roll_d20()
        if roll == 1:
            state[f"{pid}_death_fails"] += 2
        elif roll == 20:
            state[f"{pid}_hp"] = 1
            state[f"{pid}_downed"] = False
            state[f"{pid}_death_successes"] = 0
            state[f"{pid}_death_fails"] = 0
            state[f"{pid}_stabilized"] = False
            return
        elif roll >= 10:
            state[f"{pid}_death_successes"] += 1
        else:
            state[f"{pid}_death_fails"] += 1

        if state[f"{pid}_death_fails"] >= 3:
            state[f"{pid}_dead"] = True
        elif state[f"{pid}_death_successes"] >= 3:
            state[f"{pid}_stabilized"] = True

    def _conscious_actor_ids(state: dict[str, Any]) -> list[str]:
        return [pid for pid in actor_ids if _is_conscious(pid, state)]

    def _choose_targets(state: dict[str, Any], count: int) -> list[str]:
        conscious = _conscious_actor_ids(state)
        if not conscious:
            return []
        if boss_target_mode == "random":
            shuffled = list(conscious)
            rng.shuffle(shuffled)
            return shuffled[:count]
        if boss_target_mode == "highest_hp":
            ranked = sorted(conscious, key=lambda pid: (-state[f"{pid}_hp"], rng.random()))
            return ranked[:count]
        ranked = sorted(conscious, key=lambda pid: (state[f"{pid}_hp"], rng.random()))
        return ranked[:count]

    def _roll_save(
        pid: str,
        save_key: str,
        dc: int,
        *,
        state: dict[str, Any],
        magical: bool,
    ) -> bool:
        auto_fail = save_key in {"dex", "str"} and _is_unconscious(pid, state)
        advantage = bool(
            magical and has_gnomish_cunning.get(pid, False) and save_key in {"int", "wis", "cha"}
        )
        disadvantage = bool(save_key == "dex" and state.get(f"{pid}_restrained", False))
        if auto_fail:
            return False
        return (
            _roll_d20(advantage=advantage, disadvantage=disadvantage) + save_mods[pid][save_key]
        ) >= dc

    def _ability_mod(score: int) -> int:
        return (int(score) - 10) // 2

    def _escape_grapple_bonus(pid: str) -> int:
        actor = {"isak": isak, "fury": fury, "druid": druid}[pid]
        skill_mods = actor.get("skill_mods", {})
        athletics = skill_mods.get("athletics")
        acrobatics = skill_mods.get("acrobatics")
        if athletics is not None or acrobatics is not None:
            return max(int(athletics or -999), int(acrobatics or -999))
        return max(
            _ability_mod(int(actor["ability_scores"]["str"])),
            _ability_mod(int(actor["ability_scores"]["dex"])),
        )

    def _attempt_escape_grapple(*, pid: str, state: dict[str, Any]) -> bool:
        if not state.get(f"{pid}_grappled", False):
            return False
        return (_roll_d20() + _escape_grapple_bonus(pid)) >= harpoon_escape_dc

    def _node_distance_ft(a: str, b: str, *, boss_to_pylon_ft: float) -> float:
        if a == b:
            return 0.0
        if "center" in {a, b}:
            return boss_to_pylon_ft
        return pylon_to_pylon_ft

    def _home_nodes_for_round(*, current_pylon: str, pulse_taker: str) -> dict[str, str]:
        nodes = ["past", "present", "future"]
        if formation_mode == "double_monk_focus":
            other_nodes = [n for n in nodes if n != current_pylon]
            druid_node = other_nodes[0]
            return {"isak": current_pylon, "fury": current_pylon, "druid": druid_node}
        if formation_mode == "split_monks_two_pylons":
            return {"isak": "past", "fury": "present", "druid": "future"}
        if formation_mode == "stack_all":
            return {"isak": current_pylon, "fury": current_pylon, "druid": current_pylon}
        if (not spread_out_positions) or formation_mode == "cluster":
            return {"isak": current_pylon, "fury": current_pylon, "druid": current_pylon}
        other_nodes = [n for n in nodes if n != current_pylon]
        if pulse_taker not in {"isak", "fury"}:
            pulse_taker = "isak"
        other_monk = "fury" if pulse_taker == "isak" else "isak"
        return {
            pulse_taker: current_pylon,
            other_monk: other_nodes[0],
            "druid": other_nodes[1],
        }

    def _set_round_positions(
        *, current_pylon: str, pulse_taker: str, state: dict[str, Any]
    ) -> dict[str, str]:
        if positioning_mode == "none":
            home = {"isak": current_pylon, "fury": current_pylon, "druid": current_pylon}
        else:
            home = _home_nodes_for_round(current_pylon=current_pylon, pulse_taker=pulse_taker)
        for pid in actor_ids:
            if not _is_conscious(pid, state):
                continue
            if state.get(f"{pid}_grappled", False):
                continue
            state[f"{pid}_pos"] = home[pid]
        return home

    def _actors_within_pulse_radius(
        *, pylon_type: str, pulse_taker: str, state: dict[str, Any]
    ) -> list[str]:
        if positioning_mode == "none":
            return _pulse_targets(pulse_target=pulse_taker, state=state)

        for pid in actor_ids:
            if _is_dead(pid, state):
                continue
            if state.get(f"{pid}_pos") == pylon_type:
                return [pid]
        return []

    def apply_pulse(targets: list[str], pylon_type: str, state: dict[str, Any]) -> None:
        if pylon_type == "past":
            save_key = "con"
        elif pylon_type == "present":
            save_key = "dex"
        else:
            save_key = "wis"

        for target in targets:
            if _is_dead(target, state):
                continue
            is_magical = prism_pulse_magical if pylon_type == "future" else True
            success = _roll_save(target, save_key, pulse_save_dc, state=state, magical=is_magical)

            rolled = _roll_expr(rng, "2d6")
            if save_key == "dex" and has_evasion.get(target, False):
                damage = 0 if success else _half_damage(rolled)
            else:
                damage = _half_damage(rolled) if success else rolled

            _apply_damage(target, damage, state=state)
            state[f"{target}_pulse_damage"] += damage
            state[f"{target}_pulse_hits"] += 1
            if (not success) and pylon_type == "past":
                state[f"{target}_no_reactions"] = True
            if (not success) and pylon_type == "future":
                state[f"{target}_next_disadvantage"] = True

    def _pulse_targets(*, pulse_target: str, state: dict[str, Any]) -> list[str]:
        if pulse_targeting == "aoe_all_party":
            return [pid for pid in actor_ids if not _is_dead(pid, state)]

        if pulse_targeting == "single_alternating_monk":
            other_monk = "fury" if pulse_target == "isak" else "isak"
            for candidate in (pulse_target, other_monk, "druid"):
                if not _is_dead(candidate, state):
                    return [candidate]
            return []

        return [pulse_target] if not _is_dead(pulse_target, state) else []

    def _apply_attack_damage(
        *,
        hp: int,
        damage: int,
        pylon_type: str,
        trig_high: bool,
        trig_low: bool,
        pulse_target: str,
        pylon_damage_threshold: int,
        temporal_reversal_available: bool,
        state: dict[str, Any],
    ) -> tuple[int, bool, bool, str, int, bool]:
        if damage <= 0 or hp <= 0:
            return hp, trig_high, trig_low, pulse_target, 0, temporal_reversal_available

        if pylon_damage_threshold > 0 and damage < pylon_damage_threshold:
            return hp, trig_high, trig_low, pulse_target, 0, temporal_reversal_available

        will_cross_high = (
            (not trig_high) and hp > high_breakpoint and (hp - damage) <= high_breakpoint
        )
        will_cross_low = (not trig_low) and hp > low_breakpoint and (hp - damage) <= low_breakpoint
        if temporal_reversal_available and (will_cross_high or will_cross_low):
            if temporal_reversal_recharge_min is not None:
                should_reverse = bool(state.get("boss_temporal_reversal_ready", False))
            else:
                should_reverse = bool(temporal_reversal_chance is not None) and (
                    rng.random() < float(temporal_reversal_chance)
                )
            if should_reverse:
                damage = max(0, damage - temporal_reversal_reduction)
                temporal_reversal_available = False
                state["boss_legendary_temporal_reversal"] += 1
                state["boss_temporal_reversal_ready"] = False
                if damage <= 0:
                    return hp, trig_high, trig_low, pulse_target, 0, temporal_reversal_available

        prev_hp = hp
        if breakpoints_per_attack:
            if not trig_high and hp > high_breakpoint:
                cap_to = high_breakpoint
            elif not trig_low and hp > low_breakpoint:
                cap_to = low_breakpoint
            else:
                cap_to = 0
            if hp - damage < cap_to:
                damage = hp - cap_to

        hp -= damage

        if not breakpoints_per_attack:
            if not trig_high and prev_hp > high_breakpoint and hp <= high_breakpoint:
                hp = high_breakpoint
            elif not trig_low and prev_hp > low_breakpoint and hp <= low_breakpoint:
                hp = low_breakpoint

        if not trig_high and hp == high_breakpoint:
            trig_high = True
            apply_pulse(
                _actors_within_pulse_radius(
                    pylon_type=pylon_type, pulse_taker=pulse_target, state=state
                ),
                pylon_type,
                state,
            )
            if positioning_mode == "none" and pulse_targeting == "single_alternating_monk":
                pulse_target = "fury" if pulse_target == "isak" else "isak"
        elif not trig_low and hp == low_breakpoint:
            trig_low = True
            apply_pulse(
                _actors_within_pulse_radius(
                    pylon_type=pylon_type, pulse_taker=pulse_target, state=state
                ),
                pylon_type,
                state,
            )
            if positioning_mode == "none" and pulse_targeting == "single_alternating_monk":
                pulse_target = "fury" if pulse_target == "isak" else "isak"

        return hp, trig_high, trig_low, pulse_target, damage, temporal_reversal_available

    def druid_turn(exposed: bool, target_ac: int, state: dict[str, Any]) -> int:
        if state["druid_hp"] <= 0:
            return 0
        hit, crit = _attack_roll(
            rng,
            druid_attack[0],
            target_ac,
            disadvantage=state["druid_next_disadvantage"],
        )
        state["druid_next_disadvantage"] = False
        if not hit:
            return 0
        damage = _roll_expr(rng, druid_attack[1], crit=crit)
        return _apply_unexposed_modifier(damage, exposed)

    def _monk_ranged_profile(pid: str) -> tuple[int, str]:
        actor = {"isak": isak, "fury": fury}[pid]
        dex_mod = _ability_mod(int(actor["ability_scores"]["dex"]))
        # Assumption: the non-melee monk uses a shortbow from another pylon node.
        # We reuse the monk's baseline attack bonus to avoid inventing proficiency/magic details.
        to_hit = isak_staff[0] if pid == "isak" else fury_main[0]
        return to_hit, f"1d6+{dex_mod}"

    def monk_ranged_turn(
        pid: str,
        exposed: bool,
        target_ac: int,
        *,
        action_attacks: int = 2,
        state: dict[str, Any],
    ) -> list[int]:
        if state[f"{pid}_hp"] <= 0:
            return []
        to_hit, dmg_expr = _monk_ranged_profile(pid)
        damages: list[int] = []
        for _ in range(max(0, int(action_attacks))):
            hit, crit = _attack_roll(
                rng,
                to_hit,
                target_ac,
                disadvantage=state[f"{pid}_next_disadvantage"],
            )
            state[f"{pid}_next_disadvantage"] = False
            if hit:
                damage = _roll_expr(rng, dmg_expr, crit=crit)
                damages.append(_apply_unexposed_modifier(damage, exposed))
        return damages

    def isak_turn(
        exposed: bool,
        target_ac: int,
        *,
        action_attacks: int = 2,
        bonus_action_available: bool = True,
        state: dict[str, Any],
        slowed: bool,
    ) -> list[int]:
        if state["isak_hp"] <= 0:
            return []
        damages: list[int] = []
        savage_used = False

        for _ in range(max(0, int(action_attacks))):
            hit, crit = _attack_roll(
                rng,
                isak_staff[0],
                target_ac,
                disadvantage=state["isak_next_disadvantage"],
            )
            state["isak_next_disadvantage"] = False
            if hit:
                damage = _roll_expr(rng, isak_staff[1], crit=crit)
                if has_savage_attacker.get("isak", False) and not savage_used:
                    damage = max(damage, _roll_expr(rng, isak_staff[1], crit=crit))
                    savage_used = True
                damages.append(_apply_unexposed_modifier(damage, exposed))

        bonus_attacks = 0 if (slowed or (not bonus_action_available)) else 1
        if (not slowed) and bonus_action_available and state["isak_ki"] > 0:
            if monk_flurry_policy == "always_if_ki" or (
                monk_flurry_policy == "exposed_only" and exposed
            ):
                bonus_attacks = 2
                state["isak_ki"] -= 1
                state["isak_ki_spent"] += 1

        for _ in range(bonus_attacks):
            hit, crit = _attack_roll(
                rng,
                isak_unarmed[0],
                target_ac,
                disadvantage=state["isak_next_disadvantage"],
            )
            state["isak_next_disadvantage"] = False
            if hit:
                damage = _roll_expr(rng, isak_unarmed[1], crit=crit)
                if has_savage_attacker.get("isak", False) and not savage_used:
                    damage = max(damage, _roll_expr(rng, isak_unarmed[1], crit=crit))
                    savage_used = True
                damages.append(_apply_unexposed_modifier(damage, exposed))

        return damages

    def fury_turn(
        exposed: bool,
        target_ac: int,
        *,
        action_attacks: int = 2,
        bonus_action_available: bool = True,
        state: dict[str, Any],
        slowed: bool,
    ) -> list[int]:
        if state["fury_hp"] <= 0:
            return []
        damages: list[int] = []

        for _ in range(max(0, int(action_attacks))):
            hit, crit = _attack_roll(
                rng,
                fury_main[0],
                target_ac,
                disadvantage=state["fury_next_disadvantage"],
            )
            state["fury_next_disadvantage"] = False
            if hit:
                damage = _roll_expr(rng, fury_main[1], crit=crit)
                damages.append(_apply_unexposed_modifier(damage, exposed))

        bonus_attacks = 0 if (slowed or (not bonus_action_available)) else 1
        if (not slowed) and bonus_action_available and state["fury_ki"] > 0:
            if monk_flurry_policy == "always_if_ki" or (
                monk_flurry_policy == "exposed_only" and exposed
            ):
                bonus_attacks = 2
                state["fury_ki"] -= 1
                state["fury_ki_spent"] += 1

        for _ in range(bonus_attacks):
            hit, crit = _attack_roll(
                rng,
                fury_main[0],
                target_ac,
                disadvantage=state["fury_next_disadvantage"],
            )
            state["fury_next_disadvantage"] = False
            if hit:
                damage = _roll_expr(rng, fury_main[1], crit=crit)
                damages.append(_apply_unexposed_modifier(damage, exposed))

        return damages

    def _boss_recharge(state: dict[str, Any]) -> None:
        if state["boss_guilt_fog_ready"] is False and rng.randint(1, 6) >= 5:
            state["boss_guilt_fog_ready"] = True
        if state["boss_boiler_vent_ready"] is False and rng.randint(1, 6) >= 5:
            state["boss_boiler_vent_ready"] = True
        if state["boss_time_shear_ready"] is False and rng.randint(1, 6) >= 4:
            state["boss_time_shear_ready"] = True
        if (
            temporal_reversal_recharge_min is not None
            and state["boss_temporal_reversal_ready"] is False
            and rng.randint(1, 6) >= temporal_reversal_recharge_min
        ):
            state["boss_temporal_reversal_ready"] = True

    def _record_boss_damage(target: str, applied: int, state: dict[str, Any]) -> None:
        if applied <= 0:
            return
        state[f"boss_{target}_damage"] += applied

    def _scale_boss_damage(damage: int) -> int:
        return max(0, int(round(damage * boss_damage_scalar)))

    def _boss_lair_action(
        *,
        active_pylons: set[str],
        pylon_hp_by_type: dict[str, int],
        state: dict[str, Any],
    ) -> None:
        if not boss_enabled or _party_defeated(state):
            return

        def _do_arc_flash() -> None:
            targets = _choose_targets(state, arc_flash_targets)
            for target in targets:
                success = _roll_save(
                    target,
                    "dex",
                    arc_flash_dc + boss_save_dc_offset,
                    state=state,
                    magical=True,
                )
                rolled = _roll_expr(rng, arc_flash_damage_expr)
                if has_evasion.get(target, False):
                    damage = 0 if success else _half_damage(rolled)
                else:
                    damage = _half_damage(rolled) if success else rolled
                damage = _scale_boss_damage(damage)
                applied = _apply_damage(target, damage, state=state)
                _record_boss_damage(target, applied, state)
                if not success:
                    state[f"{target}_no_reactions"] = True
            state["boss_lair_turns"] += 1
            state["boss_lair_arc_flash"] += 1

        def _do_phase_flicker(target_pylon: str) -> None:
            state[f"pylon_ac_bonus_{target_pylon}"] = max(
                int(state.get(f"pylon_ac_bonus_{target_pylon}", 0)), phase_flicker_ac_bonus
            )
            state[f"pylon_damage_threshold_bonus_{target_pylon}"] = max(
                int(state.get(f"pylon_damage_threshold_bonus_{target_pylon}", 0)),
                phase_flicker_threshold_bonus,
            )
            state["boss_lair_turns"] += 1
            state["boss_lair_phase_flicker"] += 1

        def _do_undertow() -> None:
            target = _choose_targets(state, 1)
            if target:
                success = _roll_save(
                    target[0],
                    "str",
                    undertow_dc + boss_save_dc_offset,
                    state=state,
                    magical=True,
                )
                if not success:
                    state[f"{target[0]}_restrained"] = True
            state["boss_lair_turns"] += 1
            state["boss_lair_undertow"] += 1

        if boss_lair_mode == "best_available":
            weakest_hp = min((pylon_hp_by_type.get(p, 9999) for p in active_pylons), default=9999)
            if (
                ("future" in active_pylons)
                and (weakest_hp <= phase_flicker_weak_threshold)
                and (
                    (phase_flicker_ac_bonus > 0)
                    or (phase_flicker_threshold_bonus > 0)
                    or (temporal_reversal_reduction > 0)
                )
            ):
                target_pylon = min(
                    (p for p in active_pylons),
                    key=lambda p: (pylon_hp_by_type.get(p, 9999), rng.random()),
                )
                _do_phase_flicker(target_pylon)
                return
            if ("present" in active_pylons) and arc_flash_targets > 0:
                _do_arc_flash()
                return
            if "past" in active_pylons:
                _do_undertow()
                return
            if ("future" in active_pylons) and (
                (phase_flicker_ac_bonus > 0)
                or (phase_flicker_threshold_bonus > 0)
                or (temporal_reversal_reduction > 0)
            ):
                _do_phase_flicker("future")
                return
            return

        for lair_action in boss_lair_priority:
            if lair_action == "arc_flash" and "present" in active_pylons:
                _do_arc_flash()
                return
            if lair_action == "phase_flicker" and "future" in active_pylons:
                _do_phase_flicker("future")
                return
            if lair_action == "undertow" and "past" in active_pylons:
                _do_undertow()
                return

    def _boss_action(*, active_pylons: set[str], state: dict[str, Any]) -> None:
        if not boss_enabled or _party_defeated(state):
            return
        _boss_recharge(state)
        available: set[str] = set()

        def _center_targets() -> list[str]:
            if positioning_mode == "none":
                return []
            return [
                pid
                for pid in actor_ids
                if _is_conscious(pid, state) and state.get(f"{pid}_pos") == "center"
            ]

        center_targets = _center_targets()
        if center_targets:
            available.update({"boiler_vent", "slam"})
        elif positioning_mode != "none" and boss_to_pylon_ft <= 15.0:
            close_pylon_targets = [
                pid
                for pid in actor_ids
                if _is_conscious(pid, state)
                and state.get(f"{pid}_pos") in {"past", "present", "future"}
            ]
            if close_pylon_targets:
                available.add("boiler_vent")
        if "past" in active_pylons and state["boss_guilt_fog_ready"]:
            available.add("guilt_fog")
        if "present" in active_pylons:
            available.add("harpoon_winch")
        if "future" in active_pylons and state["boss_time_shear_ready"]:
            available.add("time_shear")
        if not state["boss_boiler_vent_ready"]:
            available.discard("boiler_vent")

        chosen: str | None = None
        for action_name in boss_action_priority:
            if action_name in available:
                chosen = action_name
                break
        if chosen is None:
            if "present" in active_pylons:
                chosen = "harpoon_winch"
            elif "future" in active_pylons and state["boss_time_shear_ready"]:
                chosen = "time_shear"
            elif "past" in active_pylons and state["boss_guilt_fog_ready"]:
                chosen = "guilt_fog"
            else:
                return

        state["boss_turns"] += 1
        state[f"boss_action_{chosen}"] += 1

        def _cone_targets(max_targets: int, *, max_range_ft: float = 30.0) -> list[str]:
            if positioning_mode == "none":
                return _choose_targets(state, max_targets)
            nodes = ["past", "present", "future", "center"]
            best_nodes: list[str] = []
            best_count = -1
            for node in nodes:
                if node == "center":
                    continue
                if (
                    _node_distance_ft("center", node, boss_to_pylon_ft=boss_to_pylon_ft)
                    > max_range_ft
                ):
                    continue
                candidates = [
                    pid
                    for pid in actor_ids
                    if _is_conscious(pid, state) and state.get(f"{pid}_pos") == node
                ]
                if len(candidates) > best_count:
                    best_count = len(candidates)
                    best_nodes = [node]
                elif len(candidates) == best_count and len(candidates) > 0:
                    best_nodes.append(node)
            if not best_nodes:
                return []
            chosen_node = rng.choice(best_nodes)
            chosen = [
                pid
                for pid in actor_ids
                if _is_conscious(pid, state) and state.get(f"{pid}_pos") == chosen_node
            ]
            rng.shuffle(chosen)
            return chosen[:max_targets]

        if chosen == "guilt_fog":
            targets = _cone_targets(guilt_fog_targets)
            for target in targets:
                success = _roll_save(
                    target,
                    "con",
                    guilt_fog_dc + boss_save_dc_offset,
                    state=state,
                    magical=True,
                )
                rolled = _roll_expr(rng, guilt_fog_damage_expr)
                damage = _half_damage(rolled) if success else rolled
                damage = _scale_boss_damage(damage)
                applied = _apply_damage(target, damage, state=state)
                _record_boss_damage(target, applied, state)
                if not success:
                    state[f"{target}_no_heal_until_boss_turn"] = True
            state["boss_guilt_fog_ready"] = False
            return

        if chosen == "boiler_vent":
            if positioning_mode == "none":
                targets = _choose_targets(state, boiler_vent_targets)
            else:
                if center_targets:
                    targets = list(center_targets)
                    rng.shuffle(targets)
                    targets = targets[:boiler_vent_targets]
                else:
                    targets = _cone_targets(boiler_vent_targets, max_range_ft=15.0)
            for target in targets:
                success = _roll_save(
                    target,
                    "con",
                    boiler_vent_dc + boss_save_dc_offset,
                    state=state,
                    magical=True,
                )
                rolled = _roll_expr(rng, boiler_vent_damage_expr)
                damage = _half_damage(rolled) if success else rolled
                damage = _scale_boss_damage(damage)
                applied = _apply_damage(target, damage, state=state)
                _record_boss_damage(target, applied, state)
            state["boss_boiler_vent_ready"] = False
            return

        target_list = _choose_targets(state, 1)
        if not target_list:
            return
        target = target_list[0]

        if chosen == "time_shear":
            success = _roll_save(
                target,
                "wis",
                time_shear_dc + boss_save_dc_offset,
                state=state,
                magical=True,
            )
            rolled = _roll_expr(rng, time_shear_damage_expr)
            damage = _half_damage(rolled) if success else rolled
            damage = _scale_boss_damage(damage)
            applied = _apply_damage(target, damage, state=state)
            _record_boss_damage(target, applied, state)
            if not success:
                state[f"{target}_slow_next_turn"] = True
            state["boss_time_shear_ready"] = False
            return

        if chosen == "harpoon_winch":
            hit, crit = _attack_roll(
                rng,
                harpoon_to_hit + boss_attack_bonus_offset,
                player_ac[target],
                disadvantage=False,
            )
            if hit:
                damage = _roll_expr(rng, harpoon_damage_expr, crit=crit)
                damage = _scale_boss_damage(damage)
                applied = _apply_damage(target, damage, state=state)
                _record_boss_damage(target, applied, state)
                state[f"{target}_grappled"] = True
            return

        if positioning_mode != "none" and state.get(f"{target}_pos") != "center":
            return
        hit, crit = _attack_roll(rng, slam_to_hit + boss_attack_bonus_offset, player_ac[target])
        if hit:
            damage = _roll_expr(rng, slam_damage_expr, crit=crit)
            damage = _scale_boss_damage(damage)
            applied = _apply_damage(target, damage, state=state)
            _record_boss_damage(target, applied, state)

    def _boss_legendary_after_turn(
        *, active_pylons: set[str], state: dict[str, Any], end_of_round: bool
    ) -> None:
        if (not boss_enabled) or (not state["boss_legendary_available"]) or _party_defeated(state):
            return
        if ("future" in active_pylons) and (not end_of_round):
            return
        if "present" in active_pylons:
            grappled = [
                pid
                for pid in actor_ids
                if state.get(f"{pid}_grappled", False) and _is_conscious(pid, state)
            ]
            if grappled:
                state["boss_legendary_winch_pull"] += 1
                if positioning_mode != "none":
                    if boss_target_mode == "random":
                        chosen_pid = rng.choice(grappled)
                    elif boss_target_mode == "highest_hp":
                        chosen_pid = max(grappled, key=lambda pid: state[f"{pid}_hp"])
                    else:
                        chosen_pid = min(grappled, key=lambda pid: state[f"{pid}_hp"])
                    current = str(state.get(f"{chosen_pid}_pos", "past"))
                    if current != "center" and (
                        _node_distance_ft("center", current, boss_to_pylon_ft=boss_to_pylon_ft)
                        <= 20.0
                    ):
                        state[f"{chosen_pid}_pos"] = "center"
                state["boss_legendary_available"] = False
                return
        if positioning_mode != "none":
            target_list = [
                pid
                for pid in actor_ids
                if _is_conscious(pid, state) and state.get(f"{pid}_pos") == "center"
            ]
            if target_list:
                rng.shuffle(target_list)
                target_list = [target_list[0]]
        else:
            target_list = _choose_targets(state, 1)
        if not target_list:
            return
        target = target_list[0]
        success = _roll_save(
            target,
            "str",
            tail_tap_dc + boss_save_dc_offset,
            state=state,
            magical=False,
        )
        if not success:
            state[f"{target}_next_disadvantage"] = True
        state["boss_legendary_tail_tap"] += 1
        state["boss_legendary_available"] = False

    def _procedure_bonus(pid: str, pylon_type: str) -> int:
        actor = {"isak": isak, "fury": fury, "druid": druid}[pid]
        skill_mods = actor.get("skill_mods", {})
        if pylon_type == "past":
            return max(
                skill_mods.get("performance", -999),
                skill_mods.get("persuasion", -999),
                skill_mods.get("religion", -999),
            )
        if pylon_type == "present":
            thieves = skill_mods.get("thieves_tools", -999)
            if thieves is None:
                thieves = -999
            return max(skill_mods.get("arcana", -999), thieves)
        return max(skill_mods.get("investigation", -999), skill_mods.get("insight", -999))

    def _next_in_order(current: str, order: list[str]) -> str:
        idx = order.index(current)
        return order[(idx + 1) % len(order)]

    def _maybe_healing_word(
        *,
        state: dict[str, Any],
        max_hp_by_id: dict[str, int],
    ) -> bool:
        if not healing_word_enabled or not _is_conscious("druid", state):
            return False
        if bool(state.get("druid_bonus_used", False)):
            return False
        if state["druid_spell_slots_1"] <= 0:
            return False

        downed = [pid for pid in actor_ids if _is_unconscious(pid, state)]
        if downed:
            target = downed[0]
        else:
            below_threshold = [
                pid
                for pid in actor_ids
                if _is_conscious(pid, state)
                and (state[f"{pid}_hp"] / max_hp_by_id[pid]) < healing_word_threshold
            ]
            if not below_threshold:
                return False
            target = min(
                below_threshold,
                key=lambda pid: state[f"{pid}_hp"] / max_hp_by_id[pid],
            )

        state["druid_spell_slots_1"] -= 1
        state["druid_healing_word_casts"] += 1
        state["druid_bonus_used"] = True
        heal_amount = _roll_expr(rng, "1d4") + druid_wis_mod
        _apply_heal(target, heal_amount, state=state, max_hp_by_id=max_hp_by_id)
        return True

    def _maybe_wholeness_of_body(
        *,
        state: dict[str, Any],
        max_hp_by_id: dict[str, int],
        isak_attempting_procedure: bool,
    ) -> bool:
        if (
            (not wholeness_enabled)
            or (not _is_conscious("isak", state))
            or state["isak_wholeness_used"]
            or isak_attempting_procedure
        ):
            return False
        if (state["isak_hp"] / max_hp_by_id["isak"]) >= wholeness_threshold:
            return False
        state["isak_wholeness_used"] = True
        _apply_heal("isak", 24, state=state, max_hp_by_id=max_hp_by_id)
        return True

    for trial in range(trials):
        max_hp_by_id = {
            "isak": int(isak["max_hp"]),
            "fury": int(fury["max_hp"]),
            "druid": int(druid["max_hp"]),
        }
        initiative_order = ["isak", "fury", "druid"]
        if initiative_mode == "random_fixed":
            rng.shuffle(initiative_order)
        elif initiative_mode == "rolled_fixed":
            init_scores: list[tuple[float, str]] = []
            for pid in initiative_order:
                score = _roll_d20() + dex_mod_by_id[pid]
                init_scores.append((score + rng.random() * 1e-6, pid))
            init_scores.sort(key=lambda t: t[0], reverse=True)
            initiative_order = [pid for _score, pid in init_scores]

        state: dict[str, Any] = {
            "isak_hp": max_hp_by_id["isak"],
            "fury_hp": max_hp_by_id["fury"],
            "druid_hp": max_hp_by_id["druid"],
            "isak_pos": "past",
            "fury_pos": "present",
            "druid_pos": "future",
            "isak_bonus_used": False,
            "fury_bonus_used": False,
            "druid_bonus_used": False,
            "isak_ki": int(isak["resources"]["ki"]["max"]),
            "fury_ki": int(fury["resources"]["ki"]["max"]),
            "isak_ki_spent": 0,
            "fury_ki_spent": 0,
            "isak_pulse_damage": 0,
            "fury_pulse_damage": 0,
            "druid_pulse_damage": 0,
            "isak_pulse_hits": 0,
            "fury_pulse_hits": 0,
            "druid_pulse_hits": 0,
            "isak_next_disadvantage": False,
            "fury_next_disadvantage": False,
            "druid_next_disadvantage": False,
            "isak_death_successes": 0,
            "fury_death_successes": 0,
            "druid_death_successes": 0,
            "isak_death_fails": 0,
            "fury_death_fails": 0,
            "druid_death_fails": 0,
            "isak_stabilized": False,
            "fury_stabilized": False,
            "druid_stabilized": False,
            "isak_downed": False,
            "fury_downed": False,
            "druid_downed": False,
            "isak_dead": False,
            "fury_dead": False,
            "druid_dead": False,
            "druid_spell_slots_1": int(druid["resources"]["spell_slots"]["1"]),
            "druid_healing_word_casts": 0,
            "isak_wholeness_used": False,
            "isak_proc_attempts": 0,
            "fury_proc_attempts": 0,
            "druid_proc_attempts": 0,
            "isak_proc_successes": 0,
            "fury_proc_successes": 0,
            "druid_proc_successes": 0,
            "isak_damage_dealt": 0,
            "fury_damage_dealt": 0,
            "druid_damage_dealt": 0,
            "isak_damage_taken": 0,
            "fury_damage_taken": 0,
            "druid_damage_taken": 0,
            "isak_healing_received": 0,
            "fury_healing_received": 0,
            "druid_healing_received": 0,
            "isak_no_heal_until_boss_turn": False,
            "fury_no_heal_until_boss_turn": False,
            "druid_no_heal_until_boss_turn": False,
            "isak_slow_next_turn": False,
            "fury_slow_next_turn": False,
            "druid_slow_next_turn": False,
            "isak_no_reactions": False,
            "fury_no_reactions": False,
            "druid_no_reactions": False,
            "isak_restrained": False,
            "fury_restrained": False,
            "druid_restrained": False,
            "isak_grappled": False,
            "fury_grappled": False,
            "druid_grappled": False,
            "boss_turns": 0,
            "boss_lair_turns": 0,
            "boss_isak_damage": 0,
            "boss_fury_damage": 0,
            "boss_druid_damage": 0,
            "boss_action_harpoon_winch": 0,
            "boss_action_guilt_fog": 0,
            "boss_action_boiler_vent": 0,
            "boss_action_time_shear": 0,
            "boss_action_slam": 0,
            "boss_lair_undertow": 0,
            "boss_lair_arc_flash": 0,
            "boss_lair_phase_flicker": 0,
            "boss_legendary_temporal_reversal": 0,
            "boss_legendary_winch_pull": 0,
            "boss_legendary_tail_tap": 0,
            "boss_legendary_available": False,
            "boss_temporal_reversal_ready": True,
            "boss_guilt_fog_ready": True,
            "boss_boiler_vent_ready": True,
            "boss_time_shear_ready": True,
            "pylon_ac_bonus_past": 0,
            "pylon_ac_bonus_present": 0,
            "pylon_ac_bonus_future": 0,
            "pylon_damage_threshold_bonus_past": 0,
            "pylon_damage_threshold_bonus_present": 0,
            "pylon_damage_threshold_bonus_future": 0,
        }

        def _run_sequential_trial() -> tuple[int, dict[str, int | None], bool]:
            rounds = 0
            pulse_target = "isak" if rng.random() < 0.5 else "fury"
            trial_success = True
            pylon_kill_round: dict[str, int | None] = {
                "past": None,
                "present": None,
                "future": None,
            }

            for pylon in ("past", "present", "future"):
                hp = pylon_hp
                trig_high = False
                trig_low = False
                exposed = False
                exposed_by: str | None = None
                exposed_fresh = False
                proc_advantage_next = False

                if procedure_mode == "fixed_actor":
                    procedure_candidate = str(procedure_actors[pylon])
                else:
                    procedure_candidate = initiative_order[0]

                while hp > 0 and (not _party_defeated(state)) and rounds < max_rounds:
                    rounds += 1
                    if pylon == "past":
                        active_pylons = {"past", "present", "future"}
                    elif pylon == "present":
                        active_pylons = {"present", "future"}
                    else:
                        active_pylons = {"future"}

                    for p in ("past", "present", "future"):
                        state[f"pylon_ac_bonus_{p}"] = 0
                        state[f"pylon_damage_threshold_bonus_{p}"] = 0
                    state["boss_legendary_available"] = bool(boss_enabled)
                    home_nodes = _set_round_positions(
                        current_pylon=pylon,
                        pulse_taker=pulse_target,
                        state=state,
                    )

                    if boss_enabled:
                        for pid in actor_ids:
                            state[f"{pid}_no_heal_until_boss_turn"] = False
                        _boss_lair_action(
                            active_pylons=active_pylons,
                            pylon_hp_by_type={pylon: int(hp)},
                            state=state,
                        )
                        _boss_action(active_pylons=active_pylons, state=state)

                    for actor_id in initiative_order:
                        if hp <= 0 or _party_defeated(state):
                            break
                        end_of_round = actor_id == initiative_order[-1]

                        def _end_turn() -> None:
                            nonlocal exposed, exposed_by, exposed_fresh
                            if exposed and exposed_by == actor_id:
                                if exposed_fresh:
                                    exposed_fresh = False
                                else:
                                    exposed = False
                                    exposed_by = None
                                    exposed_fresh = False
                            _boss_legendary_after_turn(
                                active_pylons=active_pylons,
                                state=state,
                                end_of_round=end_of_round,
                            )

                        state[f"{actor_id}_no_reactions"] = False
                        state[f"{actor_id}_restrained"] = False
                        state[f"{actor_id}_bonus_used"] = False
                        slowed_this_turn = bool(state[f"{actor_id}_slow_next_turn"])
                        state[f"{actor_id}_slow_next_turn"] = False

                        if (
                            positioning_mode != "none"
                            and avoid_boss_center
                            and state.get(f"{actor_id}_pos") == "center"
                            and (not state.get(f"{actor_id}_grappled", False))
                        ):
                            state[f"{actor_id}_pos"] = home_nodes.get(actor_id, pylon)

                        if (
                            positioning_mode != "none"
                            and state.get(f"{actor_id}_pos") == "center"
                            and state.get(f"{actor_id}_grappled", False)
                        ):
                            if _attempt_escape_grapple(pid=actor_id, state=state):
                                state[f"{actor_id}_grappled"] = False
                                state[f"{actor_id}_pos"] = home_nodes.get(actor_id, pylon)
                            _end_turn()
                            continue

                        if _is_unconscious(actor_id, state):
                            _death_save(actor_id, state=state)
                            if _is_unconscious(actor_id, state) or _is_dead(actor_id, state):
                                _end_turn()
                                continue

                        if actor_id == "druid":
                            if slowed_this_turn:
                                if _maybe_healing_word(state=state, max_hp_by_id=max_hp_by_id):
                                    _end_turn()
                                    continue
                            else:
                                _maybe_healing_word(state=state, max_hp_by_id=max_hp_by_id)

                        if actor_id == "isak":
                            isak_attempting_procedure = (
                                procedure_mode == "pass_on_fail"
                                and (actor_id == procedure_candidate)
                                and (not exposed)
                                and _is_conscious("isak", state)
                            )
                            if _maybe_wholeness_of_body(
                                state=state,
                                max_hp_by_id=max_hp_by_id,
                                isak_attempting_procedure=isak_attempting_procedure,
                            ):
                                _end_turn()
                                continue

                        if procedure_mode != "fixed_actor":
                            for _ in range(len(initiative_order)):
                                if _is_conscious(procedure_candidate, state):
                                    break
                                procedure_candidate = _next_in_order(
                                    procedure_candidate, initiative_order
                                )

                        should_attempt_procedure = (
                            _is_conscious(actor_id, state)
                            and (not exposed)
                            and (
                                (
                                    procedure_mode == "fixed_actor"
                                    and actor_id == procedure_candidate
                                )
                                or (
                                    procedure_mode != "fixed_actor"
                                    and actor_id == procedure_candidate
                                )
                            )
                        )
                        if (
                            should_attempt_procedure
                            and positioning_mode != "none"
                            and pylon in {"past", "present"}
                            and state.get(f"{actor_id}_grappled", False)
                        ):
                            if state.get(f"{actor_id}_pos") != pylon:
                                should_attempt_procedure = False
                        if (
                            should_attempt_procedure
                            and procedure_cost_mode == "bonus_action"
                            and bool(state.get(f"{actor_id}_bonus_used", False))
                        ):
                            should_attempt_procedure = False

                        action_attacks_lost = 0
                        if should_attempt_procedure:
                            state[f"{actor_id}_proc_attempts"] += 1
                            bonus = _procedure_bonus(actor_id, pylon)
                            advantage = (
                                procedure_fail_forward == "next_attempt_advantage"
                                and proc_advantage_next
                            )
                            proc_advantage_next = False
                            if (_roll_d20(advantage=advantage) + bonus) >= proc_dc:
                                exposed = True
                                exposed_by = actor_id
                                exposed_fresh = True
                                state[f"{actor_id}_proc_successes"] += 1
                            else:
                                if procedure_fail_forward == "next_attempt_advantage":
                                    proc_advantage_next = True
                                if procedure_mode != "fixed_actor":
                                    procedure_candidate = _next_in_order(
                                        procedure_candidate, initiative_order
                                    )
                            if procedure_cost_mode == "one_attack" and actor_id in {"isak", "fury"}:
                                action_attacks_lost = 1
                            elif procedure_cost_mode == "bonus_action":
                                state[f"{actor_id}_bonus_used"] = True
                                if slowed_this_turn:
                                    _end_turn()
                                    continue
                            else:
                                _end_turn()
                                continue

                        if not _is_conscious(actor_id, state):
                            _end_turn()
                            continue

                        target_ac = pylon_ac + int(state.get(f"pylon_ac_bonus_{pylon}", 0))
                        action_attacks = (
                            max(0, 2 - action_attacks_lost) if actor_id in {"isak", "fury"} else 0
                        )
                        bonus_action_available = not bool(
                            state.get(f"{actor_id}_bonus_used", False)
                        )
                        attack_damages: list[int] = []
                        if actor_id == "druid":
                            attack_damages.append(druid_turn(exposed, target_ac, state))
                        elif actor_id == "isak":
                            if positioning_mode != "none" and state.get("isak_pos") != pylon:
                                attack_damages.extend(
                                    monk_ranged_turn(
                                        "isak",
                                        exposed,
                                        target_ac,
                                        action_attacks=action_attacks,
                                        state=state,
                                    )
                                )
                            else:
                                attack_damages.extend(
                                    isak_turn(
                                        exposed,
                                        target_ac,
                                        action_attacks=action_attacks,
                                        bonus_action_available=bonus_action_available,
                                        state=state,
                                        slowed=slowed_this_turn,
                                    )
                                )
                        else:
                            if positioning_mode != "none" and state.get("fury_pos") != pylon:
                                attack_damages.extend(
                                    monk_ranged_turn(
                                        "fury",
                                        exposed,
                                        target_ac,
                                        action_attacks=action_attacks,
                                        state=state,
                                    )
                                )
                            else:
                                attack_damages.extend(
                                    fury_turn(
                                        exposed,
                                        target_ac,
                                        action_attacks=action_attacks,
                                        bonus_action_available=bonus_action_available,
                                        state=state,
                                        slowed=slowed_this_turn,
                                    )
                                )

                        for attack_damage in attack_damages:
                            hp, trig_high, trig_low, pulse_target, applied, temporal_available = (
                                _apply_attack_damage(
                                    hp=hp,
                                    damage=attack_damage,
                                    pylon_type=pylon,
                                    trig_high=trig_high,
                                    trig_low=trig_low,
                                    pulse_target=pulse_target,
                                    pylon_damage_threshold=int(
                                        state.get(f"pylon_damage_threshold_bonus_{pylon}", 0)
                                    ),
                                    temporal_reversal_available=bool(
                                        state["boss_legendary_available"]
                                        and ("future" in active_pylons)
                                    ),
                                    state=state,
                                )
                            )
                            if "future" in active_pylons:
                                state["boss_legendary_available"] = temporal_available
                            if applied:
                                state[f"{actor_id}_damage_dealt"] += applied
                            if hp <= 0 or _party_defeated(state):
                                break

                        _end_turn()

                if hp <= 0:
                    pylon_kill_round[pylon] = rounds
                if hp > 0:
                    trial_success = False
                    break

            return rounds, pylon_kill_round, trial_success

        def _run_parallel_trial() -> tuple[int, dict[str, int | None], bool]:
            rounds = 0
            pulse_target = "isak" if rng.random() < 0.5 else "fury"
            pylons = ("past", "present", "future")
            pylon_kill_round: dict[str, int | None] = {
                "past": None,
                "present": None,
                "future": None,
            }
            pylon_state: dict[str, dict[str, Any]] = {
                pylon: {
                    "hp": int(pylon_hp),
                    "trig_high": False,
                    "trig_low": False,
                    "exposed": False,
                    "exposed_by": None,
                    "exposed_fresh": False,
                    "proc_advantage_next": False,
                }
                for pylon in pylons
            }

            def _active() -> set[str]:
                return {pylon for pylon in pylons if int(pylon_state[pylon]["hp"]) > 0}

            def _choose_focus(actor_id: str) -> str | None:
                active = _active()
                if not active:
                    return None
                focus = actor_focus.get(actor_id, [])
                for pylon in focus:
                    if pylon in active:
                        return pylon
                if positioning_mode != "none":
                    current = state.get(f"{actor_id}_pos")
                    if isinstance(current, str) and current in active:
                        return current
                return min(active, key=lambda p: (int(pylon_state[p]["hp"]), rng.random()))

            while _active() and (not _party_defeated(state)) and rounds < max_rounds:
                rounds += 1
                active_pylons = _active()

                for pylon in pylons:
                    state[f"pylon_ac_bonus_{pylon}"] = 0
                    state[f"pylon_damage_threshold_bonus_{pylon}"] = 0
                state["boss_legendary_available"] = bool(boss_enabled)

                home_nodes = _set_round_positions(
                    current_pylon="past",
                    pulse_taker=pulse_target,
                    state=state,
                )

                if boss_enabled:
                    for pid in actor_ids:
                        state[f"{pid}_no_heal_until_boss_turn"] = False
                    _boss_lair_action(
                        active_pylons=active_pylons,
                        pylon_hp_by_type={p: int(pylon_state[p]["hp"]) for p in active_pylons},
                        state=state,
                    )
                    _boss_action(active_pylons=active_pylons, state=state)

                for actor_id in initiative_order:
                    if _party_defeated(state) or (not _active()):
                        break
                    end_of_round = actor_id == initiative_order[-1]
                    active_pylons = _active()

                    def _end_turn() -> None:
                        for pylon in pylons:
                            if pylon_state[pylon]["exposed_by"] == actor_id:
                                if bool(pylon_state[pylon].get("exposed_fresh", False)):
                                    pylon_state[pylon]["exposed_fresh"] = False
                                else:
                                    pylon_state[pylon]["exposed"] = False
                                    pylon_state[pylon]["exposed_by"] = None
                                    pylon_state[pylon]["exposed_fresh"] = False
                        _boss_legendary_after_turn(
                            active_pylons=_active(),
                            state=state,
                            end_of_round=end_of_round,
                        )

                    state[f"{actor_id}_no_reactions"] = False
                    state[f"{actor_id}_restrained"] = False
                    state[f"{actor_id}_bonus_used"] = False
                    slowed_this_turn = bool(state[f"{actor_id}_slow_next_turn"])
                    state[f"{actor_id}_slow_next_turn"] = False

                    if (
                        positioning_mode != "none"
                        and avoid_boss_center
                        and state.get(f"{actor_id}_pos") == "center"
                        and (not state.get(f"{actor_id}_grappled", False))
                    ):
                        state[f"{actor_id}_pos"] = home_nodes.get(actor_id, "past")

                    if _is_unconscious(actor_id, state):
                        _death_save(actor_id, state=state)
                        if _is_unconscious(actor_id, state) or _is_dead(actor_id, state):
                            _end_turn()
                            continue

                    if (
                        positioning_mode != "none"
                        and state.get(f"{actor_id}_pos") == "center"
                        and state.get(f"{actor_id}_grappled", False)
                    ):
                        if _attempt_escape_grapple(pid=actor_id, state=state):
                            state[f"{actor_id}_grappled"] = False
                            state[f"{actor_id}_pos"] = home_nodes.get(actor_id, "past")
                        _end_turn()
                        continue

                    if actor_id == "druid":
                        if slowed_this_turn:
                            if _maybe_healing_word(state=state, max_hp_by_id=max_hp_by_id):
                                _end_turn()
                                continue
                        else:
                            _maybe_healing_word(state=state, max_hp_by_id=max_hp_by_id)

                    primary_pylon = _choose_focus(actor_id)
                    if primary_pylon is None:
                        break

                    exposed = bool(pylon_state[primary_pylon]["exposed"])
                    if procedure_mode == "fixed_actor":
                        procedure_candidate = str(procedure_actors.get(primary_pylon))
                    else:
                        procedure_candidate = actor_id

                    should_attempt_procedure = (
                        _is_conscious(actor_id, state)
                        and (not exposed)
                        and (actor_id == procedure_candidate)
                    )
                    if (
                        should_attempt_procedure
                        and positioning_mode != "none"
                        and primary_pylon in {"past", "present"}
                        and state.get(f"{actor_id}_pos") != primary_pylon
                    ):
                        should_attempt_procedure = False
                    if (
                        should_attempt_procedure
                        and procedure_cost_mode == "bonus_action"
                        and bool(state.get(f"{actor_id}_bonus_used", False))
                    ):
                        should_attempt_procedure = False

                    action_attacks_lost = 0
                    if should_attempt_procedure:
                        state[f"{actor_id}_proc_attempts"] += 1
                        bonus = _procedure_bonus(actor_id, primary_pylon)
                        advantage = procedure_fail_forward == "next_attempt_advantage" and bool(
                            pylon_state[primary_pylon].get("proc_advantage_next", False)
                        )
                        pylon_state[primary_pylon]["proc_advantage_next"] = False
                        if (_roll_d20(advantage=advantage) + bonus) >= proc_dc:
                            pylon_state[primary_pylon]["exposed"] = True
                            pylon_state[primary_pylon]["exposed_by"] = actor_id
                            pylon_state[primary_pylon]["exposed_fresh"] = True
                            state[f"{actor_id}_proc_successes"] += 1
                        else:
                            if procedure_fail_forward == "next_attempt_advantage":
                                pylon_state[primary_pylon]["proc_advantage_next"] = True
                        if procedure_cost_mode == "one_attack" and actor_id in {"isak", "fury"}:
                            action_attacks_lost = 1
                        elif procedure_cost_mode == "bonus_action":
                            state[f"{actor_id}_bonus_used"] = True
                            if slowed_this_turn:
                                _end_turn()
                                continue
                        else:
                            _end_turn()
                            continue

                    exposed_candidates = [
                        p
                        for p in active_pylons
                        if pylon_state[p]["exposed"] and pylon_state[p]["exposed_by"] != actor_id
                    ]
                    if exposed and pylon_state[primary_pylon]["exposed_by"] != actor_id:
                        target_pylon = primary_pylon
                    elif exposed_candidates:
                        target_pylon = min(
                            exposed_candidates,
                            key=lambda p: (int(pylon_state[p]["hp"]), rng.random()),
                        )
                    else:
                        target_pylon = primary_pylon

                    target_ac = pylon_ac + int(state.get(f"pylon_ac_bonus_{target_pylon}", 0))
                    action_attacks = (
                        max(0, 2 - action_attacks_lost) if actor_id in {"isak", "fury"} else 0
                    )
                    bonus_action_available = not bool(state.get(f"{actor_id}_bonus_used", False))
                    attack_damages: list[int] = []
                    if actor_id == "druid":
                        attack_damages.append(
                            druid_turn(bool(pylon_state[target_pylon]["exposed"]), target_ac, state)
                        )
                    elif actor_id == "isak":
                        if positioning_mode != "none" and state.get("isak_pos") != target_pylon:
                            attack_damages.extend(
                                monk_ranged_turn(
                                    "isak",
                                    bool(pylon_state[target_pylon]["exposed"]),
                                    target_ac,
                                    action_attacks=action_attacks,
                                    state=state,
                                )
                            )
                        else:
                            attack_damages.extend(
                                isak_turn(
                                    bool(pylon_state[target_pylon]["exposed"]),
                                    target_ac,
                                    action_attacks=action_attacks,
                                    bonus_action_available=bonus_action_available,
                                    state=state,
                                    slowed=slowed_this_turn,
                                )
                            )
                    else:
                        if positioning_mode != "none" and state.get("fury_pos") != target_pylon:
                            attack_damages.extend(
                                monk_ranged_turn(
                                    "fury",
                                    bool(pylon_state[target_pylon]["exposed"]),
                                    target_ac,
                                    action_attacks=action_attacks,
                                    state=state,
                                )
                            )
                        else:
                            attack_damages.extend(
                                fury_turn(
                                    bool(pylon_state[target_pylon]["exposed"]),
                                    target_ac,
                                    action_attacks=action_attacks,
                                    bonus_action_available=bonus_action_available,
                                    state=state,
                                    slowed=slowed_this_turn,
                                )
                            )

                    for attack_damage in attack_damages:
                        active_now = _active()
                        hp, trig_high, trig_low, _pulse_target, applied, temporal_available = (
                            _apply_attack_damage(
                                hp=int(pylon_state[target_pylon]["hp"]),
                                damage=attack_damage,
                                pylon_type=target_pylon,
                                trig_high=bool(pylon_state[target_pylon]["trig_high"]),
                                trig_low=bool(pylon_state[target_pylon]["trig_low"]),
                                pulse_target=actor_id,
                                pylon_damage_threshold=int(
                                    state.get(f"pylon_damage_threshold_bonus_{target_pylon}", 0)
                                ),
                                temporal_reversal_available=bool(
                                    state["boss_legendary_available"] and ("future" in active_now)
                                ),
                                state=state,
                            )
                        )
                        pylon_state[target_pylon]["hp"] = hp
                        pylon_state[target_pylon]["trig_high"] = trig_high
                        pylon_state[target_pylon]["trig_low"] = trig_low
                        if "future" in active_now:
                            state["boss_legendary_available"] = temporal_available
                        if applied:
                            state[f"{actor_id}_damage_dealt"] += applied
                        if int(pylon_state[target_pylon]["hp"]) <= 0:
                            if pylon_kill_round[target_pylon] is None:
                                pylon_kill_round[target_pylon] = rounds
                            break

                    _end_turn()

            trial_success = (
                (not _active()) and (not _party_defeated(state)) and rounds <= max_rounds
            )
            return rounds, pylon_kill_round, trial_success

        if combat_mode == "parallel":
            rounds, pylon_kill_round, trial_success = _run_parallel_trial()
        else:
            rounds, pylon_kill_round, trial_success = _run_sequential_trial()

        if trial_success and (not _party_defeated(state)) and rounds <= max_rounds:
            party_success += 1
        if not _is_conscious("isak", state):
            isak_downed += 1
        if not _is_conscious("fury", state):
            fury_downed += 1
        if not _is_conscious("druid", state):
            druid_downed += 1

        rounds_all.append(float(rounds))
        isak_ki_all.append(float(state["isak_ki_spent"]))
        fury_ki_all.append(float(state["fury_ki_spent"]))
        isak_pulse_all.append(float(state["isak_pulse_damage"]))
        fury_pulse_all.append(float(state["fury_pulse_damage"]))
        druid_pulse_all.append(float(state["druid_pulse_damage"]))
        isak_hp_all.append(float(max(state["isak_hp"], 0)))
        fury_hp_all.append(float(max(state["fury_hp"], 0)))
        druid_hp_all.append(float(max(state["druid_hp"], 0)))
        isak_hit_all.append(float(state["isak_pulse_hits"]))
        fury_hit_all.append(float(state["fury_pulse_hits"]))
        druid_hit_all.append(float(state["druid_pulse_hits"]))
        if pylon_kill_round["past"] is not None:
            past_kill_round_all.append(float(pylon_kill_round["past"]))
        if pylon_kill_round["present"] is not None:
            present_kill_round_all.append(float(pylon_kill_round["present"]))
        if pylon_kill_round["future"] is not None:
            future_kill_round_all.append(float(pylon_kill_round["future"]))
        isak_damage_dealt_all.append(int(state["isak_damage_dealt"]))
        fury_damage_dealt_all.append(int(state["fury_damage_dealt"]))
        druid_damage_dealt_all.append(int(state["druid_damage_dealt"]))
        isak_damage_taken_all.append(int(state["isak_damage_taken"]))
        fury_damage_taken_all.append(int(state["fury_damage_taken"]))
        druid_damage_taken_all.append(int(state["druid_damage_taken"]))
        healing_word_casts_all.append(int(state["druid_healing_word_casts"]))
        spell_slot_1_spent_all.append(
            int(druid["resources"]["spell_slots"]["1"]) - int(state["druid_spell_slots_1"])
        )
        wholeness_used_all.append(int(state["isak_wholeness_used"]))
        isak_proc_attempts_all.append(int(state["isak_proc_attempts"]))
        fury_proc_attempts_all.append(int(state["fury_proc_attempts"]))
        druid_proc_attempts_all.append(int(state["druid_proc_attempts"]))
        isak_proc_successes_all.append(int(state["isak_proc_successes"]))
        fury_proc_successes_all.append(int(state["fury_proc_successes"]))
        druid_proc_successes_all.append(int(state["druid_proc_successes"]))
        boss_turns_all.append(int(state["boss_turns"]))
        boss_lair_turns_all.append(int(state["boss_lair_turns"]))
        boss_isak_damage_all.append(int(state["boss_isak_damage"]))
        boss_fury_damage_all.append(int(state["boss_fury_damage"]))
        boss_druid_damage_all.append(int(state["boss_druid_damage"]))
        for action_name in action_names:
            boss_action_usage_all[action_name].append(int(state[f"boss_action_{action_name}"]))
        for lair_name in lair_names:
            boss_lair_usage_all[lair_name].append(int(state[f"boss_lair_{lair_name}"]))
        boss_legendary_usage_all["temporal_reversal"].append(
            int(state["boss_legendary_temporal_reversal"])
        )
        boss_legendary_usage_all["winch_pull"].append(int(state["boss_legendary_winch_pull"]))
        boss_legendary_usage_all["tail_tap"].append(int(state["boss_legendary_tail_tap"]))
        for pid in actor_ids:
            if _is_dead(pid, state):
                deaths_all[pid] += 1

        if emit_trial_rows:
            trial_rows.append(
                {
                    "trial_index": trial,
                    "rounds": rounds,
                    "party_success": int(
                        trial_success and (not _party_defeated(state)) and rounds <= max_rounds
                    ),
                    "isak_hp": max(state["isak_hp"], 0),
                    "fury_hp": max(state["fury_hp"], 0),
                    "druid_hp": max(state["druid_hp"], 0),
                    "isak_ki_spent": state["isak_ki_spent"],
                    "fury_ki_spent": state["fury_ki_spent"],
                    "isak_pulse_damage": state["isak_pulse_damage"],
                    "fury_pulse_damage": state["fury_pulse_damage"],
                    "druid_pulse_damage": state["druid_pulse_damage"],
                    "isak_pulse_hits": state["isak_pulse_hits"],
                    "fury_pulse_hits": state["fury_pulse_hits"],
                    "druid_pulse_hits": state["druid_pulse_hits"],
                    "initiative_order": ",".join(initiative_order),
                    "druid_healing_word_casts": state["druid_healing_word_casts"],
                    "druid_spell_slots_1_spent": int(druid["resources"]["spell_slots"]["1"])
                    - state["druid_spell_slots_1"],
                    "isak_wholeness_used": int(state["isak_wholeness_used"]),
                    "past_kill_round": pylon_kill_round["past"],
                    "present_kill_round": pylon_kill_round["present"],
                    "future_kill_round": pylon_kill_round["future"],
                    "isak_damage_dealt": state["isak_damage_dealt"],
                    "fury_damage_dealt": state["fury_damage_dealt"],
                    "druid_damage_dealt": state["druid_damage_dealt"],
                    "isak_damage_taken": state["isak_damage_taken"],
                    "fury_damage_taken": state["fury_damage_taken"],
                    "druid_damage_taken": state["druid_damage_taken"],
                    "isak_proc_attempts": state["isak_proc_attempts"],
                    "fury_proc_attempts": state["fury_proc_attempts"],
                    "druid_proc_attempts": state["druid_proc_attempts"],
                    "isak_proc_successes": state["isak_proc_successes"],
                    "fury_proc_successes": state["fury_proc_successes"],
                    "druid_proc_successes": state["druid_proc_successes"],
                    "boss_turns": state["boss_turns"],
                    "boss_lair_turns": state["boss_lair_turns"],
                    "boss_isak_damage": state["boss_isak_damage"],
                    "boss_fury_damage": state["boss_fury_damage"],
                    "boss_druid_damage": state["boss_druid_damage"],
                    "boss_action_harpoon_winch": state["boss_action_harpoon_winch"],
                    "boss_action_guilt_fog": state["boss_action_guilt_fog"],
                    "boss_action_boiler_vent": state["boss_action_boiler_vent"],
                    "boss_action_time_shear": state["boss_action_time_shear"],
                    "boss_action_slam": state["boss_action_slam"],
                    "boss_lair_undertow": state["boss_lair_undertow"],
                    "boss_lair_arc_flash": state["boss_lair_arc_flash"],
                    "boss_lair_phase_flicker": state["boss_lair_phase_flicker"],
                    "boss_legendary_temporal_reversal": state["boss_legendary_temporal_reversal"],
                    "boss_legendary_winch_pull": state["boss_legendary_winch_pull"],
                    "boss_legendary_tail_tap": state["boss_legendary_tail_tap"],
                    "isak_dead": int(state["isak_dead"]),
                    "fury_dead": int(state["fury_dead"]),
                    "druid_dead": int(state["druid_dead"]),
                }
            )

    summary_payload = {
        "run_id": run_dir.name,
        "scenario_id": scenario.config.scenario_id,
        "trials": trials,
        "breakpoint_thresholds": breakpoint_thresholds,
        "pulse_save_dc": pulse_save_dc,
        "positioning_mode": positioning_mode,
        "pylon_to_pylon_ft": pylon_to_pylon_ft,
        "boss_to_pylon_ft": boss_to_pylon_ft,
        "avoid_boss_center": avoid_boss_center,
        "spread_out_positions": spread_out_positions,
        "formation_mode": formation_mode,
        "monk_flurry_policy": monk_flurry_policy,
        "procedure_cost_mode": procedure_cost_mode,
        "procedure_fail_forward": procedure_fail_forward,
        "combat_mode": combat_mode,
        "party_success_rate": party_success / trials,
        "down_probabilities": {
            "isak": isak_downed / trials,
            "fury": fury_downed / trials,
            "druid": druid_downed / trials,
        },
        "rounds": _summary(rounds_all),
        "pylon_kill_rounds": {
            "past": _summary(past_kill_round_all) if past_kill_round_all else {},
            "present": _summary(present_kill_round_all) if present_kill_round_all else {},
            "future": _summary(future_kill_round_all) if future_kill_round_all else {},
        },
        "pylon_alive_rounds": {
            "past": _summary(past_kill_round_all) if past_kill_round_all else {},
            "present": _summary(present_kill_round_all) if present_kill_round_all else {},
            "future": _summary(future_kill_round_all) if future_kill_round_all else {},
        },
        "damage_dealt": {
            "isak": _summary_int(isak_damage_dealt_all),
            "fury": _summary_int(fury_damage_dealt_all),
            "druid": _summary_int(druid_damage_dealt_all),
        },
        "damage_taken": {
            "isak": _summary_int(isak_damage_taken_all),
            "fury": _summary_int(fury_damage_taken_all),
            "druid": _summary_int(druid_damage_taken_all),
        },
        "isak_ki_spent": _summary(isak_ki_all),
        "fury_ki_spent": _summary(fury_ki_all),
        "healing_word_casts": _summary_int(healing_word_casts_all),
        "spell_slot_1_spent": _summary_int(spell_slot_1_spent_all),
        "wholeness_used_rate": float(sum(wholeness_used_all)) / float(trials),
        "procedure_attempts": {
            "isak": _summary_int(isak_proc_attempts_all),
            "fury": _summary_int(fury_proc_attempts_all),
            "druid": _summary_int(druid_proc_attempts_all),
        },
        "procedure_successes": {
            "isak": _summary_int(isak_proc_successes_all),
            "fury": _summary_int(fury_proc_successes_all),
            "druid": _summary_int(druid_proc_successes_all),
        },
        "death_probabilities": {pid: deaths_all[pid] / trials for pid in actor_ids},
        "isak_pulse_damage": _summary(isak_pulse_all),
        "fury_pulse_damage": _summary(fury_pulse_all),
        "druid_pulse_damage": _summary(druid_pulse_all),
        "isak_pulse_hits": _summary(isak_hit_all),
        "fury_pulse_hits": _summary(fury_hit_all),
        "druid_pulse_hits": _summary(druid_hit_all),
        "boss_turns": _summary_int(boss_turns_all),
        "boss_lair_turns": _summary_int(boss_lair_turns_all),
        "boss_damage_dealt": {
            "isak": _summary_int(boss_isak_damage_all),
            "fury": _summary_int(boss_fury_damage_all),
            "druid": _summary_int(boss_druid_damage_all),
        },
        "boss_action_usage": {
            name: _summary_int(values) for name, values in boss_action_usage_all.items()
        },
        "boss_lair_usage": {
            name: _summary_int(values) for name, values in boss_lair_usage_all.items()
        },
        "boss_legendary_usage": {
            name: _summary_int(values) for name, values in boss_legendary_usage_all.items()
        },
        "remaining_hp": {
            "isak": _summary(isak_hp_all),
            "fury": _summary(fury_hp_all),
            "druid": _summary(druid_hp_all),
        },
    }

    plot_paths = _plot_outputs(run_dir, trial_rows) if emit_plots else {}
    report_markdown = (
        _build_report(
            summary_payload=summary_payload,
            scenario_id=scenario.config.scenario_id,
            trials=trials,
            seed=seed,
            assumptions={
                "procedure_actors": procedure_actors,
                "procedure_mode": procedure_mode,
                "initiative_mode": initiative_mode,
                "pulse_targeting": pulse_targeting,
                "prism_pulse_magical": prism_pulse_magical,
                "breakpoints_per_attack": breakpoints_per_attack,
                "breakpoint_thresholds": breakpoint_thresholds,
                "heal_threshold_fraction": healing_word_threshold,
                "pylon_hp": pylon_hp,
                "pylon_ac": pylon_ac,
                "procedure_dc": proc_dc,
                "pulse_save_dc": pulse_save_dc,
                "unexposed_damage_multiplier": unexposed_damage_multiplier,
                "positioning_mode": positioning_mode,
                "pylon_to_pylon_ft": pylon_to_pylon_ft,
                "avoid_boss_center": avoid_boss_center,
                "spread_out_positions": spread_out_positions,
                "formation_mode": formation_mode,
                "monk_flurry_policy": monk_flurry_policy,
                "procedure_cost_mode": procedure_cost_mode,
                "procedure_fail_forward": procedure_fail_forward,
                "combat_mode": combat_mode,
                "boss_enabled": boss_enabled,
                "boss_action_priority": boss_action_priority,
                "boss_lair_priority": boss_lair_priority,
                "boss_target_mode": boss_target_mode,
                "boss_lair_mode": boss_lair_mode,
                "boss_damage_scalar": boss_damage_scalar,
                "boss_save_dc_offset": boss_save_dc_offset,
                "boss_attack_bonus_offset": boss_attack_bonus_offset,
                "phase_flicker_ac_bonus": phase_flicker_ac_bonus,
                "phase_flicker_threshold_bonus": phase_flicker_threshold_bonus,
                "phase_flicker_weak_threshold": phase_flicker_weak_threshold,
                "temporal_reversal_reduction": temporal_reversal_reduction,
                "temporal_reversal_recharge_min": temporal_reversal_recharge_min,
                "temporal_reversal_chance": temporal_reversal_chance,
            },
            plot_paths=plot_paths,
        )
        if emit_report
        else ""
    )

    return {
        "summary": summary_payload,
        "trial_rows": trial_rows,
        "report_markdown": report_markdown,
        "plot_paths": plot_paths,
    }
