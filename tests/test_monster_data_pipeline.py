from __future__ import annotations

import json
import random
from pathlib import Path

from dnd_sim.engine import (
    _action_available,
    _build_actor_from_enemy,
    _execute_action,
    _roll_recharge_for_actor,
)
from dnd_sim.mechanics_schema import (
    EXECUTABLE_EFFECT_TYPES,
    build_mechanics_coverage_report,
    validate_rule_mechanics_payload,
)
from dnd_sim.io import EnemyConfig
from dnd_sim.models import ActorRuntimeState
from dnd_sim.monster_backfill import backfill_monster_payload
from dnd_sim.parse_monsters import parse_monsters


def _fixture_text(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / "monster_parser" / name
    return path.read_text(encoding="utf-8")


def test_parse_monsters_extracts_full_action_reaction_legendary_and_lair_kits() -> None:
    monsters = parse_monsters(_fixture_text("chronal_hydra_srd.txt"))

    assert len(monsters) == 1
    hydra = monsters[0]

    # Legacy compatibility keys remain available.
    assert hydra["name"] == "Chronal Hydra"
    assert hydra["ac"] == 18
    assert hydra["hp"] == 250
    assert hydra["cr"] == "15"

    assert hydra["identity"]["enemy_id"] == "chronal_hydra"
    assert hydra["stat_block"]["max_hp"] == 250
    assert hydra["resources"]["legendary_actions"] == 3

    action_names = [row["name"] for row in hydra["actions"]]
    assert action_names == ["multiattack", "temporal_bite", "time_pulse"]

    reaction_names = [row["name"] for row in hydra["reactions"]]
    assert reaction_names == ["counter_lash"]
    assert hydra["reactions"][0]["action_cost"] == "reaction"

    legendary_names = [row["name"] for row in hydra["legendary_actions"]]
    assert legendary_names == ["detect", "snap", "rift_burst"]
    assert "legendary_cost:2" in hydra["legendary_actions"][1]["tags"]
    assert "legendary_cost:3" in hydra["legendary_actions"][2]["tags"]

    lair_names = [row["name"] for row in hydra["lair_actions"]]
    assert lair_names == ["gravitic_surge", "temporal_fog"]
    assert hydra["lair_actions"][0]["action_cost"] == "lair"


def test_validate_rule_mechanics_payload_flags_invalid_mechanics_shapes() -> None:
    issues = validate_rule_mechanics_payload(
        kind="trait",
        payload={
            "name": "Broken Trait",
            "type": "feat",
            "mechanics": [{"damage": "1d6"}, "not even a mapping"],
        },
    )

    assert len(issues) == 2
    assert "effect_type" in issues[0]
    assert "must be an object" in issues[1]


def test_validate_rule_mechanics_payload_accepts_known_effect_types() -> None:
    issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Pulse Bolt",
            "type": "spell",
            "mechanics": [{"effect_type": "damage", "damage": "2d8", "damage_type": "force"}],
        },
    )
    assert issues == []


def test_validate_rule_mechanics_payload_accepts_apply_condition_runtime_fields() -> None:
    issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Stasis Net",
            "type": "spell",
            "mechanics": [
                {
                    "effect_type": "apply_condition",
                    "condition": "restrained",
                    "duration_timing": "turn_end",
                    "stack_policy": "refresh",
                    "save_ability": "dex",
                }
            ],
        },
    )
    assert issues == []


def test_validate_rule_mechanics_payload_rejects_invalid_apply_condition_runtime_fields() -> None:
    issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Broken Stasis",
            "type": "spell",
            "mechanics": [
                {
                    "effect_type": "apply_condition",
                    "condition": "restrained",
                    "duration_timing": "start_of_round",
                    "stack_policy": "merge",
                    "save_ability": "constitution",
                }
            ],
        },
    )
    assert (
        "mechanics[0].duration_timing 'start_of_round' is unsupported for apply_condition" in issues
    )
    assert "mechanics[0].stack_policy 'merge' is unsupported for apply_condition" in issues
    assert "mechanics[0].save_ability 'constitution' is unsupported for apply_condition" in issues


def test_build_mechanics_coverage_report_counts_executable_and_unsupported(tmp_path: Path) -> None:
    traits_dir = tmp_path / "traits"
    spells_dir = tmp_path / "spells"
    monsters_dir = tmp_path / "monsters"
    traits_dir.mkdir()
    spells_dir.mkdir()
    monsters_dir.mkdir()

    (traits_dir / "trait.json").write_text(
        json.dumps(
            {
                "name": "Reactive Mind",
                "type": "feat",
                "mechanics": [
                    {"effect_type": "sense", "sense": "blindsight", "range_ft": 10},
                    {"effect_type": "quantum_shift"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (spells_dir / "spell.json").write_text(
        json.dumps(
            {
                "name": "Pulse Bolt",
                "type": "spell",
                "mechanics": [{"effect_type": "damage", "damage": "2d8", "damage_type": "force"}],
            }
        ),
        encoding="utf-8",
    )
    (monsters_dir / "monster.json").write_text(
        json.dumps(
            {
                "identity": {"enemy_id": "void_hound", "name": "Void Hound", "team": "enemy"},
                "stat_block": {"max_hp": 22, "ac": 13},
                "actions": [
                    {
                        "name": "warp_bite",
                        "action_type": "attack",
                        "effects": [{"effect_type": "apply_condition", "condition": "frightened"}],
                    },
                    {
                        "name": "timeline_bark",
                        "action_type": "utility",
                        "mechanics": [{"effect_type": "timeline_snap"}],
                    },
                ],
                "reactions": [],
                "legendary_actions": [],
                "lair_actions": [],
            }
        ),
        encoding="utf-8",
    )

    report = build_mechanics_coverage_report(
        traits_dir=traits_dir,
        spells_dir=spells_dir,
        monsters_dir=monsters_dir,
    )

    assert report["totals"]["ingested"] == 5
    assert report["totals"]["executable"] == 3
    assert report["totals"]["unsupported"] == 2
    assert "quantum_shift" in report["unsupported_effect_types"]
    assert "timeline_snap" in report["unsupported_effect_types"]
    assert "damage" in EXECUTABLE_EFFECT_TYPES


def test_backfill_monster_payload_upgrades_legacy_shape_to_enemy_schema() -> None:
    legacy = {
        "name": "Legacy Beast",
        "meta": "Large monstrosity, unaligned",
        "ac": 13,
        "hp": 45,
        "hp_formula": "6d10 + 12",
        "ability_scores": {"str": 16, "dex": 10, "con": 14, "int": 3, "wis": 12, "cha": 6},
        "cr": "3",
        "saving_throws_text": "Con +4, Wis +3",
    }

    migrated = backfill_monster_payload(legacy)

    assert migrated["identity"]["enemy_id"] == "legacy_beast"
    assert migrated["identity"]["name"] == "Legacy Beast"
    assert migrated["stat_block"]["max_hp"] == 45
    assert migrated["stat_block"]["ac"] == 13
    assert migrated["stat_block"]["save_mods"]["con"] == 4
    assert migrated["stat_block"]["save_mods"]["wis"] == 3
    assert migrated["actions"] == []
    assert migrated["reactions"] == []
    assert migrated["legendary_actions"] == []
    assert migrated["lair_actions"] == []
    assert migrated["resources"] == {}


def test_backfill_monster_payload_preserves_existing_enemy_schema() -> None:
    modern = {
        "identity": {"enemy_id": "modern_one", "name": "Modern One", "team": "enemy"},
        "stat_block": {"max_hp": 10, "ac": 12, "save_mods": {"dex": 2}},
        "actions": [{"name": "slam", "action_type": "attack"}],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
    }

    migrated = backfill_monster_payload(modern)
    assert migrated["identity"]["enemy_id"] == "modern_one"
    assert migrated["actions"][0]["name"] == "slam"


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


class _FixedSixRng:
    def randint(self, _a: int, _b: int) -> int:
        return 6


def test_monster_pipeline_extracts_innate_spells_and_runtime_uses_recharge_and_limits() -> None:
    raw_text = """
Monsters (A)
Spell Tyrant
Large fiend, lawful evil
Armor Class 16 (natural armor)
Hit Points 120 (16d10 + 32)
Speed 30 ft.
STR DEX CON INT WIS CHA
18 (+4) 12 (+1) 15 (+2) 16 (+3) 14 (+2) 18 (+4)
Challenge 12 (8,400 XP)
Legendary Resistance (3/Day). If the tyrant fails a saving throw, it can choose to succeed instead.
Innate Spellcasting. The tyrant's innate spellcasting ability is Charisma (spell save DC 16, +8 to hit with spell attacks). It can innately cast the following spells: At will: magic missile 1/day each: fireball
Actions
Arc Bolt (Recharge 6). Ranged Spell Attack: +8 to hit, range 120 ft., one target. Hit: 14 (4d6) force damage.
Appendix PH-A:
""".strip()

    monsters = parse_monsters(raw_text)
    assert len(monsters) == 1
    monster_payload = monsters[0]
    assert monster_payload["resources"]["legendary_resistance"] == 3
    assert monster_payload["innate_spellcasting"][0]["spell"] == "Magic Missile"
    assert monster_payload["innate_spellcasting"][1]["spell"] == "Fireball"
    assert monster_payload["innate_spellcasting"][1]["max_uses"] == 1

    enemy = EnemyConfig.model_validate(monster_payload)
    actor = _build_actor_from_enemy(enemy)

    arc_bolt = next(action for action in actor.actions if action.name == "arc_bolt")
    fireball = next(action for action in actor.actions if action.name == "Fireball")
    target = _base_actor(actor_id="hero", team="party")

    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(11),
        actor=actor,
        action=fireball,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    actor.per_action_uses[fireball.name] = actor.per_action_uses.get(fireball.name, 0) + 1
    assert _action_available(actor, fireball) is False

    _execute_action(
        rng=random.Random(12),
        actor=actor,
        action=arc_bolt,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    actor.recharge_ready[arc_bolt.name] = False
    assert _action_available(actor, arc_bolt) is False

    _roll_recharge_for_actor(_FixedSixRng(), actor)
    assert actor.recharge_ready["arc_bolt"] is True
