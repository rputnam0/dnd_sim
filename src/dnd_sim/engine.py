from __future__ import annotations

from types import ModuleType

from dnd_sim import engine_legacy as _engine_legacy


def _export_engine_symbols(module: ModuleType) -> None:
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        globals()[name] = value


_export_engine_symbols(_engine_legacy)

__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
    and name not in {"ModuleType", "_engine_legacy", "_export_engine_symbols"}
]
