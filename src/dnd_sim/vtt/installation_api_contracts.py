"""Strict transport envelopes for installation administration, never table play."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .installation_contracts import AdminPublic, SessionPublic
from .world_catalog_contracts import (
    WorldArchiveCommand,
    WorldCatalogView,
    WorldMutationReceipt,
    WorldRecord,
)


class _StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InstallationLoginRequest(_StrictAPIModel):
    username: str
    password: SecretStr


class InstallationSessionView(_StrictAPIModel):
    schema_version: Literal["vtt.installation_session.v1"] = "vtt.installation_session.v1"
    admin: AdminPublic
    session: SessionPublic


class InstallationLoginResponse(_StrictAPIModel):
    schema_version: Literal["vtt.installation_login.v1"] = "vtt.installation_login.v1"
    admin: AdminPublic
    session: SessionPublic
    bearer_token: str = Field(repr=False)


class WorldDashboardView(_StrictAPIModel):
    schema_version: Literal["vtt.world_dashboard.v1"] = "vtt.world_dashboard.v1"
    catalog: WorldCatalogView
    launch_supported: Literal[False] = False
    launch_unavailable_reason: Literal["world_provisioning_not_implemented"] = (
        "world_provisioning_not_implemented"
    )


class WorldDashboardMutationResponse(_StrictAPIModel):
    schema_version: Literal["vtt.world_dashboard_mutation.v1"] = "vtt.world_dashboard_mutation.v1"
    receipt: WorldMutationReceipt
    replayed: bool
    dashboard: WorldDashboardView


class _WorldMutationRequest(_StrictAPIModel):
    command_id: str
    expected_revision: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return WorldArchiveCommand.validate_command_id(value)


class WorldCreateRequest(_WorldMutationRequest):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return WorldRecord.validate_name(value)


class WorldArchiveRequest(_WorldMutationRequest):
    world_id: str

    @field_validator("world_id")
    @classmethod
    def validate_world_id(cls, value: str) -> str:
        return WorldArchiveCommand.validate_world_id(value)


class WorldRenameRequest(WorldArchiveRequest):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return WorldRecord.validate_name(value)
