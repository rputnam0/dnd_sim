from __future__ import annotations

from dnd_sim.engine import _action_available, _build_actor_from_character, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=2,
        dex_mod=3,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 3, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _rogue_character(*, level: int, traits: list[str] | None = None) -> dict[str, object]:
    return {
        "character_id": f"rogue_{level}",
        "name": f"Rogue {level}",
        "class_level": f"Rogue {level}",
        "max_hp": 34,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 18, "con": 14, "int": 12, "wis": 10, "cha": 12},
        "save_mods": {"str": 0, "dex": 6, "con": 2, "int": 1, "wis": 0, "cha": 1},
        "skill_mods": {},
        "attacks": [
            {
                "name": "Shortbow",
                "to_hit": 8,
                "damage": "1d6+4",
                "damage_type": "piercing",
                "range_ft": 80,
                "range_normal_ft": 80,
                "range_long_ft": 320,
                "weapon_properties": ["ammunition", "ranged"],
            }
        ],
        "resources": {},
        "traits": list(traits or []),
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def test_build_actor_infers_rogue_package_traits_and_cunning_actions() -> None:
    actor = _build_actor_from_character(_rogue_character(level=7), traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert {"sneak attack", "cunning action", "uncanny dodge", "evasion"}.issubset(actor.traits)
    assert by_name["cunning_dash"].action_cost == "bonus"
    assert by_name["cunning_disengage"].action_cost == "bonus"
    assert by_name["cunning_hide"].action_cost == "bonus"


def test_cunning_action_bonus_option_is_illegal_after_bonus_is_spent() -> None:
    actor = _build_actor_from_character(_rogue_character(level=2), traits_db={})
    cunning_dash = next(action for action in actor.actions if action.name == "cunning_dash")

    assert _action_available(actor, cunning_dash, turn_token="1:rogue") is True
    actor.bonus_available = False
    assert _action_available(actor, cunning_dash, turn_token="1:rogue") is False


def test_sneak_attack_applies_only_once_when_two_attacks_share_turn_token() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    # Keep ally adjacent to the target so Sneak Attack remains legal without
    # forcing ranged-in-melee disadvantage on the rogue.
    ally.position = (25.0, 0.0, 0.0)

    action = ActionDefinition(
        name="shortbow",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="piercing",
        range_ft=80,
        attack_count=2,
    )

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 6, 5, 15, 1]),
        actor=rogue,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:rogue",
    )

    # Hit 1: 1d1 + sneak(2d6=11) = 12, Hit 2: 1d1 = 1 => total 13
    assert damage_dealt[rogue.actor_id] == 13
    assert rogue.sneak_attack_used_this_turn is True
