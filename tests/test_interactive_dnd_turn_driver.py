from __future__ import annotations

import copy
import math
import random

import pytest
from pydantic import ValidationError

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.interactive import (
    EngineSession,
    EngineSessionProjectionDriver,
    EngineSessionError,
    EngineVersionPins,
    SessionCommand,
)
from dnd_sim.interactive.dnd_contracts import (
    DECLARATION_COMMAND_KIND,
    TurnDeclarationPayload,
)
from dnd_sim.interactive.dnd_turn_driver import (
    PREPARE_TURN_COMMAND_KIND,
    DndCombatTurnDriver,
    DndCombatTurnState,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.turn_kernel import CombatTurnContext, CombatTurnPrompt

VERSION_PINS = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="5e_2014_combat_foundation@1.0.0",
    content_version="solo-table-fixture@1",
)


def _actor(
    actor_id: str,
    *,
    team: str,
    actions: list[ActionDefinition] | None = None,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
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
        actions=list(actions or []),
        position=position,
    )


def _turn_state(*, enemy_position: tuple[float, float, float] = (5.0, 0.0, 0.0)):
    strike = ActionDefinition(
        name="strike",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=20,
        damage="4",
        damage_type="slashing",
        reach_ft=5,
    )
    hero = _actor("hero", team="party", actions=[strike])
    enemy = _actor("enemy", team="enemy", position=enemy_position)
    actors = {actor.actor_id: actor for actor in (hero, enemy)}
    context = CombatTurnContext(
        actors=actors,
        initiative_order=["hero", "enemy"],
        round_number=1,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=[],
        rule_trace=[],
        obstacles=[],
        light_level="bright",
        burst_round_threshold=3,
        strategy_overrides={},
        timing_engine=engine_runtime._create_combat_timing_engine(),
    )
    return DndCombatTurnState(context=context, actor_id="hero")


def _healing_turn_state() -> DndCombatTurnState:
    healing_word = ActionDefinition(
        name="healing_word",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        effects=[{"effect_type": "heal", "amount": "1d4+3", "target": "source"}],
    )
    hero = _actor("hero", team="party", actions=[healing_word])
    hero.hp = 28
    enemy = _actor("enemy", team="enemy", position=(5.0, 0.0, 0.0))
    actors = {actor.actor_id: actor for actor in (hero, enemy)}
    context = CombatTurnContext(
        actors=actors,
        initiative_order=["hero", "enemy"],
        round_number=1,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=[],
        rule_trace=[],
        obstacles=[],
        light_level="bright",
        burst_round_threshold=3,
        strategy_overrides={},
        timing_engine=engine_runtime._create_combat_timing_engine(),
    )
    return DndCombatTurnState(context=context, actor_id="hero")


def _save_turn_state() -> DndCombatTurnState:
    frost_burst = ActionDefinition(
        name="frost_burst",
        action_type="save",
        action_cost="action",
        target_mode="single_enemy",
        save_dc=12,
        save_ability="dex",
        damage="4",
        damage_type="cold",
        half_on_save=True,
    )
    hero = _actor("hero", team="party", actions=[frost_burst])
    enemy = _actor("enemy", team="enemy", position=(5.0, 0.0, 0.0))
    actors = {actor.actor_id: actor for actor in (hero, enemy)}
    context = CombatTurnContext(
        actors=actors,
        initiative_order=["hero", "enemy"],
        round_number=1,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=[],
        rule_trace=[],
        obstacles=[],
        light_level="bright",
        burst_round_threshold=3,
        strategy_overrides={},
        timing_engine=engine_runtime._create_combat_timing_engine(),
    )
    return DndCombatTurnState(context=context, actor_id="hero")


def _declaration(*, invalid_bonus: bool = False, move: bool = False) -> TurnDeclaration:
    return TurnDeclaration(
        movement_path=([(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)] if move else []),
        action=DeclaredAction(
            action_name="strike",
            targets=[TargetRef(actor_id="enemy")],
        ),
        bonus_action=(
            DeclaredAction(
                action_name="missing_bonus",
                targets=[TargetRef(actor_id="enemy")],
            )
            if invalid_bonus
            else None
        ),
    )


def _command(
    *,
    session_id: str,
    command_id: str,
    mode: str,
    declaration: TurnDeclaration,
    expected_revision: int,
) -> SessionCommand:
    return SessionCommand(
        command_id=command_id,
        session_id=session_id,
        actor_id="hero",
        expected_revision=expected_revision,
        mode=mode,
        kind=DECLARATION_COMMAND_KIND,
        version_pins=VERSION_PINS,
        payload=TurnDeclarationPayload.from_domain(declaration).model_dump(mode="json"),
    )


def _prepare_command(*, session_id: str) -> SessionCommand:
    return SessionCommand(
        command_id="prepare-1",
        session_id=session_id,
        actor_id="hero",
        expected_revision=0,
        mode="admin",
        kind=PREPARE_TURN_COMMAND_KIND,
        version_pins=VERSION_PINS,
        payload={},
    )


def test_real_dnd_driver_preview_matches_commit_without_mutating_session() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-1", _turn_state(), driver, seed=13)
    declaration = _declaration()

    prepared = session.execute(_prepare_command(session_id="table-1"))

    assert prepared.revision == 1
    assert prepared.events[0].kind == "dnd.turn.prepared"
    assert session.state["phase"] == "awaiting_declaration"
    assert session.state["actors"]["hero"]["movement_remaining"] == 30.0

    preview = session.execute(
        _command(
            session_id="table-1",
            command_id="turn-1-preview",
            mode="preview",
            declaration=declaration,
            expected_revision=1,
        )
    )

    assert preview.projection["phase"] == "complete"
    assert preview.projection["actors"]["enemy"]["hp"] == 26
    assert session.revision == 1
    assert session.state["phase"] == "awaiting_declaration"
    assert session.state["actors"]["enemy"]["hp"] == 30

    receipt = session.execute(
        _command(
            session_id="table-1",
            command_id="turn-1",
            mode="commit",
            declaration=declaration,
            expected_revision=1,
        )
    )

    assert receipt.revision == 2
    assert receipt.events[0].kind == "dnd.turn.resolved"
    assert receipt.events[0].payload["status"] == "resolved"
    assert session.state["phase"] == "complete"
    assert session.state["actors"]["enemy"]["hp"] == 26
    assert session.projection["choices"] is None


def test_real_dnd_driver_emits_finalized_preview_commit_roll_records_without_rerolling() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-rolls", _turn_state(), driver, seed=13)
    declaration = _declaration()
    session.execute(_prepare_command(session_id="table-rolls"))

    preview = session.execute(
        _command(
            session_id="table-rolls",
            command_id="roll-preview",
            mode="preview",
            declaration=declaration,
            expected_revision=1,
        )
    )
    preview_rolls = [
        event.payload["record"] for event in preview.events if event.kind == "dnd.roll.recorded.v1"
    ]

    committed = session.execute(
        _command(
            session_id="table-rolls",
            command_id="roll-commit",
            mode="commit",
            declaration=declaration,
            expected_revision=1,
        )
    )
    committed_rolls = [
        event.payload["record"]
        for event in committed.events
        if event.kind == "dnd.roll.recorded.v1"
    ]

    assert committed_rolls == preview_rolls
    assert [record["sequence"] for record in committed_rolls] == [1, 2]
    assert [record["fact"]["kind"] for record in committed_rolls] == ["d20", "damage"]
    assert committed_rolls[0]["fact"]["outcome"] == "hit"
    assert committed_rolls[1]["fact"]["raw_damage"] == 4
    assert committed_rolls[1]["fact"]["applied_damage"] == 4
    assert session.state["actors"]["enemy"]["hp"] == 26


def test_real_dnd_driver_finalizes_lucky_replacement_in_one_attack_record() -> None:
    state = _turn_state()
    hero = state.context.actors["hero"]
    hero.actions[0].to_hit = 0
    hero.traits["lucky"] = {}
    hero.resources["luck_points"] = 1
    hero.max_resources["luck_points"] = 1
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-lucky-roll", state, driver, seed=1)
    session.execute(_prepare_command(session_id="table-lucky-roll"))

    preview = session.execute(
        _command(
            session_id="table-lucky-roll",
            command_id="lucky-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id="table-lucky-roll",
            command_id="lucky-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    attack = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    preview_attack = next(
        event.payload["record"]["fact"]
        for event in preview.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )

    assert attack == preview_attack
    assert [face["value"] for face in attack["roll"]["faces"]] == [5, 19]
    assert attack["roll"]["faces"][0]["status"] == "replaced"
    assert attack["roll"]["faces"][0]["replacement_generation_index"] == 2
    assert attack["roll"]["faces"][1]["status"] == "kept"
    assert attack["roll"]["total"] == 19
    assert attack["outcome"] == "hit"
    assert session.state["actors"]["enemy"]["hp"] == 26


@pytest.mark.parametrize(
    ("seed", "expected_faces"),
    [(7, [11, 5]), (26, [7, 7])],
)
def test_real_dnd_driver_keeps_worse_and_tied_lucky_faces(
    seed: int,
    expected_faces: list[int],
) -> None:
    state = _turn_state()
    hero = state.context.actors["hero"]
    hero.actions[0].to_hit = 0
    hero.traits["lucky"] = {}
    hero.resources["luck_points"] = 1
    hero.max_resources["luck_points"] = 1
    session_id = f"table-lucky-{seed}"
    session = EngineSession(
        session_id,
        state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=seed,
    )
    session.execute(_prepare_command(session_id=session_id))

    preview = session.execute(
        _command(
            session_id=session_id,
            command_id="lucky-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id=session_id,
            command_id="lucky-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    attack = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    preview_attack = next(
        event.payload["record"]["fact"]
        for event in preview.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )

    assert attack == preview_attack
    assert [face["value"] for face in attack["roll"]["faces"]] == expected_faces
    assert [face["status"] for face in attack["roll"]["faces"]] == ["kept", "discarded"]
    assert attack["roll"]["candidate_generation_indices"] == [1, 2]
    assert attack["roll"]["mode"] == "resolved"
    assert attack["adjustments"] == []
    assert session.state["actors"]["hero"]["resources"]["luck_points"] == 0


def test_real_dnd_driver_preserves_bardic_die_without_rewriting_flat_modifier() -> None:
    state = _turn_state()
    hero = state.context.actors["hero"]
    hero.actions[0].to_hit = 0
    hero.resources["bardic_inspiration_die"] = 6
    hero.max_resources["bardic_inspiration_die"] = 6
    session = EngineSession(
        "table-bardic-roll",
        state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=7,
    )
    session.execute(_prepare_command(session_id="table-bardic-roll"))

    preview = session.execute(
        _command(
            session_id="table-bardic-roll",
            command_id="bardic-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id="table-bardic-roll",
            command_id="bardic-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    attack = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    preview_attack = next(
        event.payload["record"]["fact"]
        for event in preview.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )

    assert attack == preview_attack
    assert attack["roll"]["flat_modifier"] == 0
    assert attack["roll"]["total"] == 11
    assert attack["adjustments"] == [
        {
            "stage": "total",
            "kind": "bardic_inspiration",
            "amount": 2,
            "generated_face": {"generation_index": 1, "sides": 6, "value": 2},
        }
    ]
    assert attack["outcome"] == "hit"


def test_real_dnd_driver_preserves_cutting_words_die_and_shield_threshold() -> None:
    cutting_state = _turn_state()
    cutting_state.context.actors["hero"].actions[0].to_hit = 2
    bard = _actor("bard", team="enemy", position=(5.0, 0.0, 0.0))
    bard.traits["cutting words"] = {}
    bard.resources["bardic_inspiration"] = 1
    bard.max_resources["bardic_inspiration"] = 1
    cutting_state.context.actors[bard.actor_id] = bard
    cutting_state.context.initiative_order.append(bard.actor_id)
    cutting_state.context.resources_spent[bard.actor_id] = {}
    cutting_state.context.damage_dealt[bard.actor_id] = 0
    cutting_state.context.damage_taken[bard.actor_id] = 0
    cutting_state.context.threat_scores[bard.actor_id] = 0
    cutting = EngineSession(
        "table-cutting-attack",
        cutting_state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=7,
    )
    cutting.execute(_prepare_command(session_id="table-cutting-attack"))
    cutting_preview = cutting.execute(
        _command(
            session_id="table-cutting-attack",
            command_id="cutting-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    cutting_receipt = cutting.execute(
        _command(
            session_id="table-cutting-attack",
            command_id="cutting-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    cutting_attack = next(
        event.payload["record"]["fact"]
        for event in cutting_receipt.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    cutting_preview_attack = next(
        event.payload["record"]["fact"]
        for event in cutting_preview.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    assert cutting_attack == cutting_preview_attack
    assert cutting_attack["roll"]["total"] == 13
    assert cutting_attack["threshold"] == 12
    assert cutting_attack["adjustments"][0]["amount"] == -2
    assert cutting_attack["adjustments"][0]["generated_face"]["value"] == 2
    assert cutting_attack["outcome"] == "miss"

    shield_state = _turn_state()
    shield_state.context.actors["hero"].actions[0].to_hit = 5
    enemy = shield_state.context.actors["enemy"]
    enemy.ac = 15
    enemy.actions = [
        ActionDefinition(
            name="shield",
            action_type="utility",
            action_cost="reaction",
            target_mode="self",
            tags=["reaction", "shield_spell"],
        )
    ]
    enemy.resources["spell_slot_1"] = 1
    enemy.max_resources["spell_slot_1"] = 1
    shield = EngineSession(
        "table-shield-attack",
        shield_state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=7,
    )
    shield.execute(_prepare_command(session_id="table-shield-attack"))
    shield_preview = shield.execute(
        _command(
            session_id="table-shield-attack",
            command_id="shield-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    shield_receipt = shield.execute(
        _command(
            session_id="table-shield-attack",
            command_id="shield-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    shield_attack = next(
        event.payload["record"]["fact"]
        for event in shield_receipt.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    shield_preview_attack = next(
        event.payload["record"]["fact"]
        for event in shield_preview.events
        if event.kind == "dnd.roll.recorded.v1" and event.payload["record"]["purpose"] == "attack"
    )
    assert shield_attack == shield_preview_attack
    assert shield_attack["threshold"] == 20
    assert shield_attack["adjustments"] == [
        {
            "stage": "threshold",
            "kind": "shield",
            "amount": 5,
            "generated_face": None,
        }
    ]
    assert shield_attack["outcome"] == "miss"


def test_real_dnd_driver_finalizes_target_mitigation_in_damage_record() -> None:
    state = _turn_state()
    state.context.actors["enemy"].damage_resistances.add("slashing")
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-resistance-roll", state, driver, seed=13)
    session.execute(_prepare_command(session_id="table-resistance-roll"))

    receipt = session.execute(
        _command(
            session_id="table-resistance-roll",
            command_id="resisted-roll",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    damage = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    )

    assert damage["raw_damage"] == 4
    assert damage["applied_damage"] == 2
    assert damage["adjustments"] == [
        {
            "stage": "applied",
            "kind": "resistance",
            "amount": -2,
            "source_id": None,
            "generated_face": None,
        }
    ]
    assert session.state["actors"]["enemy"]["hp"] == 28


def test_real_dnd_driver_finalizes_each_generated_damage_packet() -> None:
    state = _turn_state()
    hero = state.context.actors["hero"]
    hero.traits["sneak attack"] = {}
    hero.class_levels["rogue"] = 3
    hero.actions[0].weapon_properties = ["finesse"]
    ally = _actor("ally", team="party", position=(5.0, 5.0, 0.0))
    state.context.actors[ally.actor_id] = ally
    state.context.initiative_order.append(ally.actor_id)
    state.context.damage_dealt[ally.actor_id] = 0
    state.context.damage_taken[ally.actor_id] = 0
    state.context.threat_scores[ally.actor_id] = 0
    state.context.resources_spent[ally.actor_id] = {}
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-packet-roll", state, driver, seed=13)
    session.execute(_prepare_command(session_id="table-packet-roll"))

    receipt = session.execute(
        _command(
            session_id="table-packet-roll",
            command_id="packet-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    damages = [
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    ]

    assert len(damages) == 2
    assert damages[0]["expression"] == "4"
    assert damages[1]["expression"] == "2d6"
    assert sum(damage["applied_damage"] for damage in damages) == (
        30 - session.state["actors"]["enemy"]["hp"]
    )
    assert len(damages[1]["faces"]) == 2


def test_real_dnd_driver_finalizes_attack_damage_after_cutting_words() -> None:
    state = _turn_state()
    bard = _actor("bard", team="enemy", position=(5.0, 0.0, 0.0))
    bard.traits["cutting words"] = {}
    bard.resources["bardic_inspiration"] = 1
    bard.max_resources["bardic_inspiration"] = 1
    state.context.actors[bard.actor_id] = bard
    state.context.initiative_order.append(bard.actor_id)
    state.context.damage_dealt[bard.actor_id] = 0
    state.context.damage_taken[bard.actor_id] = 0
    state.context.threat_scores[bard.actor_id] = 0
    state.context.resources_spent[bard.actor_id] = {}
    session = EngineSession(
        "table-cutting-damage",
        state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=13,
    )
    session.execute(_prepare_command(session_id="table-cutting-damage"))

    preview = session.execute(
        _command(
            session_id="table-cutting-damage",
            command_id="cutting-preview",
            mode="preview",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id="table-cutting-damage",
            command_id="cutting-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    preview_damage = [
        event.payload["record"]["fact"]
        for event in preview.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    ]
    committed_damage = [
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    ]

    assert committed_damage == preview_damage
    assert len(committed_damage) == 1
    assert committed_damage[0]["rolled_total"] == 4
    assert committed_damage[0]["raw_damage"] == 1
    assert committed_damage[0]["applied_damage"] == 1
    assert committed_damage[0]["adjustments"][0] == {
        "stage": "raw",
        "kind": "reduction",
        "amount": -3,
        "source_id": None,
        "generated_face": {"generation_index": 1, "sides": 6, "value": 3},
    }
    assert session.state["actors"]["enemy"]["hp"] == 29


def test_real_dnd_driver_correlates_multi_packet_cutting_words_by_packet_identity() -> None:
    state = _turn_state()
    hero = state.context.actors["hero"]
    hero.traits["sneak attack"] = {}
    hero.class_levels["rogue"] = 3
    hero.actions[0].weapon_properties = ["finesse"]
    ally = _actor("ally", team="party", position=(5.0, 5.0, 0.0))
    bard = _actor("bard", team="enemy", position=(5.0, 0.0, 0.0))
    bard.traits["cutting words"] = {}
    bard.resources["bardic_inspiration"] = 1
    bard.max_resources["bardic_inspiration"] = 1
    for participant in (ally, bard):
        state.context.actors[participant.actor_id] = participant
        state.context.initiative_order.append(participant.actor_id)
        state.context.damage_dealt[participant.actor_id] = 0
        state.context.damage_taken[participant.actor_id] = 0
        state.context.threat_scores[participant.actor_id] = 0
        state.context.resources_spent[participant.actor_id] = {}
    session = EngineSession(
        "table-cutting-packets",
        state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=13,
    )
    session.execute(_prepare_command(session_id="table-cutting-packets"))

    receipt = session.execute(
        _command(
            session_id="table-cutting-packets",
            command_id="packets-commit",
            mode="commit",
            declaration=_declaration(),
            expected_revision=1,
        )
    )
    damages = [
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    ]

    assert len(damages) == 2
    assert [damage["expression"] for damage in damages] == ["4", "2d6"]
    assert len(damages[1]["faces"]) == 2
    assert all(
        any(item["stage"] == "raw" and item["amount"] < 0 for item in damage["adjustments"])
        for damage in damages
    )
    generated_faces = [
        item["generated_face"]
        for damage in damages
        for item in damage["adjustments"]
        if item["stage"] == "raw" and item["generated_face"] is not None
    ]
    assert len(generated_faces) == 1
    assert sum(damage["applied_damage"] for damage in damages) == (
        30 - session.state["actors"]["enemy"]["hp"]
    )


def test_real_dnd_driver_finalizes_save_damage_after_cutting_words() -> None:
    state = _save_turn_state()
    bard = _actor("bard", team="enemy", position=(5.0, 0.0, 0.0))
    bard.traits["cutting words"] = {}
    bard.resources["bardic_inspiration"] = 1
    bard.max_resources["bardic_inspiration"] = 1
    state.context.actors[bard.actor_id] = bard
    state.context.initiative_order.append(bard.actor_id)
    state.context.damage_dealt[bard.actor_id] = 0
    state.context.damage_taken[bard.actor_id] = 0
    state.context.threat_scores[bard.actor_id] = 0
    state.context.resources_spent[bard.actor_id] = {}
    session = EngineSession(
        "table-cutting-save",
        state,
        DndCombatTurnDriver(version_pins=VERSION_PINS),
        seed=13,
    )
    session.execute(_prepare_command(session_id="table-cutting-save"))
    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name="frost_burst",
            targets=[TargetRef(actor_id="enemy")],
        ),
    )

    receipt = session.execute(
        _command(
            session_id="table-cutting-save",
            command_id="save-commit",
            mode="commit",
            declaration=declaration,
            expected_revision=1,
        )
    )
    damage = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["fact"]["kind"] == "damage"
    )

    assert damage["rolled_total"] == 4
    assert damage["raw_damage"] == 1
    assert damage["adjustments"][0]["stage"] == "raw"
    assert damage["adjustments"][0]["generated_face"]["value"] == 3
    assert damage["applied_damage"] == 30 - session.state["actors"]["enemy"]["hp"]


def test_real_dnd_driver_records_effective_healing_and_overheal() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-healing-roll", _healing_turn_state(), driver, seed=13)
    session.execute(_prepare_command(session_id="table-healing-roll"))
    declaration = TurnDeclaration(
        action=DeclaredAction(action_name="healing_word", targets=[]),
    )

    preview = session.execute(
        _command(
            session_id="table-healing-roll",
            command_id="healing-preview",
            mode="preview",
            declaration=declaration,
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id="table-healing-roll",
            command_id="healing-commit",
            mode="commit",
            declaration=declaration,
            expected_revision=1,
        )
    )
    preview_healing = next(
        event.payload["record"]["fact"]
        for event in preview.events
        if event.kind == "dnd.roll.recorded.v1"
    )
    committed_healing = next(
        event.payload["record"]["fact"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
    )

    assert committed_healing == preview_healing
    assert committed_healing["kind"] == "healing"
    assert 4 <= committed_healing["rolled_healing"] <= 7
    assert committed_healing["effective_healing"] == 2
    assert committed_healing["overheal"] == committed_healing["rolled_healing"] - 2
    assert committed_healing["faces"][0]["sides"] == 4
    assert session.state["actors"]["hero"]["hp"] == 30


def test_real_dnd_driver_records_save_outcome_and_target_applied_damage() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-save-roll", _save_turn_state(), driver, seed=13)
    session.execute(_prepare_command(session_id="table-save-roll"))
    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name="frost_burst",
            targets=[TargetRef(actor_id="enemy")],
        ),
    )

    preview = session.execute(
        _command(
            session_id="table-save-roll",
            command_id="save-preview",
            mode="preview",
            declaration=declaration,
            expected_revision=1,
        )
    )
    receipt = session.execute(
        _command(
            session_id="table-save-roll",
            command_id="save-commit",
            mode="commit",
            declaration=declaration,
            expected_revision=1,
        )
    )
    preview_rolls = [
        event.payload["record"] for event in preview.events if event.kind == "dnd.roll.recorded.v1"
    ]
    committed_rolls = [
        event.payload["record"] for event in receipt.events if event.kind == "dnd.roll.recorded.v1"
    ]

    assert committed_rolls == preview_rolls
    assert [record["fact"]["kind"] for record in committed_rolls] == [
        "saving_throw",
        "damage",
    ]
    save = committed_rolls[0]
    damage = committed_rolls[1]
    assert save["source_actor_id"] == "enemy"
    assert save["target_actor_id"] == "hero"
    assert save["fact"]["ability"] == "dexterity"
    assert save["fact"]["dc"] == 12
    assert save["fact"]["succeeded"] is (save["fact"]["roll"]["total"] >= save["fact"]["dc"])
    assert damage["source_actor_id"] == "hero"
    assert damage["target_actor_id"] == "enemy"
    assert damage["fact"]["raw_damage"] == 4
    assert damage["fact"]["applied_damage"] == 30 - session.state["actors"]["enemy"]["hp"]


def test_real_dnd_driver_records_both_sides_of_a_contested_check() -> None:
    state = _turn_state()
    state.context.actors["hero"].str_mod = 3
    state.context.actors["hero"].actions.insert(
        0,
        ActionDefinition(
            name="grapple",
            action_type="grapple",
            action_cost="action",
            target_mode="single_enemy",
            reach_ft=5,
        ),
    )
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-check-roll", state, driver, seed=13)
    session.execute(_prepare_command(session_id="table-check-roll"))

    receipt = session.execute(
        _command(
            session_id="table-check-roll",
            command_id="check-commit",
            mode="commit",
            declaration=TurnDeclaration(
                action=DeclaredAction(
                    action_name="grapple",
                    targets=[TargetRef(actor_id="enemy")],
                ),
            ),
            expected_revision=1,
        )
    )
    checks = [
        event.payload["record"]
        for event in receipt.events
        if event.kind == "dnd.roll.recorded.v1"
        and event.payload["record"]["purpose"] in {"check", "opposed_check"}
    ]

    assert [record["purpose"] for record in checks] == ["check", "opposed_check"]
    assert [record["source_actor_id"] for record in checks] == ["hero", "enemy"]
    assert all(record["fact"]["kind"] == "d20" for record in checks)
    assert {record["fact"]["outcome"] for record in checks} == {"success", "failure"}


def test_real_dnd_driver_accepts_browser_integer_movement_coordinates() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession(
        "table-browser-movement",
        _turn_state(enemy_position=(10.0, 0.0, 0.0)),
        driver,
        seed=13,
    )
    session.execute(_prepare_command(session_id="table-browser-movement"))
    canonical_command = _command(
        session_id="table-browser-movement",
        command_id="turn-browser-movement",
        mode="commit",
        declaration=_declaration(move=True),
        expected_revision=1,
    )
    browser_payload = copy.deepcopy(canonical_command.payload)
    browser_payload["movement_path"] = [[0, 0, 0], [5, 0, 0]]
    browser_command = SessionCommand.model_validate(
        {**canonical_command.model_dump(mode="json"), "payload": browser_payload}
    )

    receipt = session.execute(browser_command)

    assert receipt.events[0].payload["status"] == "resolved"
    assert session.state["actors"]["hero"]["position"] == [5.0, 0.0, 0.0]
    assert session.state["actors"]["hero"]["movement_remaining"] == 25.0
    assert session.state["actors"]["enemy"]["hp"] == 26


@pytest.mark.parametrize(
    "payload_case",
    ["omitted_field", "extra_field", "boolean_coordinate", "coercion_elsewhere"],
)
def test_real_dnd_driver_keeps_strict_declaration_canonicality(payload_case: str) -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session_id = f"table-strict-{payload_case}"
    session = EngineSession(session_id, _turn_state(), driver, seed=13)
    session.execute(_prepare_command(session_id=session_id))
    canonical_command = _command(
        session_id=session_id,
        command_id=f"turn-strict-{payload_case}",
        mode="commit",
        declaration=_declaration(move=True),
        expected_revision=1,
    )
    payload = copy.deepcopy(canonical_command.payload)
    if payload_case == "omitted_field":
        del payload["movement_path"]
    elif payload_case == "extra_field":
        payload["unexpected"] = True
    elif payload_case == "boolean_coordinate":
        payload["movement_path"] = [[False, 0, 0], [5, 0, 0]]
    else:
        payload["action"]["action_name"] = " strike "
    command = SessionCommand.model_validate(
        {**canonical_command.model_dump(mode="json"), "payload": payload}
    )

    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(command)

    assert exc_info.value.code == "invalid_command_payload"


def test_session_command_rejects_nonfinite_movement_coordinates() -> None:
    command = _command(
        session_id="table-nonfinite-movement",
        command_id="turn-nonfinite-movement",
        mode="commit",
        declaration=_declaration(move=True),
        expected_revision=1,
    )
    payload = copy.deepcopy(command.payload)
    payload["movement_path"] = [[0, 0, 0], [math.inf, 0, 0]]

    with pytest.raises(ValidationError, match="must not contain NaN or infinity"):
        SessionCommand.model_validate({**command.model_dump(mode="json"), "payload": payload})


def test_turn_session_projection_is_a_safe_public_view() -> None:
    state = _turn_state()
    state.context.rule_trace.append({"internal": "hidden"})
    state.context.resources_spent["hero"]["spell_slot"] = 1
    state.context.actors["hero"].traits["secret"] = {"value": 99}
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    assert isinstance(driver, EngineSessionProjectionDriver)
    session = EngineSession("turn-projection", state, driver, seed=13)

    projection = session.projection

    assert projection["active_actor_id"] == "hero"
    assert projection["actors"]["hero"]["hp"] == 30
    assert "schema_version" not in projection
    assert "rule_trace" not in projection
    assert "resources_spent" not in projection
    assert "traits" not in projection["actors"]["hero"]
    assert projection["choices"] is None


def test_turn_projection_exposes_repeatable_authoritative_choices() -> None:
    def choice_state() -> DndCombatTurnState:
        state = _turn_state()
        second_enemy = _actor(
            "enemy-2",
            team="enemy",
            position=(5.0, 5.0, 0.0),
        )
        state.context.actors[second_enemy.actor_id] = second_enemy
        state.context.initiative_order.append(second_enemy.actor_id)
        state.context.damage_dealt[second_enemy.actor_id] = 0
        state.context.damage_taken[second_enemy.actor_id] = 0
        state.context.threat_scores[second_enemy.actor_id] = 0
        state.context.resources_spent[second_enemy.actor_id] = {}
        state.context.actors["hero"].actions.extend(
            [
                ActionDefinition(
                    name="focus",
                    action_type="buff",
                    action_cost="bonus",
                    target_mode="self",
                ),
                ActionDefinition(
                    name="area_pulse",
                    action_type="save",
                    action_cost="action",
                    target_mode="all_enemies",
                    range_ft=5,
                ),
                ActionDefinition(
                    name="short_reach",
                    action_type="attack",
                    action_cost="action",
                    target_mode="single_enemy",
                    reach_ft=1,
                ),
                ActionDefinition(
                    name="spent_power",
                    action_type="buff",
                    action_cost="action",
                    target_mode="self",
                    resource_cost={"focus_points": 1},
                ),
            ]
        )
        return state

    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    projected = EngineSession("choice-projection", choice_state(), driver, seed=29)
    control = EngineSession("choice-projection", choice_state(), driver, seed=29)
    projected.execute(_prepare_command(session_id="choice-projection"))
    control.execute(_prepare_command(session_id="choice-projection"))
    before = projected.snapshot_json()

    first = projected.projection
    second = projected.projection

    assert first == second
    assert projected.snapshot_json() == before
    assert first["choices"] == {
        "schema_version": "dnd.turn-choices.v1",
        "actor_id": "hero",
        "movement": {
            "origin": [0.0, 0.0, 0.0],
            "remaining_ft": 30.0,
        },
        "actions": [
            {
                "action_name": "strike",
                "action_cost": "action",
                "target_mode": "single_enemy",
                "requires_explicit_targets": True,
                "selectable_target_ids": ["enemy", "enemy-2"],
                "legal_target_ids": ["enemy", "enemy-2"],
                "reason": None,
            },
            {
                "action_name": "focus",
                "action_cost": "bonus",
                "target_mode": "self",
                "requires_explicit_targets": False,
                "selectable_target_ids": ["hero"],
                "legal_target_ids": ["hero"],
                "reason": None,
            },
            {
                "action_name": "area_pulse",
                "action_cost": "action",
                "target_mode": "all_enemies",
                "requires_explicit_targets": False,
                "selectable_target_ids": ["enemy", "enemy-2"],
                "legal_target_ids": ["enemy", "enemy-2"],
                "reason": None,
            },
            {
                "action_name": "short_reach",
                "action_cost": "action",
                "target_mode": "single_enemy",
                "requires_explicit_targets": True,
                "selectable_target_ids": ["enemy", "enemy-2"],
                "legal_target_ids": [],
                "reason": "no_legal_targets",
            },
        ],
        "reason": None,
    }

    command = _command(
        session_id="choice-projection",
        command_id="choice-strike",
        mode="commit",
        declaration=_declaration(),
        expected_revision=1,
    )
    assert projected.execute(command).events == control.execute(command).events


def test_turn_projection_explains_when_no_actions_are_available() -> None:
    state = _turn_state()
    state.context.actors["hero"].actions.clear()
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("no-choice-projection", state, driver, seed=13)
    session.execute(_prepare_command(session_id="no-choice-projection"))

    choices = session.projection["choices"]

    assert choices["actions"] == []
    assert choices["reason"] == "no_available_actions"


def test_turn_choice_projection_does_not_mutate_live_runtime_inputs() -> None:
    state = _turn_state()
    state.context.active_hazards.append(
        {
            "hazard_id": "far_fog",
            "position": [100.0, 100.0, 0.0],
            "radius_ft": 5.0,
        }
    )
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    rng = random.Random(43)
    prepared = driver.prepare_turn(
        state,
        _prepare_command(session_id="live-choice-projection"),
        rng,
    )
    assert isinstance(prepared, CombatTurnPrompt)
    before_state = driver.encode_state(state)
    before_rng = rng.getstate()

    first = driver.project_choices(state)
    second = driver.project_choices(state)

    assert first == second
    assert driver.encode_state(state) == before_state
    assert rng.getstate() == before_rng


def test_invalid_late_bonus_rolls_back_real_dnd_state_and_rng() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    failed = EngineSession(
        "table-rollback",
        _turn_state(enemy_position=(10.0, 0.0, 0.0)),
        driver,
        seed=41,
    )
    control = EngineSession(
        "table-rollback",
        _turn_state(enemy_position=(10.0, 0.0, 0.0)),
        driver,
        seed=41,
    )
    failed.execute(_prepare_command(session_id="table-rollback"))
    control.execute(_prepare_command(session_id="table-rollback"))
    before = failed.snapshot_json()

    with pytest.raises(EngineSessionError) as exc_info:
        failed.execute(
            _command(
                session_id="table-rollback",
                command_id="invalid",
                mode="commit",
                declaration=_declaration(invalid_bonus=True, move=True),
                expected_revision=1,
            )
        )

    assert exc_info.value.code == "invalid_turn_declaration"
    assert exc_info.value.details["rule_error_code"] == "unknown_action"
    assert failed.snapshot_json() == before

    legal = _command(
        session_id="table-rollback",
        command_id="legal",
        mode="commit",
        declaration=_declaration(move=True),
        expected_revision=1,
    )
    failed_receipt = failed.execute(legal)
    control_receipt = control.execute(legal)

    assert failed.state == control.state
    assert failed_receipt.events == control_receipt.events


def test_real_dnd_driver_snapshot_restore_and_idempotent_retry_are_exact() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    session = EngineSession("table-restore", _turn_state(), driver, seed=19)
    session.execute(_prepare_command(session_id="table-restore"))
    command = _command(
        session_id="table-restore",
        command_id="turn-1",
        mode="commit",
        declaration=_declaration(),
        expected_revision=1,
    )
    original_receipt = session.execute(command)
    snapshot = session.snapshot()
    snapshot_json = session.snapshot_json()

    restored = EngineSession.restore(snapshot, driver)
    replayed_receipt = restored.execute(command)

    assert restored.snapshot_json() == snapshot_json
    assert replayed_receipt.replayed is True
    assert replayed_receipt.model_copy(update={"replayed": False}) == original_receipt


def test_real_dnd_driver_restores_at_prompt_without_rerunning_turn_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    uninterrupted = EngineSession("table-prompt", _turn_state(), driver, seed=37)
    uninterrupted.execute(_prepare_command(session_id="table-prompt"))
    restored = EngineSession.restore(uninterrupted.snapshot(), driver)
    command = _command(
        session_id="table-prompt",
        command_id="turn-1",
        mode="commit",
        declaration=_declaration(),
        expected_revision=1,
    )
    lifecycle: list[str] = []
    real_dispatch = engine_runtime._dispatch_combat_event

    def observing_dispatch(**kwargs):
        lifecycle.append(str(kwargs["event"]))
        return real_dispatch(**kwargs)

    monkeypatch.setattr(engine_runtime, "_dispatch_combat_event", observing_dispatch)

    uninterrupted_receipt = uninterrupted.execute(command)
    restored_receipt = restored.execute(command)

    assert restored.state == uninterrupted.state
    assert restored_receipt.events == uninterrupted_receipt.events
    assert "turn_start" not in lifecycle


def test_real_dnd_driver_fixed_seed_command_replay_is_byte_identical() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    command = _command(
        session_id="table-replay",
        command_id="turn-1",
        mode="commit",
        declaration=_declaration(),
        expected_revision=1,
    )

    first = EngineSession.replay(
        session_id="table-replay",
        initial_state=_turn_state(),
        driver=driver,
        seed=71,
        commands=[_prepare_command(session_id="table-replay"), command],
    )
    second = EngineSession.replay(
        session_id="table-replay",
        initial_state=_turn_state(),
        driver=driver,
        seed=71,
        commands=[_prepare_command(session_id="table-replay"), command],
    )

    assert first.snapshot_json() == second.snapshot_json()


def test_real_dnd_driver_state_codec_rejects_noncanonical_shape() -> None:
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    encoded = dict(driver.encode_state(_turn_state()))

    with_extra = {**encoded, "unexpected": True}
    with pytest.raises(ValueError, match="noncanonical fields"):
        driver.decode_state(with_extra)

    missing_actor_field = copy.deepcopy(encoded)
    del missing_actor_field["actors"]["hero"]["conditions"]
    with pytest.raises(ValueError, match="canonical runtime state"):
        driver.decode_state(missing_actor_field)

    invalid_timing_registration = copy.deepcopy(encoded)
    invalid_timing_registration["timing_next_subscription_id"] += 1
    with pytest.raises(ValueError, match="custom timing-engine registrations"):
        driver.decode_state(invalid_timing_registration)
