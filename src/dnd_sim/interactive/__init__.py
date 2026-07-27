"""Deterministic command/event contracts for interactive engine sessions."""

from .contracts import (
    COMMAND_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    REACTION_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    RNG_ALGORITHM,
    SNAPSHOT_SCHEMA_VERSION,
    CommandReceipt,
    CommandRecord,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PendingReactionDraft,
    PreviewOutcome,
    PreviewReceipt,
    SessionCommand,
    SessionEvent,
    SessionSnapshot,
)
from .dnd_contracts import DECLARATION_COMMAND_KIND, TurnDeclarationPayload
from .dnd_state_codec import (
    ActorStateCodecError,
    decode_actor_runtime_state,
    decode_actor_runtime_state_map,
    encode_actor_runtime_state,
    encode_actor_runtime_state_map,
)
from .dnd_turn_driver import (
    DND_TURN_STATE_SCHEMA_VERSION,
    DndCombatTurnDriver,
    DndCombatTurnState,
)
from .session import EngineSession, EngineSessionDriver, EngineSessionError, EngineTransition

__all__ = [
    "ActorStateCodecError",
    "COMMAND_SCHEMA_VERSION",
    "DECLARATION_COMMAND_KIND",
    "DND_TURN_STATE_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "REACTION_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "RNG_ALGORITHM",
    "SNAPSHOT_SCHEMA_VERSION",
    "CommandReceipt",
    "CommandRecord",
    "DndCombatTurnDriver",
    "DndCombatTurnState",
    "EngineSession",
    "EngineSessionDriver",
    "EngineSessionError",
    "EngineTransition",
    "EngineVersionPins",
    "EventDraft",
    "PendingReaction",
    "PendingReactionDraft",
    "PreviewOutcome",
    "PreviewReceipt",
    "SessionCommand",
    "SessionEvent",
    "SessionSnapshot",
    "TurnDeclarationPayload",
    "decode_actor_runtime_state",
    "decode_actor_runtime_state_map",
    "encode_actor_runtime_state",
    "encode_actor_runtime_state_map",
]
