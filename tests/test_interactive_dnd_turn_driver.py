from __future__ import annotations

import copy
import random

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
from dnd_sim.interactive.dnd_turn_driver import (
    PREPARE_TURN_COMMAND_KIND,
    DndCombatTurnDriver,
    DndCombatTurnState,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.turn_kernel import CombatTurnContext

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
