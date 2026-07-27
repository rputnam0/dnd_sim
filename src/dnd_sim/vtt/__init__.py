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
from .scene import (
    SCENE_PROJECTION_SCHEMA_VERSION,
    SCENE_SCHEMA_VERSION,
    FeetPosition,
    GridCell,
    GridPixelTransform,
    PixelPoint,
    SceneProjection,
    SceneToken,
    SquareGridScene,
    project_scene,
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
    "SCENE_PROJECTION_SCHEMA_VERSION",
    "SCENE_SCHEMA_VERSION",
    "FeetPosition",
    "GridCell",
    "GridPixelTransform",
    "PixelPoint",
    "SceneProjection",
    "SceneToken",
    "SquareGridScene",
    "project_scene",
]
