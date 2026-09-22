from __future__ import annotations

import random
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.interactive import (
    EngineTransition,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PreviewOutcome,
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
from dnd_sim.vtt import (
    VTT_COMMAND_SCHEMA_VERSION,
    VTT_COMMIT_RESPONSE_SCHEMA_VERSION,
    VTT_EVENT_SCHEMA_VERSION,
    VTT_PREVIEW_RESPONSE_SCHEMA_VERSION,
    SQLiteSessionEventStore,
    VTTCommand,
    VTTCommitResponse,
    VTTPreviewResponse,
    VTTSessionService,
)

VERSION_PINS = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="5e_2014_combat_foundation@1.0.0",
    content_version="solo-table-fixture@1",
)


class CounterDriver:
    version_pins = EngineVersionPins(
        engine_version="counter@1",
        rules_version="counter-rules@1",
        content_version="counter-content@1",
    )

    def encode_state(self, state: Any) -> Mapping[str, Any]:
        return {"value": state["value"]}

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, int]:
        return {"value": int(payload["value"])}

    def preview(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        return PreviewOutcome(
            projection={"value": state["value"] + int(command.payload["amount"])},
            events=(EventDraft(kind="counter.previewed", payload={}),),
        )

    def commit(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        next_value = state["value"] + int(command.payload["amount"])
        roll = rng.randint(1, 20)
        return EngineTransition(
            state={"value": next_value},
            events=(
                EventDraft(
                    kind="counter.changed",
                    payload={"value": next_value, "roll": roll},
                ),
            ),
        )

    def respond_to_reaction(
        self,
        state: dict[str, int],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise AssertionError("counter tests do not open reactions")


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


def _turn_state() -> DndCombatTurnState:
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


def _declaration_payload() -> dict[str, Any]:
    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name="strike",
            targets=[TargetRef(actor_id="enemy")],
        )
    )
    return TurnDeclarationPayload.from_domain(declaration).model_dump(mode="json")


def _vtt_command(
    *,
    command_id: str,
    expected_revision: int,
    mode: str = "commit",
    kind: str = "counter.increment.v1",
    payload: dict[str, Any] | None = None,
    session_id: str = "table-1",
    actor_id: str | None = "hero",
) -> VTTCommand:
    return VTTCommand(
        command_id=command_id,
        session_id=session_id,
        actor_id=actor_id,
        expected_revision=expected_revision,
        mode=mode,
        kind=kind,
        payload={"amount": 1} if payload is None else payload,
    )


def test_vtt_command_is_strict_and_injects_engine_versions_only_when_translated() -> None:
    command = _vtt_command(command_id="command-1", expected_revision=0)

    wire_payload = command.model_dump(mode="json")
    translated = command.to_session_command(CounterDriver.version_pins)

    assert wire_payload["schema_version"] == VTT_COMMAND_SCHEMA_VERSION
    assert "version_pins" not in wire_payload
    assert translated.command_id == command.command_id
    assert translated.version_pins == CounterDriver.version_pins
    assert translated.schema_version == "engine.command.v1"

    with pytest.raises(ValidationError):
        VTTCommand.model_validate({**wire_payload, "expected_revision": "0"})
    with pytest.raises(ValidationError):
        VTTCommand.model_validate({**wire_payload, "schema_version": "vtt.command.v2"})
    with pytest.raises(ValidationError):
        VTTCommand.model_validate({**wire_payload, "version_pins": {}})


def test_preview_returns_only_vtt_schemas_and_is_never_persisted() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteSessionEventStore(connection)
    service = VTTSessionService.open(
        session_id="table-1",
        initial_state={"value": 2},
        driver=CounterDriver(),
        seed=7,
        event_store=store,
    )

    response = service.execute(
        _vtt_command(
            command_id="preview-1",
            expected_revision=0,
            mode="preview",
            payload={"amount": 3},
        )
    )

    assert isinstance(response, VTTPreviewResponse)
    assert response.schema_version == VTT_PREVIEW_RESPONSE_SCHEMA_VERSION
    assert response.projection == {"value": 5}
    assert response.events[0].schema_version.startswith("vtt.")
    assert service.revision == 0
    assert service.state == {"value": 2}
    assert store.load_commands("table-1") == ()


def test_store_failure_restores_the_pre_command_session_snapshot() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteSessionEventStore(connection)
    service = VTTSessionService.open(
        session_id="table-1",
        initial_state={"value": 2},
        driver=CounterDriver(),
        seed=7,
        event_store=store,
    )
    connection.execute("""
        CREATE TRIGGER reject_vtt_commits
        BEFORE INSERT ON vtt_committed_commands
        BEGIN
            SELECT RAISE(ABORT, 'simulated storage failure');
        END
        """)
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="simulated storage failure"):
        service.execute(
            _vtt_command(
                command_id="commit-1",
                expected_revision=0,
                payload={"amount": 3},
            )
        )

    assert service.revision == 0
    assert service.state == {"value": 2}
    assert store.load_commands("table-1") == ()

    connection.execute("DROP TRIGGER reject_vtt_commits")
    connection.commit()
    retried = service.execute(
        _vtt_command(
            command_id="commit-1",
            expected_revision=0,
            payload={"amount": 3},
        )
    )
    control_connection = sqlite3.connect(":memory:")
    control = VTTSessionService.open(
        session_id="table-1",
        initial_state={"value": 2},
        driver=CounterDriver(),
        seed=7,
        event_store=SQLiteSessionEventStore(control_connection),
    )
    control_response = control.execute(
        _vtt_command(
            command_id="commit-1",
            expected_revision=0,
            payload={"amount": 3},
        )
    )

    assert retried == control_response


def test_real_dnd_prepare_preview_commit_restart_and_retry_are_durable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "vtt-session.sqlite3"
    driver = DndCombatTurnDriver(version_pins=VERSION_PINS)
    first_connection = sqlite3.connect(database_path)
    first_store = SQLiteSessionEventStore(first_connection)
    first_service = VTTSessionService.open(
        session_id="encounter-1",
        initial_state=_turn_state(),
        driver=driver,
        seed=13,
        event_store=first_store,
    )
    prepare = _vtt_command(
        session_id="encounter-1",
        command_id="prepare-1",
        actor_id="hero",
        expected_revision=0,
        mode="admin",
        kind=PREPARE_TURN_COMMAND_KIND,
        payload={},
    )

    prepared = first_service.execute(prepare)

    assert isinstance(prepared, VTTCommitResponse)
    assert prepared.schema_version == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
    assert prepared.events[0].schema_version == VTT_EVENT_SCHEMA_VERSION
    assert prepared.events[0].kind == "dnd.turn.prepared"
    assert first_service.revision == 1

    preview = first_service.execute(
        _vtt_command(
            session_id="encounter-1",
            command_id="turn-preview-1",
            actor_id="hero",
            expected_revision=1,
            mode="preview",
            kind=DECLARATION_COMMAND_KIND,
            payload=_declaration_payload(),
        )
    )

    assert isinstance(preview, VTTPreviewResponse)
    assert preview.projection["actors"]["enemy"]["hp"] == 26
    assert first_service.revision == 1
    assert len(first_store.load_commands("encounter-1")) == 1

    commit = _vtt_command(
        session_id="encounter-1",
        command_id="turn-1",
        actor_id="hero",
        expected_revision=1,
        mode="commit",
        kind=DECLARATION_COMMAND_KIND,
        payload=_declaration_payload(),
    )
    committed = first_service.execute(commit)

    assert isinstance(committed, VTTCommitResponse)
    assert committed.replayed is False
    assert committed.revision == 2
    assert committed.events[0].kind == "dnd.turn.resolved"
    assert first_service.state["actors"]["enemy"]["hp"] == 26
    stored_commands = first_store.load_commands("encounter-1")
    assert len(stored_commands) == 2
    assert stored_commands[1].command["schema_version"] == VTT_COMMAND_SCHEMA_VERSION
    assert "version_pins" not in stored_commands[1].command
    first_connection.close()

    second_connection = sqlite3.connect(database_path)
    second_store = SQLiteSessionEventStore(second_connection)
    before_retry = second_store.load_latest_snapshot("encounter-1")
    assert before_retry is not None
    second_service = VTTSessionService.open(
        session_id="encounter-1",
        initial_state=_turn_state(),
        driver=driver,
        seed=999,
        event_store=second_store,
    )

    retried = second_service.execute(commit)

    assert isinstance(retried, VTTCommitResponse)
    assert retried.replayed is True
    assert retried.model_copy(update={"replayed": False}) == committed
    assert second_service.revision == 2
    assert second_service.state["actors"]["enemy"]["hp"] == 26
    assert len(second_store.load_commands("encounter-1")) == 2
    after_retry = second_store.load_latest_snapshot("encounter-1")
    assert after_retry == before_retry
    second_connection.close()
