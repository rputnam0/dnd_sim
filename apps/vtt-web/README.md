# Echo Vault Solo Table

A responsive vinext browser table for the original deterministic Echo Vault encounter.
The UI reads only the public VTT session projection, stages preview commands, and refreshes
the authoritative view after each commit.

## Local development

```bash
npm install
npm run dev
```

The browser client uses `http://127.0.0.1:8000` as its default VTT API base. To point it
at another gateway, set `NEXT_PUBLIC_VTT_API_BASE_URL` in a local ignored `.env` file:

```bash
NEXT_PUBLIC_VTT_API_BASE_URL=http://127.0.0.1:8000
```

The API must expose `GET /api/v1/table`, `GET /api/v1/session`,
`GET /api/v1/events`, and `POST /api/v1/commands`, and allow the frontend origin
through its exact CORS allowlist.

## Protected browser authentication

The client first requests the strict, credential-free `vtt.table_view.v1`
participant directory. Open-local tables return a synthetic local GM and open
without a prompt. Protected tables show a password-style credential gate after
the API returns `401`; a successful credential identifies the current
participant, role, and owned actors. The credential stays only in page memory,
is carried in the `Authorization` header for JSON and fetch-based SSE requests,
and is never put in a URL or browser storage. Reloading a protected table
therefore requires the credential again.

Role and ownership controls are reflected in the browser as well as enforced by
the server. GMs may run admin commands and moderate shared records, players may
act only for owned actors, and spectators can follow the table without posting
or mutating it.

## Authoritative turn choices

Action and target controls come from the projection's strict `dnd.turn-choices.v1`
read model. `selectable_target_ids` identifies structural candidates the player may
stage, while `legal_target_ids` reports exact legality at the actor's current position.
The table labels candidates that need movement and relies on preview for final legality
after the planned path; it does not infer targets from actor teams in the browser.

## Presentation ruler

The map includes a presentation-only ruler. Toggle **Measure** or press `M` while focus
is not in an input or control, then choose any two grid cells. The readout uses direct
Chebyshev distance for the 5e square-grid diagonal rule: the larger of the horizontal and
vertical cell counts, multiplied by the scene's feet-per-cell value. **Clear measure**
removes both markers.

Ruler selections are browser-memory UI state. They do not change the planned movement,
are never sent to the API or persisted, and have no effect on preview or commit commands.

## Shared ping markers

When the optional annotation API is composed into the table service, the map hydrates
shared ping markers from `GET /api/v1/annotations` and follows the reconnectable
annotation event stream. Toggle **Ping** or press `P`, then choose any map cell. The
browser posts renderer-neutral feet coordinates and renders only server-returned ping
annotations for the active scene; ping clicks never change planned movement or ruler
endpoints.

This first slice treats pings as persisted shared markers. `duration_ms` controls the
arrival pulse animation, but the durable board currently has no timestamp, expiry, or
automatic expiry, so markers remain until explicit deletion. If the optional annotation
API is absent, the table leaves movement and ruler controls available and shows shared
annotation sync as unavailable.

## Shared area templates and deletion

Toggle **Template** or press `T` to place persisted circle, cone, line, and cube area
templates using the existing renderer-neutral `vtt.annotation.v1` contracts. Circle and
cube templates use one center cell. Line templates use two cell centers and an explicit
width in feet. Cone templates use an origin and direction endpoint; those cells derive
world-space length and direction while the bounded angle control remains explicit. The
SVG presentation converts server-returned feet to grid coordinates and never becomes
engine authority.

The persisted annotation selector can remove one marker owned by the current
participant; GMs can also moderate another participant's marker. **Clear mine**
removes only the current participant's records. Both actions use
server-backed deletion. Clear is implemented as revision-safe sequential delete commands and
stops on the first stale revision or ownership failure; the UI then rehydrates
and asks the user to review and retry instead of guessing at server state.

## Durable plain-text chat

When the optional chat API is composed into the table service, the chat panel hydrates
the authoritative ordered message view from `GET /api/v1/chat` and follows
`GET /api/v1/chat-events` with its own reconnectable revision cursor. Sequence gaps are
valid because audience filtering can hide intervening events; visible messages remain in
server order. A stale mutation or a successful response without a visible event triggers
an immediate authoritative rehydrate instead of a speculative browser update.

The composer can address everyone, Game Masters, or one non-spectator
participant. The server remains responsible for audience filtering and treats
authorship as implicit access to a participant's own outbound private message.
Authors may delete their messages and GMs may moderate any message; spectators
are read-only. Message text is preserved and rendered directly through React
text nodes with whitespace retained. There is no HTML or Markdown
interpretation and no timestamps are invented. The composer enforces the
2,000-character contract by Unicode code point, so multi-code-unit characters
count the same way as they do in the Python service. If the optional chat API
returns 404, the panel reports chat as unavailable while the tactical map and
event log continue to work.

## Scene lifecycle

When the scene library API is composed, the table hydrates
`GET /api/v1/scenes`, follows the authenticated scene event stream, and sends
revision-checked changes through `POST /api/v1/scene-commands`. GMs can create,
duplicate, activate, safely archive, export, and import strict scene metadata.
Players and spectators receive the active entry only and cannot mutate the
library. Archiving the active entry is disabled until an available successor
exists.

The portable `vtt.scene_export.v1` bundle includes the scene ID, display name,
pixel dimensions, grid size, and gridless flag. It intentionally excludes map
bytes, URLs, and asset paths. In this slice, activation changes the durable
scene-library selection; the running combat session remains attached to its
authoritative engine scene until the scene/session attachment boundary is added.

## Verification

```bash
npm test
npm run lint
```

The project preserves the Sites vinext/Vite/Cloudflare Worker structure. No durable browser
state is used; session authority remains in the Python VTT service.
