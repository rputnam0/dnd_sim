"""Transport-independent persistence and contracts for the future VTT runtime."""

from .event_store import (
    EVENT_STORE_SCHEMA_VERSION,
    AppendCommitResult,
    CommandConflictError,
    EventStoreError,
    EventStoreSchemaError,
    SQLiteSessionEventStore,
    StoredCommand,
    StoredSessionSnapshot,
)

__all__ = [
    "EVENT_STORE_SCHEMA_VERSION",
    "AppendCommitResult",
    "CommandConflictError",
    "EventStoreError",
    "EventStoreSchemaError",
    "SQLiteSessionEventStore",
    "StoredCommand",
    "StoredSessionSnapshot",
]
