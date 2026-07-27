"""Original fixed encounter fixture for the first deterministic solo table.

The fixture is deliberately renderer-neutral. Its actor positions use the same
feet coordinate system as the engine and sit at square-grid cell centers in the
bound :class:`~dnd_sim.vtt.scene.SquareGridScene`.
"""

from __future__ import annotations

from dataclasses import dataclass

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.interactive.contracts import EngineVersionPins
from dnd_sim.interactive.dnd_encounter_driver import DndCombatEncounterState
from dnd_sim.interactive.dnd_turn_driver import DndCombatTurnState
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.turn_kernel import CombatTurnContext

from .scene import SCENE_SCHEMA_VERSION, FeetPosition, GridCell, SquareGridScene

SOLO_TABLE_ENGINE_VERSION = "dnd-sim@0.1.0"
SOLO_TABLE_RULES_VERSION = "5e_2014_combat_foundation@1.0.0"
SOLO_TABLE_CONTENT_VERSION = "solo-table.echo-vault@1.1.0"
SOLO_TABLE_SEED = 24_681_357
SOLO_TABLE_MAX_ROUNDS = 4

_VELA_ID = "vela_quill"
_SENTRY_ID = "hushglass_sentry"
_INITIATIVE_ORDER = (_VELA_ID, _SENTRY_ID)


@dataclass(frozen=True, slots=True)
class SoloTableFixture:
    """One fresh scene and authoritative encounter state with replay pins."""

    scene: SquareGridScene
    encounter_state: DndCombatEncounterState
    version_pins: EngineVersionPins
    seed: int


def _actor(
    *,
    actor_id: str,
    team: str,
    name: str,
    hp: int,
    ac: int,
    position: FeetPosition,
    action: ActionDefinition,
    uses_death_saves: bool,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=name,
        max_hp=hp,
        hp=hp,
        temp_hp=0,
        ac=ac,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={
            "str": 0,
            "dex": 0,
            "con": 0,
            "int": 0,
            "wis": 0,
            "cha": 0,
        },
        actions=[action],
        uses_death_saves=uses_death_saves,
        movement_remaining=0.0,
        position=(position.x_ft, position.y_ft, position.z_ft),
    )


def _build_scene() -> SquareGridScene:
    return SquareGridScene(
        schema_version=SCENE_SCHEMA_VERSION,
        scene_id="echo-vault",
        name="Echo Vault",
        cell_size_ft=5.0,
        columns=8,
        rows=6,
        origin_ft=FeetPosition(x_ft=0.0, y_ft=0.0, z_ft=0.0),
    )


def _build_actors(scene: SquareGridScene) -> dict[str, ActorRuntimeState]:
    vela = _actor(
        actor_id=_VELA_ID,
        team="party",
        name="Vela Quill",
        hp=24,
        ac=15,
        position=scene.grid_cell_to_feet(GridCell(column=2, row=2)),
        action=ActionDefinition(
            name="Lattice Lance",
            action_type="attack",
            action_cost="action",
            target_mode="single_enemy",
            to_hit=100,
            damage="7",
            damage_type="force",
            reach_ft=5,
        ),
        uses_death_saves=True,
    )
    sentry = _actor(
        actor_id=_SENTRY_ID,
        team="enemy",
        name="Hushglass Sentry",
        hp=7,
        ac=12,
        position=scene.grid_cell_to_feet(GridCell(column=4, row=2)),
        action=ActionDefinition(
            name="Quietus Needle",
            action_type="attack",
            action_cost="action",
            target_mode="single_enemy",
            to_hit=4,
            damage="5",
            damage_type="piercing",
            reach_ft=5,
        ),
        uses_death_saves=False,
    )
    return {_VELA_ID: vela, _SENTRY_ID: sentry}


def build_solo_table_fixture() -> SoloTableFixture:
    """Return a new deterministic Echo Vault fixture with no shared mutable state."""

    scene = _build_scene()
    actors = _build_actors(scene)
    initiative_order = list(_INITIATIVE_ORDER)
    context = CombatTurnContext(
        actors=actors,
        initiative_order=initiative_order,
        round_number=1,
        damage_dealt={actor_id: 0 for actor_id in initiative_order},
        damage_taken={actor_id: 0 for actor_id in initiative_order},
        threat_scores={actor_id: 0 for actor_id in initiative_order},
        resources_spent={actor_id: {} for actor_id in initiative_order},
        active_hazards=[],
        telemetry=[],
        rule_trace=[],
        obstacles=[],
        light_level="bright",
        burst_round_threshold=3,
        strategy_overrides={},
        timing_engine=engine_runtime._create_combat_timing_engine(),
        party_defeat_rule="all_unconscious_or_dead",
        enemy_defeat_rule="all_dead",
    )
    encounter_state = DndCombatEncounterState(
        turn=DndCombatTurnState(
            context=context,
            actor_id=initiative_order[0],
        ),
        current_index=0,
        max_rounds=SOLO_TABLE_MAX_ROUNDS,
    )
    version_pins = EngineVersionPins(
        engine_version=SOLO_TABLE_ENGINE_VERSION,
        rules_version=SOLO_TABLE_RULES_VERSION,
        content_version=SOLO_TABLE_CONTENT_VERSION,
    )
    return SoloTableFixture(
        scene=scene,
        encounter_state=encounter_state,
        version_pins=version_pins,
        seed=SOLO_TABLE_SEED,
    )
