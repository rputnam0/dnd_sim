"""One durable session spanning story choices and shared-engine encounters."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.interactive.contracts import (
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.interactive.dnd_contracts import DECLARATION_COMMAND_KIND, TurnDeclarationPayload
from dnd_sim.interactive.dnd_encounter_driver import (
    START_ENCOUNTER_COMMAND_KIND,
    DndCombatEncounterDriver,
    DndCombatEncounterState,
)
from dnd_sim.interactive.dnd_state_codec import (
    decode_actor_runtime_state_map,
    encode_actor_runtime_state_map,
)
from dnd_sim.interactive.dnd_turn_driver import DndCombatTurnDriver, DndCombatTurnState
from dnd_sim.interactive.session import EngineSessionError, EngineTransition
from dnd_sim.models import ActorRuntimeState
from dnd_sim.strategy_api import BaseStrategy, TurnDeclaration
from dnd_sim.turn_kernel import CombatTurnContext, CombatTurnPrompt
from dnd_sim.vtt.scene import FeetPosition, SquareGridScene

from .content import (
    CHOICES,
    CONTENT_VERSION,
    LOCATIONS,
    PARTY_IDS,
    PARTY_POSITIONS,
    create_enemies,
    create_party,
)

STATE_SCHEMA_VERSION = "adventure.state.v1"
CHOOSE_COMMAND_KIND = "adventure.choose.v1"
VERSION_PINS = EngineVersionPins(
    engine_version="dnd-sim@0.1.0",
    rules_version="5e_2014_combat_foundation@1.0.0",
    content_version=CONTENT_VERSION,
)
KNOWN_FLAGS = frozenset(
    {
        "orin_listened",
        "beacon_asked",
        "persuasion_attempted",
        "keeper_helped",
        "wardens_defeated",
        "archive_searched",
        "account_read",
        "trap_disarmed",
        "trap_sprung",
        "lock_attempted",
        "chest_open",
        "supplies_taken",
        "rest_used",
        "lantern_defeated",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class JournalEntry(_StrictModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=1200)


class _Snapshot(_StrictModel):
    schema_version: Literal["adventure.state.v1"]
    content_version: Literal["the-lantern-below@1.0.0"]
    location: Literal["landing", "hall", "archive", "stair", "beacon", "return"]
    phase: Literal["exploration", "combat", "complete", "defeat"]
    party: dict[str, Any]
    encounter: dict[str, Any] | None
    encounter_id: Literal["wardens", "lantern"] | None
    flags: list[str] = Field(max_length=32)
    journal: list[JournalEntry] = Field(max_length=40)
    supplies: int = Field(ge=0, le=2)
    ending: Literal["restore_beacon", "release_spirit"] | None
    run_number: int = Field(ge=1, le=1_000_000)


@dataclass(slots=True)
class AdventureState:
    """The party belongs to the encounter only while combat is active."""

    party: dict[str, ActorRuntimeState]
    location: str = "landing"
    phase: str = "exploration"
    encounter: DndCombatEncounterState | None = None
    encounter_id: str | None = None
    flags: set[str] = field(default_factory=set)
    journal: list[JournalEntry] = field(default_factory=list)
    supplies: int = 0
    ending: str | None = None
    run_number: int = 1


def create_initial_state() -> AdventureState:
    """Start a new authored adventure without resetting its session history."""
    return AdventureState(
        party=create_party(),
        journal=[
            JournalEntry(
                id="arrival",
                title="A light before the tide",
                text="Reach the chamber below the tower and rekindle the beacon before the fishing fleet reaches the rocks. Mara's driving strike and Iven's focused shot spend limited resources; Sela's mending light can heal a fallen companion. You control their turns, and enemies act automatically.",
            )
        ],
    )


def _conscious(actor: ActorRuntimeState) -> bool:
    return actor.hp > 0 and not actor.dead and "incapacitated" not in actor.conditions


def _note(state: AdventureState, entry_id: str, title: str, text: str) -> None:
    entry = JournalEntry(id=entry_id, title=title, text=text)
    state.journal = [item for item in state.journal if item.id != entry_id] + [entry]


class AdventureDriver:
    """Commit legal player choices and enemy turns with the session's sole RNG."""

    def __init__(self) -> None:
        self.version_pins = VERSION_PINS.model_copy()
        self._combat = DndCombatEncounterDriver(version_pins=self.version_pins)

    @staticmethod
    def _party(state: AdventureState) -> dict[str, ActorRuntimeState]:
        actors = state.encounter.turn.context.actors if state.encounter else state.party
        return {actor_id: actors[actor_id] for actor_id in PARTY_IDS}

    @staticmethod
    def _scene(state: AdventureState) -> SquareGridScene:
        return SquareGridScene(
            schema_version="vtt.scene.v1",
            scene_id=f"lantern_{state.location}",
            name=LOCATIONS[state.location][0],
            cell_size_ft=5.0,
            columns=12,
            rows=8,
        )

    def encode_state(self, state: AdventureState) -> Mapping[str, Any]:
        if not isinstance(state, AdventureState):
            raise TypeError("state must be AdventureState")
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "content_version": CONTENT_VERSION,
            "location": state.location,
            "phase": state.phase,
            "party": encode_actor_runtime_state_map(state.party),
            "encounter": self._combat.encode_state(state.encounter) if state.encounter else None,
            "encounter_id": state.encounter_id,
            "flags": sorted(state.flags),
            "journal": [entry.model_dump(mode="json") for entry in state.journal],
            "supplies": state.supplies,
            "ending": state.ending,
            "run_number": state.run_number,
        }
        _Snapshot.model_validate(payload)
        self._validate_state(state)
        return payload

    def decode_state(self, payload: Mapping[str, Any]) -> AdventureState:
        parsed = _Snapshot.model_validate(dict(payload))
        state = AdventureState(
            party=decode_actor_runtime_state_map(parsed.party),
            location=parsed.location,
            phase=parsed.phase,
            encounter=(
                self._combat.decode_state(parsed.encounter)
                if parsed.encounter is not None
                else None
            ),
            encounter_id=parsed.encounter_id,
            flags=set(parsed.flags),
            journal=parsed.journal,
            supplies=parsed.supplies,
            ending=parsed.ending,
            run_number=parsed.run_number,
        )
        canonical = self.encode_state(state)
        if json.dumps(canonical, sort_keys=True) != json.dumps(dict(payload), sort_keys=True):
            raise ValueError("Adventure state is not canonical")
        return state

    def _validate_state(self, state: AdventureState) -> None:
        if not state.flags <= KNOWN_FLAGS:
            raise ValueError("Unknown adventure flags")
        if {"keeper_helped", "wardens_defeated"} <= state.flags:
            raise ValueError("Keeper passage routes are mutually exclusive")
        if state.location in {"archive", "stair", "beacon", "return"} and not state.flags & {
            "keeper_helped",
            "wardens_defeated",
        }:
            raise ValueError("This location requires resolving the keeper's passage")
        if state.location == "return" and state.phase != "complete":
            raise ValueError("Returning requires a completed adventure")
        if (
            state.location == "beacon"
            and state.phase == "exploration"
            and "lantern_defeated" not in state.flags
        ):
            raise ValueError("Exploring the final chamber requires defeating the lantern")
        if "supplies_taken" in state.flags and "chest_open" not in state.flags:
            raise ValueError("Taking supplies requires opening the chest")
        if "chest_open" in state.flags and not state.flags & {"trap_disarmed", "trap_sprung"}:
            raise ValueError("Opening the chest must resolve its trap")
        if len({entry.id for entry in state.journal}) != len(state.journal):
            raise ValueError("Journal entry IDs must be unique")
        if state.encounter is not None:
            if state.party or state.phase != "combat" or state.encounter_id is None:
                raise ValueError("Combat must be the sole canonical party owner")
            if state.encounter.outcome is not None:
                raise ValueError("Finished combat must transfer the party back to exploration")
            if state.encounter.max_rounds != 20:
                raise ValueError("Adventure encounters are bounded to twenty rounds")
            expected = (
                {"warden_1", "warden_2"}
                if state.encounter_id == "wardens"
                else {"hollow_lantern", "attendant"}
            )
            if set(state.encounter.turn.context.actors) != set(PARTY_IDS) | expected:
                raise ValueError("Unexpected adventure combat roster")
            if state.location != ("hall" if state.encounter_id == "wardens" else "beacon"):
                raise ValueError("Encounter must match its adventure location")
        elif (
            state.phase == "combat"
            or state.encounter_id is not None
            or set(state.party) != set(PARTY_IDS)
        ):
            raise ValueError("Exploration must own exactly the authored party")
        if (state.phase == "complete") != (state.ending is not None):
            raise ValueError("Ending requires a completed adventure")
        if state.phase == "complete" and (
            state.location != "return" or "lantern_defeated" not in state.flags
        ):
            raise ValueError("Ending requires defeating the lantern and returning")
        if state.supplies and "supplies_taken" not in state.flags:
            raise ValueError("Healing supplies require opening the supply chest")
        scene = self._scene(state)
        for actor in self._party(state).values():
            if actor.team != "party" or not 0 <= actor.hp <= actor.max_hp:
                raise ValueError("Invalid adventure party health or team")
            scene.feet_to_grid_cell(
                FeetPosition(x_ft=actor.position[0], y_ft=actor.position[1], z_ft=actor.position[2])
            )

    def preview(
        self, state: AdventureState, command: SessionCommand, rng: random.Random
    ) -> PreviewOutcome:
        raise EngineSessionError(
            "unsupported_command_mode",
            "Adventure preview is disabled; commit a choice to resolve it.",
        )

    def respond_to_reaction(
        self,
        state: AdventureState,
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise EngineSessionError(
            "unsupported_reaction", "Adventure reactions resolve automatically."
        )

    def commit(
        self, state: AdventureState, command: SessionCommand, rng: random.Random
    ) -> EngineTransition:
        if command.mode != "commit":
            raise EngineSessionError(
                "unsupported_command_mode", "Adventure commands require commit mode."
            )
        if command.kind == CHOOSE_COMMAND_KIND:
            if (
                command.actor_id is not None
                or set(command.payload) != {"choice_id"}
                or not isinstance(command.payload["choice_id"], str)
            ):
                raise EngineSessionError(
                    "invalid_command_payload", "Choose exactly one available adventure choice."
                )
            choice_id = command.payload["choice_id"]
            if choice_id not in self._choice_ids(state):
                raise EngineSessionError(
                    "unavailable_choice",
                    "That choice is not available at this point in the adventure.",
                )
            events = [
                EventDraft(
                    kind="adventure.choice.made",
                    payload={
                        "choice_id": choice_id,
                        "location": state.location,
                        "run_number": state.run_number,
                    },
                )
            ]
            if choice_id == "restart":
                fresh = create_initial_state()
                fresh.run_number = state.run_number + 1
                return EngineTransition(state=fresh, events=tuple(events))
            self._choose(state, choice_id, command, rng, events)
            if state.phase == "exploration" and not any(
                _conscious(actor) for actor in state.party.values()
            ):
                state.phase = "defeat"
                _note(
                    state,
                    "defeat",
                    "No one left standing",
                    "The last conscious companion has fallen. Begin a new adventure to try again.",
                )
        elif command.kind == DECLARATION_COMMAND_KIND:
            if state.phase != "combat" or state.encounter is None:
                raise EngineSessionError("not_in_combat", "There is no active adventure combat.")
            if (
                command.actor_id not in PARTY_IDS
                or command.actor_id != state.encounter.turn.actor_id
                or not _conscious(self._party(state)[command.actor_id])
            ):
                raise EngineSessionError(
                    "actor_mismatch", "Only the current conscious companion may take this turn."
                )
            try:
                declaration = TurnDeclarationPayload.model_validate(command.payload).to_domain()
            except ValidationError as exc:
                raise EngineSessionError(
                    "invalid_command_payload", "The turn declaration payload is invalid."
                ) from exc
            for position in declaration.movement_path:
                try:
                    if position[2] != 0:
                        raise ValueError("This adventure uses ground movement")
                    self._scene(state).feet_to_grid_cell(
                        FeetPosition(x_ft=position[0], y_ft=position[1], z_ft=position[2])
                    )
                except ValueError as exc:
                    raise EngineSessionError(
                        "invalid_movement",
                        "Movement must remain inside the current room on the ground.",
                    ) from exc
            actors = dict(state.encounter.turn.context.actors)
            origins = {actor_id: actor.position for actor_id, actor in actors.items()}
            recap_id = f"combat_{state.encounter_id}_{state.encounter.turn.prompt.turn_token}"
            events = list(self._combat.commit(state.encounter, command, rng).events)
            self._advance_enemies(state, command, rng, events)
            self._combat_recap(state, recap_id, command.actor_id, actors, origins, events)
        else:
            raise EngineSessionError("unsupported_command", "Unsupported adventure command.")
        self.encode_state(state)
        return EngineTransition(state=state, events=tuple(events))

    def _choice_ids(self, state: AdventureState) -> list[str]:
        if state.phase in {"complete", "defeat"}:
            return ["restart"]
        if state.phase == "combat":
            return []
        flags = state.flags
        ids: list[str] = []
        if state.location == "landing":
            ids = ["enter_hall"]
        elif state.location == "hall":
            if flags & {"keeper_helped", "wardens_defeated"}:
                ids = ["enter_archive"]
            else:
                if "orin_listened" not in flags:
                    ids.append("listen_orin")
                else:
                    ids.append("offer_help")
                if "beacon_asked" not in flags:
                    ids.append("ask_beacon")
                if "persuasion_attempted" not in flags and _conscious(state.party["sela"]):
                    ids.append("persuade_orin")
                ids.append("threaten_orin")
        elif state.location == "archive":
            if "archive_searched" not in flags:
                ids.append("search_archive")
            elif "account_read" not in flags:
                ids.append("read_account")
            if "chest_open" not in flags:
                if _conscious(state.party["iven"]):
                    if "archive_searched" in flags and not flags & {"trap_disarmed", "trap_sprung"}:
                        ids.append("disarm_trap")
                    if "lock_attempted" not in flags:
                        ids.append("pick_lock")
                if _conscious(state.party["mara"]):
                    ids.append("force_chest")
            elif "supplies_taken" not in flags:
                ids.append("take_supplies")
            ids.append("enter_stair")
        elif state.location == "stair":
            if "rest_used" not in flags:
                ids.append("short_rest")
            ids += ["return_archive", "enter_beacon"]
        elif state.location == "beacon" and "lantern_defeated" in flags:
            ids = ["restore_beacon", "release_spirit"]
        if state.supplies:
            ids += [
                f"heal_{actor_id}"
                for actor_id, actor in self._party(state).items()
                if not actor.dead and actor.hp < actor.max_hp
            ]
        return ids

    @staticmethod
    def _travel(state: AdventureState, destination: str) -> None:
        state.location = destination
        for actor_id, position in zip(PARTY_IDS, PARTY_POSITIONS):
            state.party[actor_id].position = position
            state.party[actor_id].movement_remaining = 0.0

    def _choose(
        self,
        state: AdventureState,
        choice: str,
        command: SessionCommand,
        rng: random.Random,
        events: list[EventDraft],
    ) -> None:
        flags = state.flags
        if choice in {"enter_hall", "enter_archive", "enter_stair", "return_archive"}:
            self._travel(
                state,
                {
                    "enter_hall": "hall",
                    "enter_archive": "archive",
                    "enter_stair": "stair",
                    "return_archive": "archive",
                }[choice],
            )
        elif choice == "listen_orin":
            flags.add("orin_listened")
            _note(
                state,
                "orin",
                "A keeper's fear",
                "Orin admits the light is a bound spirit named Aster. The ward has cracked, and its pain has become the Hollow Lantern. He is guarding the archive because he fears the town will destroy Aster to save itself. He will admit anyone who promises to listen.",
            )
        elif choice == "ask_beacon":
            flags.add("beacon_asked")
            _note(
                state,
                "beacon_history",
                "A century of light",
                "Aster once offered to guide the fishing fleet through a winter storm. The first keeper built a ward to hold that gift. Orin inherited the tower and the silence around its cost. 'I never asked whether the gift had an ending,' he says.",
            )
        elif choice == "offer_help":
            flags.add("keeper_helped")
            _note(
                state,
                "keeper_helped",
                "An open passage",
                "You promise to quiet the broken ward and hear Aster's request. Orin lowers his lantern; the brass wardens step aside. He asks you to search the archive for a silver key and the original keeper's account.",
            )
        elif choice == "persuade_orin":
            flags.add("persuasion_attempted")
            roll = self._check("persuasion", 4, 13, rng, events)
            if roll:
                flags.add("keeper_helped")
                _note(
                    state,
                    "persuasion",
                    "Trust under pressure",
                    "Sela persuades Orin that saving the boats and hearing the spirit can be one task. The wardens stand down. He tells you to search the archive for the silver key.",
                )
            else:
                _note(
                    state,
                    "persuasion",
                    "Not yet convinced",
                    "Sela's appeal fails. Orin tightens his grip on the lantern. He is frightened, not your enemy; listening to his story can still open the passage peacefully.",
                )
        elif choice == "threaten_orin":
            _note(
                state,
                "wardens",
                "Brass against steel",
                "Your demand wakes the wardens' old orders. Orin retreats into the rain while the two constructs block the passage. Defeat them to reach the archive.",
            )
            self._start_combat(state, "wardens", command, rng, events)
        elif choice == "search_archive":
            flags.add("archive_searched")
            _note(
                state,
                "archive",
                "A needle and an old promise",
                "You find a spring-loaded needle inside the chest latch and the first keeper's account beneath a shelf. Iven can disarm the trap, try the lock, or Mara can force it. The account can be read before you leave.",
            )
        elif choice == "read_account":
            flags.add("account_read")
            _note(
                state,
                "account",
                "Until the last boat comes home",
                "Aster's promise was 'until the last boat comes home.' Each generation sent new boats, and no keeper ended the bargain. The silver key can loosen the ward. Restoring it will save tonight's fleet immediately, but bind Aster again. Releasing Aster honors the original promise and leaves the harbor to guide its own boats.",
            )
        elif choice == "disarm_trap":
            if self._check("disarm", 5, 12, rng, events):
                flags.add("trap_disarmed")
                _note(
                    state,
                    "trap",
                    "A quiet click",
                    "Iven catches the needle spring. The chest can now be opened safely.",
                )
            else:
                self._spring_trap(state, "iven", rng, events)
        elif choice in {"pick_lock", "force_chest"}:
            if choice == "pick_lock":
                flags.add("lock_attempted")
                if not self._check("lockpick", 5, 12, rng, events):
                    _note(
                        state,
                        "lock",
                        "A stubborn lock",
                        "The corroded lock defeats Iven's tools. Mara can still force it open; any armed needle trap will spring.",
                    )
                    return
            if not flags & {"trap_disarmed", "trap_sprung"}:
                self._spring_trap(state, "iven" if choice == "pick_lock" else "mara", rng, events)
            flags.add("chest_open")
            _note(
                state,
                "chest",
                "Emergency supplies",
                "The lid opens on two sealed healing draughts and a silver key shaped like a sun. Take them before leaving; the key will weaken the Hollow Lantern's defenses.",
            )
        elif choice == "take_supplies":
            flags.add("supplies_taken")
            state.supplies = 2
            _note(
                state,
                "supplies",
                "The silver key",
                "You take two healing draughts (each restores 2d4 + 4 HP to a living companion) and the silver key. The key reduces the Hollow Lantern's armor class by 2. Draughts can be used between encounters; Sela can heal during combat.",
            )
        elif choice.startswith("heal_"):
            actor = state.party[choice.removeprefix("heal_")]
            amount = rng.randint(1, 4) + rng.randint(1, 4) + 4
            before = actor.hp
            engine_runtime._apply_healing(actor, amount)
            state.supplies -= 1
            _note(
                state,
                f"draught_{2 - state.supplies}",
                "A healing draught",
                f"{actor.name} recovers {actor.hp - before} HP. {state.supplies} draught(s) remain.",
            )
            events.append(
                EventDraft(
                    kind="adventure.healed",
                    payload={
                        "actor_id": actor.actor_id,
                        "amount": actor.hp - before,
                        "rolled": amount,
                    },
                )
            )
        elif choice == "short_rest":
            flags.add("rest_used")
            recovered = []
            for actor in state.party.values():
                if actor.dead:
                    continue
                amount = rng.randint(1, 8) + 3
                before = actor.hp
                engine_runtime._apply_healing(actor, amount)
                recovered.append(f"{actor.name.split(' · ')[0]} +{actor.hp - before} HP")
            for actor_id, resource in (
                ("mara", "resolve"),
                ("mara", "second_wind"),
                ("iven", "focus"),
            ):
                state.party[actor_id].resources[resource] = state.party[actor_id].max_resources[
                    resource
                ]
            _note(
                state,
                "rest",
                "One hour in the dry",
                "; ".join(recovered)
                + ". Mara's resolve and second wind, and Iven's focus return. Sela's remaining light is unchanged. The rising tide leaves no time for another rest.",
            )
        elif choice == "enter_beacon":
            self._travel(state, "beacon")
            _note(
                state,
                "lantern",
                "The broken ward",
                "The Hollow Lantern lashes out. Quiet it and its attendant to hear Aster."
                + (
                    " The silver key loosens its armor (AC 12 instead of 14)."
                    if "supplies_taken" in flags
                    else " Without the silver key, the ward still shields it (AC 14)."
                ),
            )
            self._start_combat(state, "lantern", command, rng, events)
        elif choice in {"restore_beacon", "release_spirit"}:
            state.ending = choice
            state.phase = "complete"
            self._travel(state, "return")
            ending = self._ending(state)
            _note(state, "ending", ending["title"], ending["text"])

    @staticmethod
    def _check(
        check: str, modifier: int, dc: int, rng: random.Random, events: list[EventDraft]
    ) -> bool:
        face = rng.randint(1, 20)
        success = face + modifier >= dc
        events.append(
            EventDraft(
                kind="adventure.check.resolved",
                payload={
                    "check": check,
                    "face": face,
                    "modifier": modifier,
                    "dc": dc,
                    "success": success,
                },
            )
        )
        return success

    @staticmethod
    def _spring_trap(
        state: AdventureState, actor_id: str, rng: random.Random, events: list[EventDraft]
    ) -> None:
        state.flags.add("trap_sprung")
        damage = rng.randint(1, 6) + 2
        actor = state.party[actor_id]
        # This bounded trap cannot kill a companion outright. Downed companions
        # can be treated with supplies or the one short rest outside combat.
        actor.hp = max(0, actor.hp - damage)
        if actor.hp == 0:
            actor.stable = True
            actor.update_manual_conditions(
                set(actor.intrinsic_conditions) | {"unconscious", "incapacitated", "prone"}
            )
        _note(
            state,
            "trap",
            "The needle springs",
            f"{actor.name} takes {damage} piercing damage. The spring is spent; the chest is now safe to handle.",
        )
        events.append(
            EventDraft(
                kind="adventure.trap.resolved", payload={"actor_id": actor_id, "damage": damage}
            )
        )

    def _start_combat(
        self,
        state: AdventureState,
        encounter_id: str,
        command: SessionCommand,
        rng: random.Random,
        events: list[EventDraft],
    ) -> None:
        actors = dict(state.party)
        actors.update(create_enemies(encounter_id, silver_key="supplies_taken" in state.flags))
        order = list(PARTY_IDS) + [actor_id for actor_id in actors if actor_id not in PARTY_IDS]
        context = CombatTurnContext(
            actors=actors,
            initiative_order=order,
            round_number=1,
            damage_dealt={key: 0 for key in actors},
            damage_taken={key: 0 for key in actors},
            threat_scores={key: 0 for key in actors},
            resources_spent={key: {} for key in actors},
            active_hazards=[],
            telemetry=[],
            rule_trace=[],
            obstacles=[],
            light_level="bright",
            burst_round_threshold=3,
            strategy_overrides={},
            timing_engine=engine_runtime._create_combat_timing_engine(),
        )
        state.encounter = DndCombatEncounterState(
            turn=DndCombatTurnState(context=context, actor_id=order[0]), max_rounds=20
        )
        state.party = {}
        state.encounter_id = encounter_id
        state.phase = "combat"
        start = command.model_copy(
            update={
                "mode": "admin",
                "actor_id": None,
                "kind": START_ENCOUNTER_COMMAND_KIND,
                "payload": {},
            }
        )
        events.extend(self._combat.commit(state.encounter, start, rng).events)
        self._advance_enemies(state, command, rng, events)

    def _advance_enemies(
        self,
        state: AdventureState,
        command: SessionCommand,
        rng: random.Random,
        events: list[EventDraft],
    ) -> None:
        encounter = state.encounter
        assert encounter is not None
        for _ in range(200):
            if encounter.outcome is not None:
                self._finish_combat(state, events)
                return
            prompt = encounter.turn.prompt
            if prompt is None:
                raise RuntimeError("Combat must stop at a declaration prompt")
            if prompt.actor_id in PARTY_IDS:
                return
            declaration = self._enemy_declaration(prompt)
            enemy_command = command.model_copy(
                update={
                    "mode": "commit",
                    "actor_id": prompt.actor_id,
                    "kind": DECLARATION_COMMAND_KIND,
                    "payload": TurnDeclarationPayload.from_domain(declaration).model_dump(
                        mode="json"
                    ),
                }
            )
            events.extend(self._combat.commit(encounter, enemy_command, rng).events)
        raise RuntimeError("Adventure enemy automation exceeded its finite turn bound")

    @staticmethod
    def _enemy_declaration(prompt: CombatTurnPrompt) -> TurnDeclaration:
        declaration = (
            BaseStrategy().declare_turn(prompt.actor_view, prompt.state_view) or TurnDeclaration()
        )
        if (
            declaration.action is None
            and declaration.rationale.get("reason") == "target_out_of_reach"
        ):
            target = prompt.state_view.actors[declaration.rationale["target"]]
            origin = prompt.actor_view.position
            distance = max(abs(end - start) for start, end in zip(origin, target.position))
            amount = min(prompt.actor_view.movement_remaining, max(0.0, distance - 5.0))
            if amount > 0:
                destination = tuple(
                    start + max(-amount, min(amount, end - start))
                    for start, end in zip(origin, target.position)
                )
                declaration.movement_path = [origin, destination]
        if declaration.movement_path and declaration.action and declaration.action.targets:
            # BaseStrategy plans with Euclidean interpolation, which stops short
            # of melee reach on diagonal square-grid approaches. Use the same
            # target and action, ending on the nearest reachable grid line.
            target = prompt.state_view.actors[declaration.action.targets[0].actor_id]
            action = next(
                item
                for item in prompt.state_view.metadata["action_catalog"][prompt.actor_id]
                if item["name"] == declaration.action.action_name
            )
            reach = (
                action.get("reach_ft")
                or action.get("range_normal_ft")
                or action.get("range_ft")
                or 5
            )
            origin = prompt.actor_view.position
            destination = tuple(
                end - max(-reach, min(reach, end - start))
                for start, end in zip(origin, target.position)
            )
            declaration.movement_path = [origin, destination]
        return declaration

    @staticmethod
    def _combat_recap(
        state: AdventureState,
        recap_id: str,
        actor_id: str,
        actors: dict[str, ActorRuntimeState],
        origins: dict[str, tuple[float, float, float]],
        events: list[EventDraft],
    ) -> None:
        """Keep a small readable journal from committed facts, never predictions."""
        lines = []
        for event in events:
            if event.kind != "dnd.roll.recorded.v1":
                continue
            record = event.payload["record"]
            fact = record["fact"]
            source = actors.get(record["source_actor_id"])
            target = actors.get(record["target_actor_id"])
            source_name = source.name.split(" · ")[0] if source else "The chamber"
            target_name = target.name.split(" · ")[0] if target else source_name
            if fact["kind"] == "damage":
                lines.append(
                    f"{source_name} deals {fact['applied_damage']} {fact['damage_type']} damage to {target_name}."
                )
            elif fact["kind"] == "healing":
                lines.append(
                    f"{source_name} restores {fact['effective_healing']} HP to {target_name}."
                )
            elif (
                fact["kind"] == "d20"
                and record["purpose"] == "attack"
                and fact["outcome"] == "miss"
            ):
                lines.append(f"{source_name} misses {target_name}.")
        for entry_id, actor in actors.items():
            if actor.position != origins[entry_id]:
                lines.append(f"{actor.name.split(' · ')[0]} advances across the chamber.")
        if not lines:
            lines.append(
                f"{actors[actor_id].name.split(' · ')[0]} holds position. The battle continues."
            )
        _note(
            state,
            recap_id,
            "Combat · " + actors[actor_id].name.split(" · ")[0],
            " ".join(lines)[:1200],
        )
        combat_ids = [entry.id for entry in state.journal if entry.id.startswith("combat_")]
        expired = set(combat_ids[:-8])
        state.journal = [entry for entry in state.journal if entry.id not in expired]

    def _finish_combat(self, state: AdventureState, events: list[EventDraft]) -> None:
        encounter = state.encounter
        assert encounter is not None
        outcome = encounter.outcome
        encounter_id = state.encounter_id
        state.party = self._party(state)
        state.encounter = None
        state.encounter_id = None
        if outcome == "party_victory":
            state.phase = "exploration"
            if encounter_id == "wardens":
                state.flags.add("wardens_defeated")
                _note(
                    state,
                    "wardens_done",
                    "The hall falls quiet",
                    "The brass wardens collapse. Orin has fled, leaving the passage open and his trust broken. Your wounds and spent abilities carry into the archive.",
                )
            else:
                state.flags.add("lantern_defeated")
                _note(
                    state,
                    "aster",
                    "Aster's request",
                    "The hollow shell breaks. Aster stands inside the lens, small as a candle. 'I said I would bring them home. I never said I would stay forever.' You can restore the beacon and save tonight's fleet immediately, or free Aster and ask the harbor to guide its own boats. Both choices carry a cost.",
                )
        else:
            state.phase = "defeat"
            _note(
                state,
                "defeat",
                "The light goes out",
                "The party cannot continue. "
                + (
                    "The tide rises while the battle drags on."
                    if outcome == "timeout"
                    else "The tower falls quiet around your fallen companions."
                )
                + " Begin a new adventure to try another approach.",
            )
        events.append(
            EventDraft(
                kind="adventure.encounter.finished",
                payload={"encounter_id": encounter_id, "outcome": outcome},
            )
        )

    @staticmethod
    def _ending(state: AdventureState) -> dict[str, str] | None:
        if state.ending is None:
            return None
        peace = (
            "Orin returns to help keep your promise."
            if "keeper_helped" in state.flags
            else "Orin stays away; rebuilding the keeper's trust will take longer than repairing brass."
        )
        knowledge = (
            "The account you read becomes evidence of the bargain's true terms."
            if "account_read" in state.flags
            else "The keeper's unread account waits for someone to tell the whole story."
        )
        if state.ending == "restore_beacon":
            return {
                "title": "A Light Borrowed",
                "text": "The beacon burns. Every boat finds the harbor, and Aster remains bound for one more night. Sela asks the town to build a light that needs no captive spirit; Mara and Iven volunteer to begin. Your promise is a debt, not a victory over Aster. "
                + peace
                + " "
                + knowledge,
            }
        return {
            "title": "The Last Boat Comes Home",
            "text": "You turn the key and open the ward. Aster rises through the lens into the dawn. Without the beacon, Mara lights the harbor braziers and Iven rings the fog bell; the fleet returns late, with one empty boat towed behind its rescued crew. The town survives by its own hands. "
            + peace
            + " "
            + knowledge,
        }

    def project_state(self, state: AdventureState) -> dict[str, Any]:
        choices = []
        for choice in self._choice_ids(state):
            if choice.startswith("heal_"):
                actor = self._party(state)[choice.removeprefix("heal_")]
                label, description = (
                    f"Give a draught to {actor.name.split(' · ')[0]}",
                    f"Restore 2d4 + 4 HP ({actor.hp}/{actor.max_hp} HP now). Uses one supply.",
                )
            else:
                label, description = CHOICES[choice]
            choices.append({"id": choice, "label": label, "description": description})
        dialogue = None
        if state.location == "hall" and state.phase == "exploration":
            if "keeper_helped" in state.flags:
                dialogue = {
                    "speaker": "Keeper Orin",
                    "text": "Find the silver key in the archive. Quiet the broken ward, and then listen. Please.",
                }
            elif "wardens_defeated" in state.flags:
                dialogue = {
                    "speaker": "Mara Vale",
                    "text": "The passage is open. I wish that had gone differently. Keep moving.",
                }
            else:
                dialogue = {
                    "speaker": "Keeper Orin",
                    "text": (
                        "Aster is frightened. I will let you pass if you promise to hear what the spirit asks."
                        if "orin_listened" in state.flags
                        else "You came for the light. Did anyone send you for the one inside it?"
                    ),
                }
        elif state.location == "beacon" and "lantern_defeated" in state.flags:
            dialogue = {
                "speaker": "Aster",
                "text": "Until the last boat comes home. That was my promise. Every year you built more boats. Will you let it be enough?",
            }
        inventory = []
        if "supplies_taken" in state.flags:
            inventory.append(
                {
                    "id": "silver_key",
                    "name": "Silver sun key",
                    "quantity": 1,
                    "description": "Loosens the Hollow Lantern's ward: its AC is reduced by 2.",
                }
            )
        if state.supplies:
            inventory.append(
                {
                    "id": "healing_draught",
                    "name": "Healing draught",
                    "quantity": state.supplies,
                    "description": "Restores 2d4 + 4 HP to one living companion outside combat.",
                }
            )
        objectives = {
            "landing": "Reach Keeper Orin beneath the failing beacon.",
            "hall": "Find a way past the keeper's wardens.",
            "archive": "Discover the old promise and recover supplies.",
            "stair": "Prepare your companions, then enter the beacon chamber.",
            "beacon": "Quiet the Hollow Lantern and its attendant.",
            "return": "Your choice has changed the harbor.",
        }
        objective = objectives[state.location]
        if "lantern_defeated" in state.flags and state.phase == "exploration":
            objective = "Decide whether to restore the beacon or release Aster."
        if state.phase == "defeat":
            objective = "The party has fallen. Begin a new adventure to try again."
        return {
            "title": "The Lantern Below",
            "subtitle": "An original adventure for three companions · about 30 minutes",
            "phase": state.phase,
            "location": {
                "id": state.location,
                "name": LOCATIONS[state.location][0],
                "description": LOCATIONS[state.location][1],
            },
            "scene": self._scene(state).model_dump(mode="json"),
            "party": [
                DndCombatTurnDriver.project_actor(actor) for actor in self._party(state).values()
            ],
            "combat": self._combat.project_state(state.encounter) if state.encounter else None,
            "choices": choices,
            "journal": [entry.model_dump(mode="json") for entry in state.journal],
            "inventory": inventory,
            "objective": objective,
            "dialogue": dialogue,
            "ending": self._ending(state),
        }
