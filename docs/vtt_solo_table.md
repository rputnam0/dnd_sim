# Echo Vault Solo Table: Local Operator Guide

The Echo Vault solo table is the first local VTT slice over the authoritative D&D engine. It
runs as two processes: a Python API that owns and persists one deterministic encounter, and a
vinext browser client that reads only the API's public projection.

## Prerequisites

- Python matching `pyproject.toml` (Python 3.12 or newer) and [`uv`](https://docs.astral.sh/uv/).
- Node.js 22.13 or newer and npm. Node 22 LTS is the recommended local runtime.
- Two terminal windows from the repository checkout.
- Ports 8000 and 3000 available on the loopback interface.

Install the Python environment from the repository root:

```bash
uv sync
```

Install the locked frontend dependencies:

```bash
cd apps/vtt-web
npm ci
```

Do not use `pip` for this repository, and do not point the frontend at a production or shared
database. This P0 composition is a single local session.

## Start the backend

The backend requires an explicit SQLite path. The following temporary location stays intact
across process restarts, but the operating system may eventually clean it up:

```bash
mkdir -p /tmp/dnd-sim-vtt
uv run python -m dnd_sim.vtt.solo_app \
  --database /tmp/dnd-sim-vtt/echo-vault.sqlite3 \
  --host 127.0.0.1 \
  --port 8000
```

For longer-lived local state, choose another explicit absolute path outside the checkout. The
parent directory must already exist. Keep the backend running in this terminal.

Confirm that the API is ready from another terminal:

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

The expected response is `{"status":"ok"}`.

### Database and restart behavior

The SQLite file stores every committed engine command, its public receipt, and the resulting
complete engine snapshot in one transaction. It also stores map-annotation commands and table-chat
commands in separate append-only logs with independently owned SQLite connections. Preview
commands are never written. On startup:

- an empty or new database creates `echo-vault-session` at revision 0;
- the same database path restores the latest stored snapshot, RNG state, command records, and
  event sequence;
- retrying a previously committed command with the same command ID and identical content returns
  its original receipt with `replayed: true` and does not mutate the encounter again;
- reusing a command ID for different content is a conflict;
- shared pings and area templates restore with their annotation revision and
  exact-retry receipts, while explicit deletions remain deleted;
- plain-text chat messages and deletion tombstones restore in durable sequence
  order with a cursor independent from encounter and annotation revisions;
- incompatible schema or version pins fail rather than silently migrating or resetting state.

To start a genuinely fresh table, stop the backend first and move the SQLite file aside, then
restart with a path that does not exist. There is intentionally no reset endpoint in P0. Do not
move, replace, or edit the database while the backend process has it open.

## Start the frontend

In the frontend terminal:

```bash
cd apps/vtt-web
npm run dev
```

The client defaults to this API base:

```text
http://127.0.0.1:8000
```

To use another local API address, set `NEXT_PUBLIC_VTT_API_BASE_URL` before starting vinext, or
put it in an ignored `apps/vtt-web/.env.local` file:

```bash
NEXT_PUBLIC_VTT_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open the exact local URL printed by vinext. The backend's default CORS allowlist accepts only:

- `http://127.0.0.1:3000`
- `http://localhost:3000`

The origin includes the scheme, host, and port. A fallback port such as 3001, a LAN hostname, or
an HTTPS origin is not equivalent and will be rejected. Free port 3000 and restart the frontend
if vinext selects another port. The backend does not use a wildcard origin and does not enable
credentialed CORS.

## Play the encounter

The browser always renders the public `projection` returned by the API. It does not read or infer
the canonical engine snapshot.

1. **Start.** On a fresh database, select **Start encounter**. This sends the actor-independent
   admin command, commits revision 1, and prepares Vela Quill's first turn.
2. **Choose destination.** In **1. Choose destination**, click one highlighted reachable grid
   cell. Selecting the actor's current cell means hold position. Movement v0 sends a direct
   two-waypoint path from the current cell center to the selected cell center in canonical engine
   feet; preview and commit both revalidate it on the server. The movement allowance shown in the
   inspector comes from the authoritative `dnd.turn-choices.v1` projection.
3. **Choose an action and target.** Select an available action, then select a valid token either on
   the map or in the target control. The fixed Echo Vault opener supports **Lattice Lance** against
   the **Hushglass Sentry**.
4. **Preview.** Select **Preview turn**. Preview resolves the full proposed declaration against a
   cloned state and RNG, returns projected HP/state changes and draft events, and leaves the
   authoritative revision unchanged.
5. **Commit.** After reviewing the preview, select **Commit turn**. Commit uses a new UUID command
   ID, persists the transition, advances the revision, appends canonical public events, and then
   refreshes the session view.
6. Repeat movement, targeting, preview, and commit for each active actor until the table reports
   party victory, party defeat, or timeout.

Changing the action, movement path, target, active actor, or revision invalidates the staged
preview. Preview again before committing. If another client advances the revision, the stale
command receives a conflict; reload `GET /api/v1/session` and rebuild the declaration from that
projection.

### Map tools

- **Measure** or `M` starts the local presentation ruler. Choose a start and end cell to see
  5e-style square-grid distance. The ruler never changes movement, calls the API, or persists.
- **Ping** or `P` starts shared-marker mode. Choose any cell, including one occupied by a token.
  The browser sends feet-space coordinates, adopts the server receipt, and follows the separate
  reconnectable annotation stream.
- **Template** or `T` starts shared area-template mode. Circle and cube use one center cell; line
  and cone use two cells. All dimensions are posted in canonical feet, while cone direction and
  length are derived from its origin and direction endpoint.
- The annotation selector removes one open-local marker or clears all open-local markers through
  revision-checked server deletes. A stale clear stops, rehydrates, and leaves the remaining
  markers for review. Markers owned by another participant cannot be deleted from this open-local
  browser surface.
- Ping markers currently persist across reloads and backend restarts. `duration_ms` controls the
  arrival pulse only; there is no automatic expiry.

### Table chat

The optional chat panel hydrates the current table-wide message view, follows its own reconnectable
event stream, and posts public messages through revision-checked commands. Messages are plain text:
HTML and Markdown-looking input is preserved literally, rendered as text, and never interpreted.
The v1 contract intentionally has no wall-clock timestamp, so the panel presents durable server
order rather than inventing client time.

The bundled solo table is open-local: the server replaces the untrusted request author with
`local`, and the panel may delete only `local` messages. The same backend supports authenticated
GM moderation, player-owned deletion, spectator read-only access, and public/role/participant/actor
audience selectors. The current browser does not yet provide protected-table credentials or a
private-audience composer, so those deployments must add both before using the panel.

## HTTP and event-stream contracts

All client payloads are strict, versioned JSON. Unknown fields, coercive values, stale revisions,
and malformed event cursors are rejected with a `vtt.error.v1` envelope.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Process health check. |
| `GET` | `/api/v1/session` | Atomic `vtt.session_view.v1` public scene/projection read; no canonical snapshot. |
| `POST` | `/api/v1/commands` | Strict `vtt.command.v1` endpoint for preview, admin, and commit modes. |
| `GET` | `/api/v1/events` | Long-lived Server-Sent Events stream of committed public `vtt.event.v1` records. |
| `GET` | `/api/v1/annotations` | Current scene-bound `vtt.annotations_view.v1` board projection. |
| `POST` | `/api/v1/annotation-commands` | Revision-checked `vtt.annotation_request.v1` put/delete endpoint. |
| `GET` | `/api/v1/annotation-events` | Reconnectable stream of committed `vtt.annotation_event.v1` records. |
| `GET` | `/api/v1/chat` | Current table-bound `vtt.chat_view.v1` plain-text message projection. |
| `POST` | `/api/v1/chat-commands` | Revision-checked `vtt.chat_request.v1` post/delete endpoint. |
| `GET` | `/api/v1/chat-events` | Reconnectable stream of committed `vtt.chat_event.v1` records. |

Command previews return `vtt.preview_response.v1`; admin and commit commands return
`vtt.commit_response.v1`.

The event stream emits records in canonical sequence order using:

```text
id: <event sequence>
event: vtt.event
data: <vtt.event.v1 JSON>
```

Preview draft events do not appear on this stream because they are not committed. When there are
no new events, the server sends an SSE comment heartbeat approximately every 15 seconds.

### SSE reconnect semantics

- `GET /api/v1/events?after=N` replays only events whose sequence is strictly greater than `N`,
  then remains connected for new events.
- A reconnect may instead send `Last-Event-ID: N`. Native `EventSource` clients do this from the
  last received `id` value.
- If both `after` and `Last-Event-ID` are supplied, the server resumes after the greater cursor to
  avoid replaying already observed events.
- Cursors must be canonical non-negative decimal integers: `0` is valid; negative values,
  whitespace, signs, and zero-padded forms such as `01` are rejected.
- Event history and sequence numbers survive a backend restart because they are part of the
  restored snapshot.
- After reconnecting, fetch `/api/v1/session` as the state authority. SSE events are a public
  ordered notification/log channel, not a replacement for the complete current projection.

The annotation stream follows the same exclusive `after=N` and `Last-Event-ID` rules, but its
cursor belongs only to the annotation board. The current annotation `revision` is also its latest
event sequence, so the browser hydrates the board and resumes after that value without mixing it
with the encounter-event cursor.

Chat uses a third independent cursor with the same exclusive reconnect rule. Hidden events advance
the server-side stream cursor without exposing their payload; later visible events may therefore
have sequence gaps. An authenticated message author is an implicit viewer of their own outbound
record across refresh and reconnect, even when its explicit audience names only another participant.

Inspect the stream manually with:

```bash
curl -N \
  -H 'Accept: text/event-stream' \
  'http://127.0.0.1:8000/api/v1/events?after=0'
```

## Verification

Run the focused backend suite from the repository root:

```bash
uv run python -m pytest \
  tests/test_vtt_scene.py \
  tests/test_vtt_session_service.py \
  tests/test_vtt_http_api.py \
  tests/test_vtt_annotation_http_api.py \
  tests/test_vtt_chat_store.py \
  tests/test_vtt_chat_http_api.py \
  tests/test_vtt_solo_table.py \
  tests/test_vtt_solo_app.py \
  tests/test_interactive_dnd_encounter_driver.py \
  -q
```

Check backend formatting:

```bash
uv run python -m black --check src/dnd_sim/vtt tests/test_vtt_*.py
```

Run the frontend production build, command-contract tests, rendered-content tests, and lint:

```bash
cd apps/vtt-web
npm test
npm run lint
```

`npm test` already runs the vinext production build. A healthy local smoke check should also show
revision 0 and phase `unstarted` for a fresh database:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/session | uv run python -m json.tool
```

## Honest P0 limitations

- One fixed original scene, seed, rules/content pins, roster, initiative order, and session ID.
- One local browser operator. Participant ownership, bearer authorization, and audience-filtered
  annotation/chat services exist on the backend, but this client has no protected credential,
  invitation, presence, or multiplayer-concurrency UX.
- Square-grid cell-center movement with one direct two-waypoint path only. There is no arbitrary
  multi-waypoint routing, drag-and-drop ruler, difficult terrain tool, wall/door authoring,
  collision editor, dynamic lighting, fog of war, or map asset pipeline.
- Fixed-roster encounter driver. Summoning or otherwise changing the roster is unsupported, lair
  actions are rejected, and reactions are currently auto-resolved rather than opening an
  interactive reaction prompt.
- The action surface covers what the fixed encounter projects; it is not a general character
  sheet, spellbook, inventory, encounter builder, campaign journal, or rules compendium.
- SSE carries committed audience-filtered events only. It is not a bidirectional WebSocket
  transport, and it does not stream previews or canonical snapshots.
- No reset/session-creation API, database administration UI, schema migration UI, or recovery UI.
- No manual dice tray, voice/video, file upload, shared notes, persisted ruler waypoints, freehand
  drawing, template editing, or automatic ping expiry. Current shared tools are durable pings,
  four area-template shapes with explicit cleanup, and public open-local plain-text chat.
- Local HTTP and an exact development CORS allowlist only; this composition is not production
  deployment, TLS termination, rate limiting, or security hardening.
