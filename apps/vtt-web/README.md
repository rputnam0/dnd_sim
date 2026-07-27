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

## Verification

```bash
npm test
npm run lint
```

The project preserves the Sites vinext/Vite/Cloudflare Worker structure. No durable browser
state is used; session authority remains in the Python VTT service.
