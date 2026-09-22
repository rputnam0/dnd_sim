"""Authenticated HTTP transport for durable VTT map image assets."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, Self

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from .access import TableAccessPolicy
from .map_asset_contracts import (
    MapAssetCatalogView,
    MapAssetRecord,
    MapAssetUploadCommand,
)
from .map_asset_store import (
    SQLiteMapAssetStore,
    MapAssetCommandConflictError,
    MapAssetIdConflictError,
    MapAssetInvalidImageError,
    MapAssetNotFoundError,
    MapAssetRevisionConflictError,
    MapAssetStoreCorruptionError,
    MapAssetStoreError,
    MapAssetStoreSchemaError,
)
from .participants import TableParticipant
from .scene_library_store import (
    SQLiteSceneLibrary,
    SceneLibraryStoreCorruptionError,
    SceneLibraryStoreError,
    SceneLibraryStoreSchemaError,
)

VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION = "vtt.map_asset_upload_request.v1"
VTT_MAP_ASSET_UPLOAD_RESPONSE_SCHEMA_VERSION = "vtt.map_asset_upload_response.v1"

MAP_ASSET_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/map-assets"),
        ("POST", "/api/v1/map-assets"),
    }
)
MAP_ASSET_PROTECTED_ROUTE_PREFIXES = frozenset(
    {
        ("GET", "/api/v1/map-assets/"),
    }
)


class _StrictMapAssetHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


class MapAssetUploadRequest(_StrictMapAssetHTTPModel):
    schema_version: Literal[VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION] = (
        VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: MapAssetUploadCommand

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class MapAssetUploadResponse(_StrictMapAssetHTTPModel):
    schema_version: Literal[VTT_MAP_ASSET_UPLOAD_RESPONSE_SCHEMA_VERSION] = (
        VTT_MAP_ASSET_UPLOAD_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    table_id: str
    command_id: str
    revision: int
    replayed: bool
    asset: MapAssetRecord

    @field_validator("session_id", "table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if type(value) is not int or value < 1:
            raise ValueError("revision must be a positive integer")
        return value

    @field_validator("replayed", mode="before")
    @classmethod
    def validate_replayed(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("replayed must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_asset_identity(self) -> Self:
        if self.asset.reference.asset_id not in self.asset.reference.content_path:
            raise ValueError("asset response content path must match its asset identity")
        return self


class MapAssetAPIError(RuntimeError):
    """Stable map asset transport failure rendered by the parent VTT app."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = {} if details is None else dict(details)


def _request_participant(
    request: Request,
    *,
    access_policy: TableAccessPolicy | None,
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected map asset request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected map asset request has a noncanonical principal")
    return participant


def _storage_error(exc: Exception) -> MapAssetAPIError:
    if isinstance(
        exc,
        (
            MapAssetStoreCorruptionError,
            MapAssetStoreSchemaError,
            SceneLibraryStoreCorruptionError,
            SceneLibraryStoreSchemaError,
        ),
    ):
        return MapAssetAPIError(
            status_code=500,
            code="map_asset_store_corrupt",
            message="The map asset catalog contains invalid durable data.",
        )
    return MapAssetAPIError(
        status_code=503,
        code="map_asset_storage_unavailable",
        message="The map asset catalog could not be persisted or read.",
    )


def _catalog(store: SQLiteMapAssetStore, *, table_id: str) -> MapAssetCatalogView:
    try:
        return store.catalog(table_id)
    except (
        sqlite3.Error,
        MapAssetStoreError,
    ) as exc:
        raise _storage_error(exc) from exc


def _active_asset_id(
    scenes: SQLiteSceneLibrary,
    *,
    table_id: str,
) -> str | None:
    try:
        view = scenes.snapshot(table_id)
    except (
        sqlite3.Error,
        SceneLibraryStoreError,
    ) as exc:
        raise _storage_error(exc) from exc
    if view.active_scene_id is None:
        return None
    active = view.scene(view.active_scene_id)
    if active is None or active.archived:
        raise MapAssetAPIError(
            status_code=500,
            code="map_asset_store_corrupt",
            message="The active scene has invalid durable data.",
        )
    asset = active.scene.map_metadata.asset
    return None if asset is None else asset.asset_id


def _visible_catalog(
    catalog: MapAssetCatalogView,
    *,
    participant: TableParticipant | None,
    scenes: SQLiteSceneLibrary,
) -> MapAssetCatalogView:
    if participant is None or participant.role == "gm":
        return catalog
    active_asset_id = _active_asset_id(scenes, table_id=catalog.table_id)
    assets = tuple(asset for asset in catalog.assets if asset.reference.asset_id == active_asset_id)
    return MapAssetCatalogView(
        table_id=catalog.table_id,
        revision=catalog.revision,
        assets=assets,
    )


def install_map_asset_routes(
    app: FastAPI,
    *,
    store: SQLiteMapAssetStore,
    scenes: SQLiteSceneLibrary,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
) -> None:
    """Install map asset routes on an already-authenticated VTT application."""

    @app.get("/api/v1/map-assets", response_model=MapAssetCatalogView)
    async def get_map_assets(request: Request) -> MapAssetCatalogView:
        participant = _request_participant(request, access_policy=access_policy)
        return _visible_catalog(
            _catalog(store, table_id=table_id),
            participant=participant,
            scenes=scenes,
        )

    @app.post("/api/v1/map-assets", response_model=MapAssetUploadResponse)
    async def upload_map_asset(
        body: MapAssetUploadRequest,
        request: Request,
    ) -> MapAssetUploadResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            raise MapAssetAPIError(
                status_code=403,
                code="map_asset_forbidden",
                message="This participant is not permitted to upload map assets.",
            )
        if body.session_id != session_id or body.command.table_id != table_id:
            raise MapAssetAPIError(
                status_code=409,
                code="map_asset_binding_mismatch",
                message="The map asset request belongs to a different table or session.",
                details={
                    "expected_session_id": session_id,
                    "expected_table_id": table_id,
                },
            )
        try:
            result = store.execute(body.command)
        except MapAssetRevisionConflictError as exc:
            raise MapAssetAPIError(
                status_code=409,
                code="map_asset_stale_revision",
                message="The map asset upload targets a stale catalog revision.",
                details={"current_revision": exc.current_revision},
            ) from exc
        except MapAssetCommandConflictError as exc:
            raise MapAssetAPIError(
                status_code=409,
                code="map_asset_command_conflict",
                message="The map asset command ID was already used with different content.",
            ) from exc
        except MapAssetIdConflictError as exc:
            raise MapAssetAPIError(
                status_code=409,
                code="map_asset_id_conflict",
                message="The map asset ID was already used.",
            ) from exc
        except MapAssetInvalidImageError as exc:
            raise MapAssetAPIError(
                status_code=422,
                code="map_asset_invalid_image",
                message=str(exc),
            ) from exc
        except (MapAssetStoreCorruptionError, MapAssetStoreSchemaError) as exc:
            raise _storage_error(exc) from exc
        except (sqlite3.Error, MapAssetStoreError) as exc:
            raise _storage_error(exc) from exc
        receipt = result.receipt
        return MapAssetUploadResponse(
            session_id=session_id,
            table_id=receipt.table_id,
            command_id=receipt.command_id,
            revision=receipt.revision,
            replayed=result.replayed,
            asset=receipt.asset,
        )

    @app.get("/api/v1/map-assets/{asset_id}/content.{extension}")
    async def get_map_asset_content(
        asset_id: str,
        extension: str,
        request: Request,
    ) -> Response:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            active_asset_id = _active_asset_id(scenes, table_id=table_id)
            if active_asset_id != asset_id:
                raise MapAssetAPIError(
                    status_code=404,
                    code="map_asset_not_found",
                    message="The requested map asset is unavailable.",
                )
        try:
            record, content = store.content(table_id, asset_id)
        except MapAssetNotFoundError as exc:
            raise MapAssetAPIError(
                status_code=404,
                code="map_asset_not_found",
                message="The requested map asset is unavailable.",
            ) from exc
        except (MapAssetStoreCorruptionError, MapAssetStoreSchemaError) as exc:
            raise _storage_error(exc) from exc
        except (sqlite3.Error, MapAssetStoreError) as exc:
            raise _storage_error(exc) from exc
        expected_extension = record.reference.content_path.rsplit(".", 1)[-1]
        if extension != expected_extension:
            raise MapAssetAPIError(
                status_code=404,
                code="map_asset_not_found",
                message="The requested map asset is unavailable.",
            )
        return Response(
            content=content,
            media_type=record.reference.media_type,
            headers={
                "Cache-Control": "private, max-age=3600, immutable",
                "ETag": f'"{record.reference.sha256}"',
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )
