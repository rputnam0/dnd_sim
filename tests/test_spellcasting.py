from __future__ import annotations

from dnd_sim.engine import _action_available, _execute_action, _spend_action_resource_cost
from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    SpellCastRequest,
    SpellDefinition,
    SpellScaling,
)


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


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


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_spell_slot_of_level_or_higher_is_legal() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_3": 1}
    resources_spent = {caster.actor_id: {}}

    spell = ActionDefinition(
        name="shield_of_faith",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )
    spell_cast_request = SpellCastRequest()

    assert _action_available(caster, spell) is True
    assert (
        _spend_action_resource_cost(
            caster,
            spell,
            resources_spent,
            spell_cast_request=spell_cast_request,
        )
        is True
    )
    assert spell_cast_request.slot_level == 3
    assert caster.resources["spell_slot_3"] == 0
    assert resources_spent[caster.actor_id]["spell_slot_3"] == 1


def test_upcast_scaling_uses_actual_spent_slot() -> None:
    rng = _FixedRng([14, 2, 3, 4])
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.ac = 10
    caster.resources = {"spell_slot_3": 1}

    spell = ActionDefinition(
        name="chromatic_orb",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=6,
        damage="1d4",
        damage_type="acid",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        spell=SpellDefinition(
            name="chromatic_orb",
            level=1,
            scaling=SpellScaling(upcast_dice_per_level="1d4"),
        ),
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    spell_cast_request = SpellCastRequest()

    assert (
        _spend_action_resource_cost(
            caster,
            spell,
            resources_spent,
            spell_cast_request=spell_cast_request,
        )
        is True
    )
    assert spell_cast_request.slot_level == 3
    assert resources_spent[caster.actor_id] == {"spell_slot_3": 1}

    _execute_action(
        rng=rng,
        actor=caster,
        action=spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        spell_cast_request=spell_cast_request,
    )

    assert target.hp == target.max_hp - 9


def test_lower_slot_only_cannot_cast_higher_level_spell() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_1": 1}
    resources_spent = {caster.actor_id: {}}

    spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        resource_cost={"spell_slot_2": 1},
        tags=["spell"],
    )

    assert _action_available(caster, spell) is False
    assert _spend_action_resource_cost(caster, spell, resources_spent) is False
    assert caster.resources["spell_slot_1"] == 1
    assert resources_spent[caster.actor_id] == {}
