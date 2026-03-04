from __future__ import annotations

import random
from pathlib import Path

from dnd_sim.engine import _apply_effect, _build_actor_from_character, _execute_action
from dnd_sim.io import load_traits_db
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import can_see


class _CountingRng(random.Random):
    def __init__(self, rolls: list[int]):
        super().__init__(0)
        self._rolls = list(rolls)
        self.calls: int = 0

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        assert a == 1 and b == 20
        self.calls += 1
        if not self._rolls:
            return 1
        return self._rolls.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
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


def test_spell_extraction_builds_combat_actions_for_squanch() -> None:
    # The character sheet includes prepared spells only in raw_fields; ensure we
    # extract at least a few with actionable payload.
    import json
    from pathlib import Path

    character = json.loads(
        Path("river_line/db/characters/squanch_161607569.json").read_text(encoding="utf-8")
    )
    actor = _build_actor_from_character(character, traits_db={})

    spell_actions = [a for a in actor.actions if "spell" in a.tags]
    assert spell_actions, "expected spell actions extracted from raw_fields"
    names = {a.name for a in spell_actions}
    # These are present in the sheet and in the local spell DB.
    assert "Moonbeam" in names
    assert "Call Lightning" in names
    # At least one leveled spell should cost a slot.
    assert any(a.resource_cost for a in spell_actions)


def test_build_actor_imports_unprepared_known_caster_spells(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 1})
    character = {
        "character_id": "bard_1",
        "name": "Bard One",
        "class_levels": {"bard": 5},
        "max_hp": 24,
        "ac": 14,
        "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 10, "wis": 10, "cha": 18},
        "save_mods": {"str": -1, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 4},
        "skill_mods": {},
        "attacks": [],
        "resources": {"spell_slots": {"spell_slot_1": 4}},
        "traits": [],
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Dissonant Whispers"},
            {"field": "spellPrepared1", "value": ""},
            {"field": "spellName2", "value": "Healing Word"},
            {"field": "spellPrepared2", "value": ""},
        ],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actor = _build_actor_from_character(character, traits_db={})
    spell_actions = [action for action in actor.actions if "spell" in action.tags]
    assert {action.name for action in spell_actions} == {"Dissonant Whispers", "Healing Word"}


def test_gnomish_cunning_grants_advantage_on_spell_saves() -> None:
    rng = _CountingRng([2, 19])
    caster = _base_actor(actor_id="caster", team="enemy")
    target = _base_actor(actor_id="gnome", team="party")
    target.traits = {"gnomish cunning": {}}

    action = ActionDefinition(
        name="spell_save",
        action_type="save",
        save_dc=20,
        save_ability="wis",
        damage=None,
        action_cost="action",
        tags=["spell"],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert rng.calls == 2


def test_fey_ancestry_grants_advantage_vs_charmed_condition_saves() -> None:
    rng = _CountingRng([1, 20])
    caster = _base_actor(actor_id="caster", team="enemy")
    target = _base_actor(actor_id="elf", team="party")
    target.traits = {"fey ancestry": {}}

    _apply_effect(
        action=ActionDefinition(name="charm", action_type="utility", tags=["spell"]),
        effect={
            "effect_type": "apply_condition",
            "condition": "charmed",
            "save_dc": 15,
            "save_ability": "wis",
            "target": "target",
        },
        rng=rng,
        actor=caster,
        target=target,
        damage_dealt={caster.actor_id: 0, target.actor_id: 0},
        damage_taken={caster.actor_id: 0, target.actor_id: 0},
        threat_scores={caster.actor_id: 0, target.actor_id: 0},
        resources_spent={caster.actor_id: {}, target.actor_id: {}},
        actors={caster.actor_id: caster, target.actor_id: target},
        active_hazards=[],
    )
    assert rng.calls == 2


def test_blind_fighting_allows_seeing_invisible_within_10ft() -> None:
    assert (
        can_see(
            observer_pos=(0.0, 0.0, 0.0),
            target_pos=(5.0, 0.0, 0.0),
            observer_traits={"blind fighting": {}},
            target_conditions={"invisible"},
            active_hazards=[],
            light_level="darkness",
        )
        is True
    )


def test_trait_hydration_resolves_variant_names_from_sheet_traits() -> None:
    traits_db = load_traits_db(Path("db/rules/2014/traits"))
    character = {
        "character_id": "c1",
        "name": "C1",
        "class_levels": {"wizard": 8},
        "max_hp": 20,
        "ac": 12,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 10, "con": 10, "int": 16, "wis": 12, "cha": 10},
        "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 3, "wis": 1, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "staff", "to_hit": 2, "damage": "1d6", "damage_type": "bludgeoning"}],
        "resources": {},
        "traits": ["8: Ability Score Improvement", "Magic Initiate (Wizard)"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actor = _build_actor_from_character(character, traits_db=traits_db)
    assert "ability score improvement" in actor.traits
    assert "magic initiate" in actor.traits
    assert actor.traits["magic initiate"].get("mechanics")


def test_trait_hydration_reads_feature_option_lines() -> None:
    traits_db = load_traits_db(Path("db/rules/2014/traits"))
    character = {
        "character_id": "c2",
        "name": "C2",
        "class_levels": {"fighter": 8},
        "max_hp": 20,
        "ac": 12,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "staff", "to_hit": 2, "damage": "1d6", "damage_type": "bludgeoning"}],
        "resources": {},
        "traits": ["Fighting Initiate"],
        "raw_fields": [
            {
                "field": "FeaturesTraits1",
                "value": (
                    "=== FEATS ===\n\n"
                    "* Fighting Initiate • TCoE 80\n"
                    "   | Blind Fighting • TCoE 41\n"
                ),
            }
        ],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actor = _build_actor_from_character(character, traits_db=traits_db)
    assert "blind fighting" in actor.traits
    # Applied from trait mechanics(effect_type=sense)
    assert actor.traits.get("blindsight", {}).get("range_ft") == 10.0
