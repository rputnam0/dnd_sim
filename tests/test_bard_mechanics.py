from __future__ import annotations

from dnd_sim.engine import _execute_action, _extract_spells_from_raw_fields
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


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


def test_bardic_inspiration_spends_when_attack_would_otherwise_miss() -> None:
    rng = _SequenceRng([8, 3, 4])  # attack d20, inspiration d6, weapon damage d8
    attacker = _base_actor(actor_id="attacker", team="party")
    attacker.resources = {"bardic_inspiration_die": 6}
    target = _base_actor(actor_id="target", team="enemy")
    target.ac = 15

    action = ActionDefinition(
        name="rapier",
        action_type="attack",
        to_hit=5,
        damage="1d8",
        damage_type="piercing",
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 26
    assert attacker.resources["bardic_inspiration_die"] == 0
    assert resources_spent[attacker.actor_id]["bardic_inspiration_die"] == 1


def test_cutting_words_reaction_can_turn_hit_into_miss() -> None:
    rng = _SequenceRng([10, 4])  # attack d20, cutting words die
    attacker = _base_actor(actor_id="attacker", team="enemy")
    attacker.position = (20.0, 0.0, 0.0)

    target = _base_actor(actor_id="target", team="party")
    target.ac = 15

    bard = _base_actor(actor_id="bard", team="party")
    bard.position = (0.0, 0.0, 0.0)
    bard.traits = {"cutting words": {}}
    bard.resources = {"bardic_inspiration": 1}

    action = ActionDefinition(
        name="claw",
        action_type="attack",
        to_hit=8,
        damage="1d8+2",
        damage_type="slashing",
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target, bard.actor_id: bard}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}, bard.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 30
    assert bard.resources["bardic_inspiration"] == 0
    assert bard.reaction_available is False
    assert resources_spent[bard.actor_id]["bardic_inspiration"] == 1


def test_extract_spells_includes_magical_secrets_even_if_unprepared(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 3})
    character = {
        "class_levels": {"cleric": 5},
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 3rd LEVEL ==="},
            {"field": "spellName1", "value": "Fireball"},
            {"field": "spellPrepared1", "value": ""},
            {"field": "spellSource1", "value": "Magical Secrets"},
            {"field": "spellName2", "value": "Stinking Cloud"},
            {"field": "spellPrepared2", "value": ""},
            {"field": "spellSource2", "value": "Bard"},
        ],
        "ability_scores": {},
    }

    spells = _extract_spells_from_raw_fields(character)
    names = {row["name"] for row in spells}
    assert "Fireball" in names
    assert "Stinking Cloud" not in names
