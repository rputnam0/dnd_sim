"""Bearer authentication and role/ownership authorization for one VTT table."""

from __future__ import annotations

import secrets
from collections.abc import Mapping

from .contracts import VTTCommand
from .participants import TableParticipant, TableRoster

MINIMUM_BEARER_TOKEN_LENGTH = 16


class TableAccessError(PermissionError):
    """A stable authentication or command-authorization failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TableAccessPolicy:
    """Authenticate opaque credentials and authorize commands against a roster.

    Credentials are process configuration, not table state. They are copied into
    a private tuple and deliberately omitted from ``repr`` and public properties.
    """

    __slots__ = ("_credentials", "_roster")

    def __init__(
        self,
        *,
        roster: TableRoster,
        bearer_tokens: Mapping[str, str],
    ) -> None:
        if not isinstance(roster, TableRoster):
            raise TypeError("roster must be a TableRoster")
        if not isinstance(bearer_tokens, Mapping):
            raise TypeError("bearer_tokens must be a mapping")

        participant_ids = tuple(participant.participant_id for participant in roster.participants)
        supplied_ids = tuple(sorted(bearer_tokens))
        if supplied_ids != participant_ids:
            raise ValueError("bearer_tokens must contain exactly one entry per participant")

        credentials: list[tuple[str, TableParticipant]] = []
        seen_tokens: set[str] = set()
        for participant in roster.participants:
            credential = bearer_tokens[participant.participant_id]
            if not isinstance(credential, str):
                raise TypeError("bearer credentials must be strings")
            if credential != credential.strip() or any(
                character.isspace() for character in credential
            ):
                raise ValueError("bearer credentials must not contain whitespace")
            if len(credential) < MINIMUM_BEARER_TOKEN_LENGTH:
                raise ValueError(
                    f"bearer credentials must be at least {MINIMUM_BEARER_TOKEN_LENGTH} characters"
                )
            try:
                credential.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("bearer credentials must contain only ASCII characters") from exc
            if credential in seen_tokens:
                raise ValueError("bearer credentials must be unique")
            seen_tokens.add(credential)
            credentials.append((credential, participant))

        self._roster = roster.model_copy(deep=True)
        self._credentials = tuple(credentials)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(table_id={self._roster.table_id!r}, "
            f"participants={len(self._roster.participants)})"
        )

    @property
    def roster(self) -> TableRoster:
        """Return a detached immutable copy of the configured participant roster."""

        return self._roster.model_copy(deep=True)

    def authenticate(self, authorization: str | None) -> TableParticipant:
        """Resolve a canonical ``Authorization: Bearer`` header to a principal."""

        candidate: str | None = None
        if isinstance(authorization, str) and authorization == authorization.strip():
            parts = authorization.split(" ")
            if len(parts) == 2 and parts[0] == "Bearer" and parts[1]:
                try:
                    parts[1].encode("ascii")
                except UnicodeEncodeError:
                    candidate = None
                else:
                    candidate = parts[1]

        matched: TableParticipant | None = None
        if candidate is not None:
            for credential, participant in self._credentials:
                if secrets.compare_digest(candidate, credential):
                    matched = participant

        if matched is None:
            raise TableAccessError(
                "authentication_required",
                "Authentication is required for this table.",
            )
        return matched.model_copy(deep=True)

    def authorize_command(
        self,
        participant: TableParticipant,
        command: VTTCommand,
    ) -> None:
        """Require GM authority or player ownership for one command."""

        if not isinstance(participant, TableParticipant):
            raise TypeError("participant must be a TableParticipant")
        if not isinstance(command, VTTCommand):
            raise TypeError("command must be a VTTCommand")

        canonical = self._roster.participant(participant.participant_id)
        if canonical is None or canonical != participant:
            self._forbidden()
        if canonical.role == "gm":
            return
        if (
            canonical.role != "player"
            or command.mode == "admin"
            or command.actor_id is None
            or command.actor_id not in canonical.owned_actor_ids
        ):
            self._forbidden()

    @staticmethod
    def _forbidden() -> None:
        raise TableAccessError(
            "command_forbidden",
            "This participant is not permitted to issue the command.",
        )


__all__ = [
    "MINIMUM_BEARER_TOKEN_LENGTH",
    "TableAccessError",
    "TableAccessPolicy",
]
