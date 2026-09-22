"""Explicit, fail-closed provisioning of durable, encounter-free world workspaces."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.exceptions import HTTPException
from starlette.types import Receive, Scope, Send

from .access import TableAccessPolicy
from .http_api import VTTTableView
from .installation_api import _bearer, _error
from .installation_api_contracts import WorldLaunchResponse
from .installation_contracts import AdminPublic
from .installation_store import AuthenticationError, InstallationStoreError, SQLiteInstallationStore
from .map_asset_api import MapAssetAPIError, install_map_asset_routes
from .map_asset_store import MAP_ASSET_STORE_SCHEMA_VERSION, MapAssetStoreError, SQLiteMapAssetStore
from .participants import TableParticipant, TableRoster
from .scene_library_api import SceneLibraryAPIError, install_scene_library_routes
from .scene_library_store import (
    SCENE_LIBRARY_STORE_SCHEMA_VERSION,
    SceneLibraryStoreError,
    SQLiteSceneLibrary,
)
from .world_catalog_contracts import WorldArchiveCommand, WorldRecord
from .world_catalog_store import (
    SQLiteWorldCatalog,
    WorldArchivedError,
    WorldCatalogStoreError,
    WorldNotFoundError,
)

MAX_WORLD_LAUNCHES = 64
_REGISTRY = "_vtt_world_preparation_registry"
_RECEIPT = "_vtt_world_preparation_receipt"
_TABLES = {
    _RECEIPT,
    "_vtt_scene_library_store_metadata",
    "_vtt_scene_library_event_log",
    "_vtt_map_asset_store_metadata",
    "_vtt_map_asset",
    "_vtt_map_asset_command_log",
}


class WorldPreparationError(WorldCatalogStoreError):
    """A world needs operator recovery; never repair it by opening it."""


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["vtt.world_preparation.v1"] = "vtt.world_preparation.v1"
    state: Literal["complete"] = "complete"
    world_id: str
    table_id: str
    session_id: str
    initial_gm: TableParticipant
    initial_scene_revision: Literal[0] = 0
    initial_map_asset_revision: Literal[0] = 0
    schema_digest: str


@dataclass(eq=False)
class _Resource:
    connection: sqlite3.Connection
    receipt: _Receipt
    app: FastAPI
    requests: int = 0
    retiring: bool = False

    def table(self) -> VTTTableView:
        return VTTTableView(
            access_mode="protected",
            table_id=self.receipt.table_id,
            current_participant=self.receipt.initial_gm,
            participants=(self.receipt.initial_gm,),
        )


@dataclass
class _Launch:
    resource: _Resource
    admin_bearer: str = field(repr=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _schema_digest(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    return _digest(json.dumps(rows, separators=(",", ":")))


class WorldPreparationManager:
    """Own bounded launch capabilities and SQLite resources, never engine state.

    The installation registry reserves provisioning before creating any bytes.
    A completed receipt binds the world, empty-store revisions, schema, and GM.
    Missing/partial files or receipts cannot be mistaken for a first launch.
    """

    def __init__(
        self,
        *,
        database_path: Path,
        registry_connection: sqlite3.Connection,
        installation: SQLiteInstallationStore,
        catalog: SQLiteWorldCatalog,
        lock: RLock,
    ) -> None:
        self._directory = database_path.resolve().with_name(database_path.name + ".worlds")
        self._registry = registry_connection
        self._installation = installation
        self._catalog = catalog
        self._lock = lock
        self._launches: dict[str, _Launch] = {}
        self._resources: dict[str, _Resource] = {}
        self._owned: set[_Resource] = set()
        self._closed = False
        self._registry.execute(
            f"CREATE TABLE IF NOT EXISTS {_REGISTRY} (world_id TEXT PRIMARY KEY, table_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, receipt_digest TEXT)"
        )
        self._registry.commit()

    @property
    def open_resource_count(self) -> int:
        return len(self._owned)

    def database_path(self, world_id: str) -> Path:
        # Only a validated server catalog identity may reach this path builder.
        WorldArchiveCommand.validate_world_id(world_id)
        return self._directory / (world_id + ".sqlite")

    def _world(self, world_id: str) -> WorldRecord:
        entry = self._catalog.snapshot().world(world_id)
        if entry is None:
            raise WorldNotFoundError("world unavailable")
        if entry.archived:
            raise WorldArchivedError("world unavailable")
        return entry.world

    def launch(
        self, world_id: str, *, admin_bearer: str, admin: AdminPublic
    ) -> WorldLaunchResponse:
        with self._lock:
            if self._closed:
                raise WorldPreparationError("manager closed")
            self._installation.authenticate_session(admin_bearer)
            world = self._world(world_id)
            self.prune()
            if len(self._launches) >= MAX_WORLD_LAUNCHES or len(self._owned) >= MAX_WORLD_LAUNCHES:
                raise WorldPreparationError("launch capacity unavailable")
            resource = self._resources.get(world_id)
            if resource is None:
                resource = self._open(world, admin)
                self._resources[world_id] = resource
                self._owned.add(resource)
            else:
                self._validate(resource.connection, world)
            if resource.receipt.initial_gm.participant_id != admin.admin_id:
                raise AuthenticationError("world authority unavailable")
            token = secrets.token_urlsafe(32)
            self._launches[_digest(token)] = _Launch(resource, admin_bearer)
            return WorldLaunchResponse(
                world=world,
                session_id=resource.receipt.session_id,
                table=resource.table(),
                workspace_api_path="/api/v1/worlds/" + world_id,
                bearer_token=token,
            )

    def _open(self, world: WorldRecord, admin: AdminPublic) -> _Resource:
        connection = None
        try:
            path = self.database_path(world.world_id)
            row = self._registry.execute(
                f"SELECT state FROM {_REGISTRY} WHERE world_id = ?", (world.world_id,)
            ).fetchone()
            fresh = row is None and not path.exists()
            if fresh:
                self._registry.execute(
                    f"INSERT INTO {_REGISTRY} VALUES (?, ?, 'preparing', NULL)",
                    (world.world_id, world.table_id),
                )
                self._registry.commit()
                self._directory.mkdir(parents=True, exist_ok=True)
                with path.open("xb"):
                    pass
            elif row is None or row[0] != "complete" or not path.is_file():
                raise WorldPreparationError("world provisioning incomplete")
            connection = sqlite3.connect(
                path.as_uri() + "?mode=rw", uri=True, timeout=30.0, check_same_thread=False
            )
            if fresh:
                scenes = SQLiteSceneLibrary(connection)
                assets = SQLiteMapAssetStore(connection)
                connection.execute(
                    f"CREATE TABLE {_RECEIPT} (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), receipt_json TEXT NOT NULL)"
                )
                connection.commit()
                if (
                    scenes.snapshot(world.table_id).revision != 0
                    or assets.catalog(world.table_id).revision != 0
                ):
                    raise WorldPreparationError("world stores are not empty")
                receipt = _Receipt(
                    world_id=world.world_id,
                    table_id=world.table_id,
                    session_id="workspace_" + secrets.token_urlsafe(24),
                    initial_gm=TableParticipant(
                        schema_version="vtt.participant.v1",
                        participant_id=admin.admin_id,
                        display_name=admin.display_name,
                        role="gm",
                    ),
                    schema_digest=_schema_digest(connection),
                )
                encoded = receipt.model_dump_json()
                connection.execute(f"INSERT INTO {_RECEIPT} VALUES (1, ?)", (encoded,))
                connection.commit()
                self._registry.execute(
                    f"UPDATE {_REGISTRY} SET state = 'complete', receipt_digest = ? WHERE world_id = ?",
                    (_digest(encoded), world.world_id),
                )
                self._registry.commit()
            receipt = self._validate(connection, world)
            if receipt.initial_gm.participant_id != admin.admin_id:
                raise AuthenticationError("world authority unavailable")
            scenes = SQLiteSceneLibrary(connection, initialize=False)
            assets = SQLiteMapAssetStore(connection, initialize=False)
            roster = TableRoster(
                schema_version="vtt.roster.v1",
                table_id=world.table_id,
                participants=(receipt.initial_gm,),
            )
            policy = TableAccessPolicy(
                roster=roster,
                bearer_tokens={receipt.initial_gm.participant_id: secrets.token_urlsafe(32)},
            )
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            resource = _Resource(connection, receipt, app)
            self._install_errors(app)
            install_scene_library_routes(
                app,
                library=scenes,
                session_id=receipt.session_id,
                table_id=world.table_id,
                access_policy=policy,
                map_asset_store=assets,
            )
            install_map_asset_routes(
                app,
                store=assets,
                scenes=scenes,
                session_id=receipt.session_id,
                table_id=world.table_id,
                access_policy=policy,
            )

            @app.get("/api/v1/table")
            async def table(request: Request) -> VTTTableView:
                request.state.vtt_revalidate()
                return resource.table()

            return resource
        except BaseException as exc:
            if connection is not None:
                connection.close()
            if isinstance(
                exc,
                (
                    sqlite3.Error,
                    OSError,
                    ValidationError,
                    SceneLibraryStoreError,
                    MapAssetStoreError,
                ),
            ):
                raise WorldPreparationError("world storage unavailable") from exc
            raise

    def _validate(self, connection: sqlite3.Connection, world: WorldRecord) -> _Receipt:
        try:
            if not self.database_path(world.world_id).is_file() or connection.execute(
                "PRAGMA integrity_check"
            ).fetchall() != [("ok",)]:
                raise WorldPreparationError("world integrity invalid")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables != _TABLES:
                raise WorldPreparationError("world schema incomplete")
            rows = connection.execute(f"SELECT singleton, receipt_json FROM {_RECEIPT}").fetchall()
            if len(rows) != 1 or rows[0][0] != 1:
                raise WorldPreparationError("world receipt missing")
            encoded = rows[0][1]
            receipt = _Receipt.model_validate_json(encoded)
            registry = self._registry.execute(
                f"SELECT table_id, state, receipt_digest FROM {_REGISTRY} WHERE world_id = ?",
                (world.world_id,),
            ).fetchone()
            if (
                registry != (world.table_id, "complete", _digest(encoded))
                or receipt.world_id != world.world_id
                or receipt.table_id != world.table_id
                or receipt.initial_gm.role != "gm"
                or receipt.schema_digest != _schema_digest(connection)
            ):
                raise WorldPreparationError("world receipt invalid")
            for table, version in [
                ("_vtt_scene_library_store_metadata", SCENE_LIBRARY_STORE_SCHEMA_VERSION),
                ("_vtt_map_asset_store_metadata", MAP_ASSET_STORE_SCHEMA_VERSION),
            ]:
                if connection.execute(
                    f"SELECT singleton, schema_version FROM {table}"
                ).fetchall() != [(1, version)]:
                    raise WorldPreparationError("world store metadata invalid")
            for table in [
                "_vtt_scene_library_event_log",
                "_vtt_map_asset",
                "_vtt_map_asset_command_log",
            ]:
                if connection.execute(
                    f"SELECT 1 FROM {table} WHERE table_id != ? LIMIT 1", (world.table_id,)
                ).fetchone():
                    raise WorldPreparationError("world store identity invalid")
            SQLiteSceneLibrary(connection, initialize=False).snapshot(world.table_id)
            assets = SQLiteMapAssetStore(connection, initialize=False)
            catalog = assets.catalog(world.table_id)
            for asset in catalog.assets:
                assets.content(world.table_id, asset.reference.asset_id)
            # Every uploaded revision needs its durable replay receipt and bytes.
            commands = connection.execute(
                "SELECT store_schema_version, command_id, revision, receipt_json FROM _vtt_map_asset_command_log WHERE table_id = ? ORDER BY revision",
                (world.table_id,),
            ).fetchall()
            if len(commands) != len(catalog.assets) or len(commands) != catalog.revision:
                raise WorldPreparationError("world asset history incomplete")
            for index, (version, command_id, revision, encoded_receipt) in enumerate(commands, 1):
                if version != MAP_ASSET_STORE_SCHEMA_VERSION or revision != index:
                    raise WorldPreparationError("world asset history invalid")
                upload = assets._parse_receipt(
                    encoded_receipt,
                    table_id=world.table_id,
                    command_id=command_id,
                    revision=revision,
                )
                if (
                    assets.content(world.table_id, upload.asset.reference.asset_id)[0]
                    != upload.asset
                ):
                    raise WorldPreparationError("world asset receipt invalid")
            return receipt
        except (
            sqlite3.Error,
            OSError,
            ValidationError,
            SceneLibraryStoreError,
            MapAssetStoreError,
        ) as exc:
            raise WorldPreparationError("world storage invalid") from exc

    def authenticate(self, world_id: str, token: str) -> _Resource:
        with self._lock:
            key = _digest(token)
            launch = self._launches.get(key)
            if launch is None or launch.resource.receipt.world_id != world_id:
                raise AuthenticationError("world authentication required")
            try:
                session = self._installation.authenticate_session(launch.admin_bearer)
                world = self._world(world_id)
                if (
                    session.admin_id != launch.resource.receipt.initial_gm.participant_id
                    or world.table_id != launch.resource.receipt.table_id
                ):
                    raise AuthenticationError("world authentication required")
            except (InstallationStoreError, WorldCatalogStoreError, sqlite3.Error):
                self._revoke(key)
                raise AuthenticationError("world authentication required") from None
            return launch.resource

    def return_world(self, world_id: str, token: str) -> None:
        with self._lock:
            self.authenticate(world_id, token)
            self._revoke(_digest(token))

    def prune(self) -> None:
        with self._lock:
            for key, launch in list(self._launches.items()):
                try:
                    self._installation.authenticate_session(launch.admin_bearer)
                    self._world(launch.resource.receipt.world_id)
                except (InstallationStoreError, WorldCatalogStoreError, sqlite3.Error):
                    self._revoke(key)

    def _revoke(self, key: str) -> None:
        launch = self._launches.pop(key, None)
        if launch is None:
            return
        resource = launch.resource
        if any(item.resource is resource for item in self._launches.values()):
            return
        self._resources.pop(resource.receipt.world_id, None)
        resource.retiring = True
        self._release(resource)

    def _release(self, resource: _Resource) -> None:
        if resource.retiring and not resource.requests and resource in self._owned:
            resource.connection.close()
            self._owned.remove(resource)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._launches.clear()
            self._resources.clear()
            for resource in tuple(self._owned):
                resource.connection.close()
                self._owned.remove(resource)

    @staticmethod
    def _install_errors(app: FastAPI) -> None:
        async def error(request: Request, exc: Exception):
            del request
            if isinstance(exc, AuthenticationError) or (
                isinstance(exc, HTTPException) and exc.status_code == 401
            ):
                return _error(401, "authentication_required", "World authentication required.")
            if isinstance(exc, (SceneLibraryAPIError, MapAssetAPIError)):
                return _error(exc.status_code, exc.code, exc.message)
            if isinstance(exc, (ValidationError, RequestValidationError, ValueError)):
                return _error(422, "invalid_request", "Request payload is invalid.")
            if isinstance(exc, HTTPException):
                return _error(
                    exc.status_code,
                    "not_found" if exc.status_code == 404 else "request_not_allowed",
                    "Requested operation is unavailable.",
                )
            return _error(503, "storage_unavailable", "World storage is unavailable.")

        for exception in [
            AuthenticationError,
            SceneLibraryAPIError,
            MapAssetAPIError,
            ValidationError,
            RequestValidationError,
            ValueError,
            HTTPException,
            sqlite3.Error,
        ]:
            app.add_exception_handler(exception, error)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        request = Request(scope)
        world_id = scope["path_params"]["world_id"]
        try:
            token = _bearer(request)
            with self._lock:
                resource = self.authenticate(world_id, token)
                resource.requests += 1
        except AuthenticationError:
            await _error(401, "authentication_required", "World authentication required.")(
                scope, receive, send
            )
            return

        def revalidate() -> None:
            self.authenticate(world_id, token)

        def access_valid() -> bool:
            try:
                revalidate()
                return True
            except AuthenticationError:
                return False

        async def authenticated_receive():
            message = await receive()
            if message["type"] == "http.request" and scope["method"] == "POST":
                try:
                    revalidate()
                except AuthenticationError:
                    # FastAPI preserves HTTPException raised during body reads;
                    # other errors would be rewritten as a parsing failure.
                    raise HTTPException(status_code=401) from None
            return message

        request.state.vtt_participant = resource.receipt.initial_gm
        request.state.vtt_revalidate = revalidate
        request.state.vtt_access_valid = access_valid
        try:
            await resource.app(scope, authenticated_receive, send)
        finally:
            with self._lock:
                resource.requests -= 1
                self._release(resource)
