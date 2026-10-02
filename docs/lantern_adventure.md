# The Lantern Below

An original local adventure for one player controlling Mara, Iven, and Sela.
Designed for approximately 30 minutes on a first playthrough; actual duration
depends on reading and tactical choices and has not yet been human-playtested.

## Run locally

From the repository root, install the Python dependencies and start the backend:

```sh
uv sync --extra dev
uv run python -m dnd_sim.vtt.adventure_app
```

In a second terminal, start the existing tabletop application:

```sh
cd apps/vtt-web
uv run npm ci
NEXT_PUBLIC_VTT_API_BASE_URL=http://127.0.0.1:8010 uv run npm run dev -- --port 3000
```

Open <http://localhost:3000/adventure>. Keep both processes running while playing.
This adventure backend is separate from the Echo Vault demo backend. The `/`
and `/setup` routes continue to target their existing services when those are
configured; use `/adventure` with the adventure service.

For an occupied browser port, set the same explicit origin on the backend:

```sh
uv run python -m dnd_sim.vtt.adventure_app --port 8011 --web-origin http://localhost:3011
```

Then use `NEXT_PUBLIC_VTT_API_BASE_URL=http://127.0.0.1:8011` and browser port
`3011`. Origins must match exactly, including `localhost` versus `127.0.0.1`.

## Play

Read the current scene and objective, then choose an available action. The keeper
can be approached peacefully or threatened; exploration reveals supplies and
context for the final decision. Use the sheltered stair to prepare before the
last encounter. Healing supplies and rest are limited.

During combat, select an action, target, and destination on the tabletop, then
commit the turn. Enemy turns resolve automatically. The player interface does
not reveal the future dice result before committing. The party's health and
resources carry between scenes and encounters.

Every accepted choice and combat turn is saved before success is returned.
Refresh the page or restart both processes to continue from the latest accepted
action. A dropped reply can be retried with its original command ID without
applying it twice. A stale browser reloads the authoritative state before new
choices. At victory or defeat, the New adventure control starts a fresh run after
confirmation.

## Save ownership and supported scope

The default save is `.local/lantern-adventure.sqlite`, ignored by Git. Override
with `--database PATH` to keep separate playthroughs. Stop the backend before
copying the database for a backup. Restores use the engine/content version pins;
incompatible snapshots are rejected rather than silently rewritten.

This first slice is a loopback-only single-player game with a premade party,
authored choices, and a finite original content set. It uses the existing
whole-turn combat command and automatic reactions. It does not establish general
rules-catalog coverage, arbitrary character import, or multiplayer adventure
support. The map artwork is original; it illustrates each room, while the
overlaid tactical grid controls combat positions.

## Verification

```sh
uv run python -m pytest tests/test_adventure_runtime.py tests/test_adventure_api.py tests/test_adventure_api_journey.py
uv run python -m pytest
uv run python -m black --check .
uv run python scripts/docs/verify_program_docs.py
cd apps/vtt-web
uv run npm test
uv run npm run lint
```

Delivery status and remaining acceptance evidence are tracked in
[the ADV-01 checklist](lantern_adventure_plan.md).
