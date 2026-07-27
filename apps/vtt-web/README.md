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

The API must expose `GET /api/v1/session` and `POST /api/v1/commands` and allow the
frontend origin through its exact CORS allowlist.

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

The persisted annotation selector can remove one open-local marker, including a ping,
or clear all open-local annotations. Both actions use server-backed deletion. Clear is
implemented as revision-safe sequential delete commands and stops on the first stale
revision or ownership failure; the UI then rehydrates and asks the user to review and
retry instead of guessing at server state. Markers owned by another author stay visible
but cannot be removed from this open-local browser surface.

The bundled solo table uses open-local author identity. Protected browser authentication
is not implemented by this web app yet; deployments that enable participant-scoped
access need a credential source and request-header integration before these controls can
mutate protected tables.

## Verification

```bash
npm test
npm run lint
```

The project preserves the Sites vinext/Vite/Cloudflare Worker structure. No durable browser
state is used; session authority remains in the Python VTT service.
