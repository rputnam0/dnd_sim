"""Transport contracts and durable single-session ownership for the VTT runtime."""

from typing import TYPE_CHECKING, Any

from .contracts import (
    VTT_COMMAND_SCHEMA_VERSION,
    VTT_COMMIT_RESPONSE_SCHEMA_VERSION,
    VTT_EVENT_DRAFT_SCHEMA_VERSION,
    VTT_EVENT_SCHEMA_VERSION,
    VTT_PREVIEW_RESPONSE_SCHEMA_VERSION,
    VTT_VERSION_INFO_SCHEMA_VERSION,
    VTTCommand,
    VTTCommitResponse,
    VTTEvent,
    VTTEventDraft,
    VTTPreviewResponse,
    VTTResponse,
    VTTVersionInfo,
)

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
from .http_api import (
    DEFAULT_VTT_ALLOWED_ORIGINS,
    VTT_ERROR_SCHEMA_VERSION,
    VTT_SESSION_VIEW_SCHEMA_VERSION,
    VTTError,
    VTTSessionView,
    create_vtt_app,
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
from .session_service import VTTSessionReadView, VTTSessionService, VTTSessionServiceError
from .solo_table import (
    SOLO_TABLE_CONTENT_VERSION,
    SOLO_TABLE_ENGINE_VERSION,
    SOLO_TABLE_MAX_ROUNDS,
    SOLO_TABLE_RULES_VERSION,
    SOLO_TABLE_SEED,
    SoloTableFixture,
    build_solo_table_fixture,
)

if TYPE_CHECKING:
    from .solo_app import create_solo_table_app


def __getattr__(name: str) -> Any:
    if name == "create_solo_table_app":
        from .solo_app import create_solo_table_app

        return create_solo_table_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EVENT_STORE_SCHEMA_VERSION",
    "DEFAULT_VTT_ALLOWED_ORIGINS",
    "VTT_COMMAND_SCHEMA_VERSION",
    "VTT_COMMIT_RESPONSE_SCHEMA_VERSION",
    "VTT_EVENT_DRAFT_SCHEMA_VERSION",
    "VTT_EVENT_SCHEMA_VERSION",
    "VTT_ERROR_SCHEMA_VERSION",
    "VTT_PREVIEW_RESPONSE_SCHEMA_VERSION",
    "VTT_SESSION_VIEW_SCHEMA_VERSION",
    "VTT_VERSION_INFO_SCHEMA_VERSION",
    "AppendCommitResult",
    "CommandConflictError",
    "EventStoreError",
    "EventStoreSchemaError",
    "SQLiteSessionEventStore",
    "StoredCommand",
    "StoredSessionSnapshot",
    "SCENE_PROJECTION_SCHEMA_VERSION",
    "SCENE_SCHEMA_VERSION",
    "SOLO_TABLE_CONTENT_VERSION",
    "SOLO_TABLE_ENGINE_VERSION",
    "SOLO_TABLE_MAX_ROUNDS",
    "SOLO_TABLE_RULES_VERSION",
    "SOLO_TABLE_SEED",
    "FeetPosition",
    "GridCell",
    "GridPixelTransform",
    "PixelPoint",
    "SceneProjection",
    "SceneToken",
    "SquareGridScene",
    "SoloTableFixture",
    "VTTCommand",
    "VTTCommitResponse",
    "VTTEvent",
    "VTTEventDraft",
    "VTTError",
    "VTTPreviewResponse",
    "VTTResponse",
    "VTTSessionReadView",
    "VTTSessionService",
    "VTTSessionServiceError",
    "VTTSessionView",
    "VTTVersionInfo",
    "build_solo_table_fixture",
    "create_solo_table_app",
    "create_vtt_app",
    "project_scene",
]
