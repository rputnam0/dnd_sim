from __future__ import annotations

from types import ModuleType

from dnd_sim import engine_legacy as _engine_legacy
from dnd_sim.telemetry import build_event_envelope


def _export_engine_symbols(module: ModuleType) -> None:
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        globals()[name] = value


_export_engine_symbols(_engine_legacy)


def _append_telemetry_event(
    telemetry: list[dict[str, object]] | None,
    *,
    event_type: str,
    payload: dict[str, object],
    source: str = __name__,
) -> None:
    if telemetry is None:
        return
    telemetry.append(
        build_event_envelope(
            event_type=event_type,
            payload=payload,
            source=source,
        )
    )

__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
    and name not in {"ModuleType", "_engine_legacy", "_export_engine_symbols"}
]
