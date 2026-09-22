# DND Sim VTT Browser

A standalone vinext browser tabletop built on the authoritative `dnd_sim`
engine. Echo Vault is the bundled original demo world, not the product identity.
The UI reads only the participant-authorized VTT projection, stages preview
commands, and refreshes authoritative state after each commit.

## Persistent tabletop workspace

The tactical map, primary commands, and initiative tracker are stable workspace
slots rather than pages. Authorized live controllers remain mounted behind the
right-hand tool dock so chat, presence, journal, scene, token, visibility, and
presentation streams retain their reconnect state while users change tabs.
Game Masters can switch explicitly between **Play** and **Prepare**; players and
spectators receive Play only, and a live role downgrade removes preparation
panels synchronously. Workspace tabs support Left/Right/Home/End, every selected
panel is an exact focusable skip target, and compact layouts retain map,
initiative, then auxiliary-tool order instead of visually reordering keyboard
navigation.

The shell itself owns no table authority. It cannot build bearer headers,
interpret events, or synthesize actor, scene, token, or encounter state. An
optional injected preference adapter may persist only the validated workspace
mode and panel ID; the shipped table does not persist credentials or private
table data.

## Local development

```bash
uv run npm install
uv run npm run dev
```

## Standalone administration

The `/setup` route is the installation administrator entry point. From the
repository root, start a separate local administration service in a terminal:

```bash
uv run python -m dnd_sim.vtt.standalone_app --database /absolute/path/installation.sqlite
```

Choose an existing private parent directory for the database. On first run,
the service displays a one-time setup claim only in its controlling terminal.
Keep that claim private and retain it until setup succeeds: restarting does not
reissue it. Open `http://localhost:3000/setup`, use the claim to create an
administrator, then log in. A fresh noninteractive process must supply an
explicit local delivery callback through `create_standalone_app`; no claim is
returned by the HTTP API or written to an application log.

Administration defaults to `http://127.0.0.1:8001`, independently of the table
API on port 8000. Set `NEXT_PUBLIC_VTT_INSTALLATION_API_BASE_URL` to override the
administration address. The local administration CORS allowlist is exactly
`http://localhost:3000` and `http://127.0.0.1:3000`. This composition is for a
local/protected installation, not an internet-facing hosting release.

Administrators can create, rename, and archive durable world catalog records.
Archiving is irreversible in this version but retains the world's stored
metadata; the browser requires confirmation. Mutations use revision checks and
stable retry identities. Passwords, bootstrap claims, session bearers, and
private catalog state are never persisted in browser storage. Reload requires
login, and logging out revokes the server session and clears the local catalog.

**World launch is not implemented yet.** Catalog records are not playable
workspaces; provisioning, player invitations, actor deployment, and complete
world backup/restore are subsequent gates. The separate root route `/` remains
the explicitly labeled Echo Vault demonstration, served by the existing solo
table API. Creating a world never launches or copies that demonstration.

Missing or corrupt installation/catalog structures fail closed. Do not delete
or replace an existing database to clear a safe-mode message: preserve its
bytes for diagnosis. Automated repair, password recovery, schema migrations,
and backup/restore UI are not yet supported.

## Verification gates

From this browser directory, `uv run npm test` now runs strict TypeScript
checking before the production build and every browser contract/mounted test.
`uv run npm run lint` is a separate gate. A successful transpilation alone is
not a type check: the explicit gate catches mismatched transport helpers,
incomplete fixtures, and wrong projection field names.

The journal and presentation clients share the table service's strict error
decoder. Authentication and revision failures preserve their HTTP status and
structured details; losing presentation access clears private data while
retaining an identity-bound, visible error message.

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

## Participant presence

When the optional presence API is composed, the table shows the authenticated
participant directory with online, away, and offline status. Each open browser
keeps a memory-only client identity, sends revision-checked heartbeats using the
same authorization header as the rest of the table, and follows a reconnectable
presence-change stream. Stale heartbeats rehydrate the directory before one
bounded retry, while transient network failures repeat the same command once so
the server can honor its idempotency contract.

The safe presence view contains display names, roles, and derived statuses only.
Device IDs and observation timestamps remain server-internal, and the SSE
notification carries only the participant ID and revision needed to trigger a
fresh safe view. No presence identity or table credential is written to browser
storage or placed in a URL. If the optional service is absent, the roster stays
visible and reports presence as unavailable without disrupting play.

## Authoritative turn choices

Action and target controls come from the projection's strict `dnd.turn-choices.v1`
read model. `selectable_target_ids` identifies structural candidates the player may
stage, while `legal_target_ids` reports exact legality at the actor's current position.
The table labels candidates that need movement and relies on preview for final legality
after the planned path; it does not infer targets from actor teams in the browser.

## Audited combat tracker

The initiative panel includes Game Master controls for previous/next cursor
corrections, initiative reordering, delaying the active combatant, and selecting
an explicit actor and round. Every control requires a short audit reason and
posts the actor-independent `dnd.combat.control.v1` admin command through the
same transactional session as ordinary turns. The browser does not move the
cursor optimistically; it waits for the durable response and refreshes the
authoritative encounter projection. Players and spectators receive a read-only
tracker.

Ready remains a normal rules-engine declaration. Adding or removing combatants
is intentionally not a tracker shortcut: it will be supplied by the validated
actor/content library rather than accepting internal actor snapshots from a
browser.

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

## Durable layered drawings

Toggle **Draw** or press `D` to create shared freehand paths, rectangles,
ellipses, arrows, and inert plain-text labels. Native controls select the
under-token or over-token layer, public or self-only audience, stroke and
optional fill colors, opacity, width, line style, lock metadata, and text size.
Grid cells remain keyboard-selectable while drawing; a gridless board uses its
focusable free-position cursor and Enter or Space. Freehand paths accumulate
explicit control points and require **Finish path**, while shapes and arrows use
two positions and labels use one.

Every saved record is server-authored, revision checked, measured in world
feet, and reprojected through the active calibration for square, flat-hex,
pointy-hex, and gridless maps. The two SVG layers render from the same strict
annotation projection, with text emitted only through React text nodes. The
annotation manager can update one selected drawing's bounded presentation data
or remove that exact record; it never performs a wildcard or region erase.
Spectators remain read-only and unauthorized private drawings are absent from
both hydration and the reconnectable event stream.

## Journal, handouts, and scene pins

The optional journal service gives Game Masters an append-only, restart-safe
folder tree for original notes and handouts. Documents contain bounded inert
heading, paragraph, bullet-list, and internal-link blocks; React renders their
text directly and never interprets stored HTML or Markdown. The editor can
create and move folders, select note or handout type, choose a table audience,
set tags and favorites, compose each supported block, and attach a feet-space
pin to the active scene. Updates and two-step deletes remain record scoped and
optimistic-revision checked.

Players and spectators receive a flat list containing only authorized
documents. GM folder IDs, hidden documents, links to hidden targets, and hidden
pins are absent from both hydration and reconnectable events. Search runs over
the authorized structured text projection; an audience-narrowing update emits
a sanitized tombstone so a previously visible handout disappears immediately.
Any source event invalidates a filtered search result until an exact
session/table-bound rehydrate succeeds. Visible pins are focusable native map
buttons that open their projected handout, and pin placement is rejected unless
the server resolves the scene and calibrated map bounds.

## Shared sound and player view

The optional presentation service gives the GM a private, restart-safe library
of bounded MP3, Ogg, and WAV files. Files are uploaded through authenticated
first-party storage, signature and whole-file framing are checked, and the
browser verifies both MIME type and SHA-256 before creating a temporary object
URL. Play, pause, stop, loop, and playlist commands use the server epoch clock
and optimistic revisions. Players receive only playback addressed to them and
the one referenced track; unrelated tracks, playlist membership, and original
audience selectors are absent.

Volume and mute are local browser preferences and never enter a VTT request.
If browser autoplay policy blocks a shared track, playback stays paused and an
explicit **Enable sound** button performs the only retry. The GM can also share
an in-bounds camera center and zoom for the active scene. Players opt in with
**Follow GM view**; identity mismatch, scene activation, loading, or malformed
state immediately restores the neutral map. Native controls cover the complete
workflow, and reduced-motion users receive the camera change without a
transition.

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
duplicate, activate, safely archive, export, and import strict scene records.
Players and spectators receive the active entry only and cannot mutate the
library. Archiving the active entry is disabled until an available successor
exists.

The portable `vtt.scene_export.v1` bundle includes the scene ID, display name,
pixel dimensions, explicit board calibration, and an optional validated
same-origin map reference. References contain an opaque asset ID, supported
image media type, integrity digest, content path, and alternative text; map
bytes and remote URLs are not serialized into scene commands. The active
scene's image is rendered beneath the authoritative tactical grid, tokens, and
annotations. The solo table ships an original generated Echo Vault map at
`public/assets/maps/echo-vault-original.png`.

GMs can upload bounded PNG, JPEG, or WebP images (up to 12 MiB), then attach one
to the active scene and select gridless, square, flat-top hex, or pointy-top hex
geometry. Calibration records the cell-zero center in map pixels, the adjacent
cell extent, and feet per step. Square and axial hex movement, measurement,
tokens, and pings use this same transform. Gridless maps retain continuous
feet-scaled token, ping, and ruler placement without inventing cells. Existing
pre-calibration scene histories restore through a deterministic square/gridless
migration. Area-template placement remains enabled only for the exact legacy
square transform; other topologies report that limitation rather than drawing
plausible but incorrect geometry. The
server inspects the decoded media, records dimensions and a SHA-256 digest, and
stores bytes in the solo table's SQLite database. In protected tables, inactive
uploads are visible only to GMs. Players and spectators fetch only the active
image with their bearer credential; the browser verifies its media type and
digest before creating a temporary object URL, and revokes that URL on cleanup.
Credentials are never placed in asset URLs.

The engine still owns command legality and feet-based coordinates. Remote URL
ingestion, video maps, and hex-native area templates remain future scene/session
work.

## Fog, barriers, light, and token vision

When the optional visibility service is composed, non-GM clients hydrate only
`vtt.visibility_projection.v1`: a bounded run-length mask plus tokens currently
perceivable by the authenticated participant. The browser never receives raw
walls, door identifiers, light definitions, token-sense records, manual-fog
history, or occluded token identities. The same projection filters the session,
token endpoint, target controls, previews, commits, and event delivery. A
missing, invalid, loading, or reconnecting projection leaves the map fully
obscured; canvas rendering never falls back to an unmasked map.

The GM editor is a separate authenticated surface with keyboard-operable forms
for ambient light, shared sight, walls, windows, closable doors, lights, token
senses, and rectangular reveal/hide fog operations. Fog undo appends an inverse
operation instead of rewriting history. Door buttons announce the exact action,
and a participant selector requests the same player-safe preview schema used by
that participant. All mutations are revision checked, visibility updates resume
from sanitized SSE signals, and reduced-motion mode disables mask transitions.

## Verification

```bash
uv run npm test
uv run npm run lint
```

The project preserves the Sites vinext/Vite/Cloudflare Worker structure. No durable browser
state is used; session authority remains in the Python VTT service.
