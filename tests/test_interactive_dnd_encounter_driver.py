from __future__ import annotations

import copy

import pytest

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.interactive import (
    EngineSession,
    EngineSessionError,
    EngineVersionPins,
    SessionCommand,
)
from dnd_sim.interactive.dnd_contracts import (
    DECLARATION_COMMAND_KIND,
    TurnDeclarationPayload,
)
from dnd_sim.interactive.dnd_encounter_driver import (
    DND_ENCOUNTER_STATE_SCHEMA_VERSION,
    START_ENCOUNTER_COMMAND_KIND,
    DndCombatEncounterDriver,
    DndCombatEncounterState,
)
from dnd_sim.interactive.dnd_turn_driver import DndCombatTurnState
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.turn_kernel import CombatTurnContext

VERSION_PINS = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="5e_2014_combat_foundation@1.0.0",
    content_version="encounter-fixture@1",
)


def _actor(
    actor_id: str,
    *,
    team: str,
    hp: int = 30,
    actions: list[ActionDefinition] | None = None,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
        max_hp=max(30, hp),
        hp=hp,
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
        uses_death_saves=team == "party",
        movement_remaining=0.0,
        position=(0.0, 0.0, 0.0),
    )


def _strike(*, damage: str = "4") -> ActionDefinition:
    return ActionDefinition(
        name="strike",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=100,
        damage=damage,
        damage_type="slashing",
        reach_ft=5,
    )


def _encounter_state(
    *,
    hero_hp: int = 30,
    enemy_hp: int = 30,
    max_rounds: int = 3,
    include_automatic_ally: bool = False,
) -> DndCombatEncounterState:
    hero = _actor("hero", team="party", hp=hero_hp, actions=[_strike()])
    enemy = _actor("enemy", team="enemy", hp=enemy_hp, actions=[_strike()])
    enemy.position = (5.0, 0.0, 0.0)
    actors = {"hero": hero}
    initiative_order = ["hero"]
    if include_automatic_ally:
        ally = _actor("ally", team="party", hp=0)
        ally.uses_death_saves = True
        ally.update_manual_conditions({"unconscious", "incapacitated", "prone"})
        actors["ally"] = ally
        initiative_order.append("ally")
    actors["enemy"] = enemy
    initiative_order.append("enemy")
    context = CombatTurnContext(
        actors=actors,
        initiative_order=initiative_order,
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
    return DndCombatEncounterState(
        turn=DndCombatTurnState(context=context, actor_id=initiative_order[0]),
        current_index=0,
        max_rounds=max_rounds,
    )


def _start_command(*, session_id: str, command_id: str = "start") -> SessionCommand:
    return SessionCommand(
        command_id=command_id,
        session_id=session_id,
        actor_id=None,
        expected_revision=0,
        mode="admin",
        kind=START_ENCOUNTER_COMMAND_KIND,
        version_pins=VERSION_PINS,
        payload={},
    )


def _declaration_command(
    *,
    session_id: str,
    command_id: str,
    actor_id: str,
    expected_revision: int,
    mode: str = "commit",
    target_id: str | None = None,
    invalid_bonus: bool = False,
) -> SessionCommand:
    declaration = TurnDeclaration(
        action=(
            DeclaredAction(
                action_name="strike",
                targets=[TargetRef(actor_id=target_id)],
            )
            if target_id is not None
            else None
        ),
        bonus_action=(
            DeclaredAction(
                action_name="missing_bonus",
                targets=[TargetRef(actor_id=target_id or "enemy")],
            )
            if invalid_bonus
            else None
        ),
    )
    return SessionCommand(
        command_id=command_id,
        session_id=session_id,
        actor_id=actor_id,
        expected_revision=expected_revision,
        mode=mode,
        kind=DECLARATION_COMMAND_KIND,
        version_pins=VERSION_PINS,
        payload=TurnDeclarationPayload.from_domain(declaration).model_dump(mode="json"),
    )


def test_start_prepares_first_durable_prompt_and_declaration_advances_cursor() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession("encounter", _encounter_state(), driver, seed=13)

    started = session.execute(_start_command(session_id="encounter"))

    assert started.events[0].kind == "dnd.encounter.started"
    assert started.events[-1].kind == "dnd.turn.prepared"
    assert session.state["turn"]["phase"] == "awaiting_declaration"
    assert session.state["turn"]["actor_id"] == "hero"
    assert session.state["current_index"] == 0

    resolved = session.execute(
        _declaration_command(
            session_id="encounter",
            command_id="hero-turn",
            actor_id="hero",
            expected_revision=1,
            target_id="enemy",
        )
    )

    assert resolved.events[0].kind == "dnd.turn.resolved"
    assert resolved.events[-1].kind == "dnd.turn.prepared"
    assert session.state["current_index"] == 1
    assert session.state["turn"]["actor_id"] == "enemy"
    assert session.state["turn"]["phase"] == "awaiting_declaration"
    assert session.state["turn"]["actors"]["enemy"]["hp"] == 26


def test_encounter_auto_prepares_successive_automatic_slots_until_prompt() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession(
        "auto-slots",
        _encounter_state(include_automatic_ally=True),
        driver,
        seed=7,
    )
    session.execute(_start_command(session_id="auto-slots"))

    receipt = session.execute(
        _declaration_command(
            session_id="auto-slots",
            command_id="hero-turn",
            actor_id="hero",
            expected_revision=1,
        )
    )

    assert [event.kind for event in receipt.events] == [
        "dnd.turn.resolved",
        "dnd.turn.completed_automatically",
        "dnd.turn.prepared",
    ]
    assert session.state["current_index"] == 2
    assert session.state["turn"]["actor_id"] == "enemy"
    assert session.state["turn"]["actors"]["ally"]["death_successes"] == 1


def test_round_wrap_resets_batch_round_flags_and_prepares_first_slot() -> None:
    state = _encounter_state(max_rounds=2)
    for actor in state.turn.context.actors.values():
        actor.lair_action_used_this_round = True
        actor.commanded_this_round = True
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession("round-wrap", state, driver, seed=17)
    session.execute(_start_command(session_id="round-wrap"))
    session.execute(
        _declaration_command(
            session_id="round-wrap",
            command_id="hero-r1",
            actor_id="hero",
            expected_revision=1,
        )
    )

    session.execute(
        _declaration_command(
            session_id="round-wrap",
            command_id="enemy-r1",
            actor_id="enemy",
            expected_revision=2,
        )
    )

    assert session.state["turn"]["round_number"] == 2
    assert session.state["current_index"] == 0
    assert session.state["turn"]["actor_id"] == "hero"
    assert session.state["turn"]["phase"] == "awaiting_declaration"
    assert all(
        actor["lair_action_used_this_round"] is False and actor["commanded_this_round"] is False
        for actor in session.state["turn"]["actors"].values()
    )


def test_max_round_timeout_is_terminal_after_last_slot() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession("timeout", _encounter_state(max_rounds=1), driver, seed=23)
    session.execute(_start_command(session_id="timeout"))
    session.execute(
        _declaration_command(
            session_id="timeout",
            command_id="hero",
            actor_id="hero",
            expected_revision=1,
        )
    )

    receipt = session.execute(
        _declaration_command(
            session_id="timeout",
            command_id="enemy",
            actor_id="enemy",
            expected_revision=2,
        )
    )

    assert receipt.events[-1].kind == "dnd.encounter.completed"
    assert receipt.events[-1].payload["outcome"] == "timeout"
    assert session.state["outcome"] == "timeout"
    assert session.state["current_index"] == 1
    assert session.state["turn"]["phase"] == "complete"


def test_party_victory_is_terminal_and_rejects_later_commands() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession(
        "party-wins",
        _encounter_state(enemy_hp=4),
        driver,
        seed=13,
    )
    session.execute(_start_command(session_id="party-wins"))

    receipt = session.execute(
        _declaration_command(
            session_id="party-wins",
            command_id="winning-hit",
            actor_id="hero",
            expected_revision=1,
            target_id="enemy",
        )
    )

    assert receipt.events[-1].payload["outcome"] == "party_victory"
    assert session.state["outcome"] == "party_victory"
    before = session.snapshot_json()
    with pytest.raises(EngineSessionError) as exc_info:
        session.execute(
            _declaration_command(
                session_id="party-wins",
                command_id="too-late",
                actor_id="hero",
                expected_revision=2,
            )
        )
    assert exc_info.value.code == "encounter_complete"
    assert session.snapshot_json() == before


def test_enemy_victory_is_terminal() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession(
        "enemy-wins",
        _encounter_state(hero_hp=4),
        driver,
        seed=29,
    )
    session.execute(_start_command(session_id="enemy-wins"))
    session.execute(
        _declaration_command(
            session_id="enemy-wins",
            command_id="hero-pass",
            actor_id="hero",
            expected_revision=1,
        )
    )

    receipt = session.execute(
        _declaration_command(
            session_id="enemy-wins",
            command_id="enemy-hit",
            actor_id="enemy",
            expected_revision=2,
            target_id="hero",
        )
    )

    assert receipt.events[-1].payload["outcome"] == "enemy_victory"
    assert session.state["outcome"] == "enemy_victory"


def test_preview_matches_commit_candidate_without_mutating_session() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession("preview", _encounter_state(), driver, seed=13)
    session.execute(_start_command(session_id="preview"))
    command = _declaration_command(
        session_id="preview",
        command_id="hero-preview",
        actor_id="hero",
        expected_revision=1,
        mode="preview",
        target_id="enemy",
    )

    preview = session.execute(command)

    assert session.revision == 1
    assert session.state["current_index"] == 0
    assert preview.projection["active_actor_id"] == "enemy"
    assert preview.projection["actors"]["enemy"]["hp"] == 26

    commit = command.model_copy(update={"command_id": "hero-commit", "mode": "commit"})
    session.execute(commit)

    assert session.state["current_index"] == preview.projection["current_index"]
    assert session.state["turn"]["actor_id"] == preview.projection["active_actor_id"]
    assert session.state["turn"]["actors"]["enemy"]["hp"] == 26


def test_invalid_declaration_rolls_back_encounter_cursor_state_and_rng() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    failed = EngineSession("rollback", _encounter_state(), driver, seed=41)
    control = EngineSession("rollback", _encounter_state(), driver, seed=41)
    failed.execute(_start_command(session_id="rollback"))
    control.execute(_start_command(session_id="rollback"))
    before = failed.snapshot_json()

    with pytest.raises(EngineSessionError) as exc_info:
        failed.execute(
            _declaration_command(
                session_id="rollback",
                command_id="invalid",
                actor_id="hero",
                expected_revision=1,
                target_id="enemy",
                invalid_bonus=True,
            )
        )

    assert exc_info.value.code == "invalid_turn_declaration"
    assert failed.snapshot_json() == before
    legal = _declaration_command(
        session_id="rollback",
        command_id="legal",
        actor_id="hero",
        expected_revision=1,
        target_id="enemy",
    )
    assert failed.execute(legal).events == control.execute(legal).events
    assert failed.snapshot_json() == control.snapshot_json()


def test_mid_round_snapshot_restore_and_fixed_seed_replay_are_exact() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    session = EngineSession("restore", _encounter_state(), driver, seed=53)
    start = _start_command(session_id="restore")
    hero = _declaration_command(
        session_id="restore",
        command_id="hero",
        actor_id="hero",
        expected_revision=1,
        target_id="enemy",
    )
    enemy = _declaration_command(
        session_id="restore",
        command_id="enemy",
        actor_id="enemy",
        expected_revision=2,
        target_id="hero",
    )
    session.execute(start)
    session.execute(hero)
    restored = EngineSession.restore(session.snapshot(), driver)

    original_receipt = session.execute(enemy)
    restored_receipt = restored.execute(enemy)

    assert restored_receipt.events == original_receipt.events
    assert restored.snapshot_json() == session.snapshot_json()

    first = EngineSession.replay(
        session_id="restore",
        initial_state=_encounter_state(),
        driver=driver,
        seed=53,
        commands=[start, hero, enemy],
    )
    second = EngineSession.replay(
        session_id="restore",
        initial_state=_encounter_state(),
        driver=driver,
        seed=53,
        commands=[start, hero, enemy],
    )
    assert first.snapshot_json() == second.snapshot_json()


def test_encounter_codec_is_strict_versioned_and_enforces_fixed_roster() -> None:
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)
    state = _encounter_state()
    payload = dict(driver.encode_state(state))

    assert payload["schema_version"] == DND_ENCOUNTER_STATE_SCHEMA_VERSION
    assert driver.encode_state(driver.decode_state(payload)) == payload

    with_extra = {**payload, "unexpected": True}
    with pytest.raises(ValueError, match="noncanonical fields"):
        driver.decode_state(with_extra)

    wrong_cursor = copy.deepcopy(payload)
    wrong_cursor["current_index"] = 1
    with pytest.raises(ValueError, match="active turn actor"):
        driver.decode_state(wrong_cursor)

    state.turn.context.actors["summon"] = _actor("summon", team="party")
    with pytest.raises(ValueError, match="initiative_order"):
        driver.encode_state(state)


def test_encounter_v1_rejects_lair_actions_explicitly() -> None:
    state = _encounter_state()
    state.turn.context.actors["enemy"].actions.append(
        ActionDefinition(name="lair pulse", action_type="save", action_cost="lair")
    )
    driver = DndCombatEncounterDriver(version_pins=VERSION_PINS)

    with pytest.raises(ValueError, match="lair actions are unsupported"):
        driver.encode_state(state)
