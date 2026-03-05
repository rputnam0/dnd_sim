from __future__ import annotations

from dnd_sim import effects_runtime
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=14,
        initiative_mod=2,
        str_mod=1,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 1, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[ActionDefinition(name="basic", action_type="attack")],
        position=(0.0, 0.0, 0.0),
    )


def test_break_concentration_cleans_linked_effects_hazards_and_summons() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    summon = _actor(actor_id="summon", team="party")
    summon.traits["summoned"] = {"source_id": caster.actor_id, "concentration_linked": True}
    summon.conditions.add("summoned")

    created_ids = effects_runtime.apply_condition(
        target,
        "restrained",
        duration_rounds=10,
        source_actor_id=caster.actor_id,
        target_actor_id=target.actor_id,
        concentration_linked=True,
    )

    caster.concentrating = True
    caster.concentrated_targets.add(target.actor_id)
    caster.concentration_conditions.add("restrained")
    caster.concentration_effect_instance_ids.update(created_ids)
    caster.concentrated_spell = "web"
    caster.concentrated_spell_level = 2

    active_hazards = [
        {
            "hazard_id": "web-zone",
            "source_id": caster.actor_id,
            "concentration_owner_id": caster.actor_id,
            "concentration_linked": True,
            "zone_type": "difficult_terrain",
        }
    ]
    actors = {caster.actor_id: caster, target.actor_id: target, summon.actor_id: summon}

    effects_runtime.break_concentration(caster, actors, active_hazards)

    assert caster.concentrating is False
    assert not caster.concentrated_targets
    assert not caster.concentration_conditions
    assert not caster.concentration_effect_instance_ids
    assert caster.concentrated_spell is None
    assert caster.concentrated_spell_level is None

    assert "restrained" not in target.conditions
    assert target.effect_instances == []
    assert summon.actor_id not in actors
    assert active_hazards == []
