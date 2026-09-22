# VTT Visibility and Fog Rules

This is an independent dnd_sim product specification. It derives local user
jobs from the clean-room audit and defines original contracts and algorithms; it
does not reproduce another VTT's source, schemas, identifiers, assets, or visual
expression.

## Outcome

A GM can prepare opaque walls, windows, closable doors, light emitters, scene
darkness, token senses, and manual fog. A player receives only the scene regions,
tokens, and presentation records their owned observers can currently perceive.
The GM can preview that exact participant projection. State survives restart,
reconnects from a sanitized revision signal, and never sends hidden geometry as
CSS, canvas data, or dormant JSON.

## Coordinate and authority model

- All stored geometry uses finite engine feet in the scene plane. Browser pixels
  cross the selected scene's `vtt.board_calibration.v1` transform exactly once.
- Visibility is an application-server projection. The browser may render the
  projected mask, but it never decides whether a token or secret record is
  visible.
- Engine conditions and senses remain engine facts. VTT token-vision settings
  may narrow presentation range or add non-rules presentation light, but cannot
  grant an engine action permission.
- A visibility revision is independent from encounter, scene-library, and token
  revisions. Projection cache keys include all four revisions plus participant
  identity; no stale result may be relabeled as current.

## Durable records

`vtt.visibility_record.v1` is a discriminated union:

- `barrier`: `barrier_id`, `scene_id`, endpoints in feet, behavior `wall`,
  `window`, or `door`, and movement/sight policy. Endpoints must differ by at
  least 0.01 ft and remain inside the active scene. Barriers have zero secret
  thickness and deterministic closed-segment intersection semantics.
- `portal`: represented by a `door` barrier with `portal_state` `open` or
  `closed`. An open door blocks neither sight nor movement; a closed door follows
  its declared policy. Door state changes are individually revisioned events.
- `light`: `light_id`, origin in feet, bright and dim radius, shape `circle` or
  bounded cone, direction, and audience. Dim radius is at least bright radius.
- `scene_environment`: exactly one scene darkness value: `bright`, `dim`, or
  `darkness`, plus shared-vision policy `owned_only` or `party`.
- `token_vision`: one optional record per token with enabled flag, normal vision
  range, darkvision range, and optional presentation-only emitted light.
- `fog_operation`: GM-authored `reveal` or `hide` over a bounded polygon in feet,
  with immutable order. Fog begins hidden. Operations fold in order; the latest
  operation containing a sampled point wins. Undo appends an inverse operation
  and never rewrites history.

IDs are canonical, opaque, and table-local. Collections and polygon vertex
counts are bounded. Self-intersecting, degenerate, non-finite, off-scene, or
over-budget geometry is rejected before a transaction. There is no remote
script, shader, expression, or URL field.

## Deterministic sight

For one observer and sample point:

1. Reject beyond the observer's presentation range.
2. Reject when any closed sight-blocking barrier properly intersects the open
   observer-to-sample segment. A ray touching a shared endpoint uses a fixed
   half-open endpoint rule so adjacent walls do not create precision cracks.
3. Determine illumination from scene darkness, applicable light emitters, and
   darkvision. Windows pass sight but may block movement. Doors use their stored
   state.
4. Apply the folded manual-fog state. Manual fog can hide an otherwise visible
   point and can reveal an illuminated, line-of-sight point; it never reveals a
   token behind a sight-blocking barrier.
5. Union visible regions from observers permitted by the scene shared-vision
   policy. Intersect the result with the finite scene rectangle.

The initial implementation projects a bounded raster mask whose dimensions are
derived from the map aspect ratio and a fixed maximum sample budget. Cell
topology is not used to decide visibility, so square, hex, and gridless maps use
the same feet-space semantics. Samples are evaluated at pixel centers with
stable row-major ordering. Projection includes the opaque visible mask and
visible public token records only; raw barriers, lights, fog operations, hidden
token IDs, and hidden names are GM-only.

## Command and projection surfaces

- GM-only revision commands create/update/delete records, toggle doors, set the
  environment, and append/undo fog.
- Player/spectator GET returns `vtt.visibility_projection.v1` for their
  authenticated participant. The GM may request an explicit participant preview
  but receives the same projected schema, not a bypassed hybrid.
- GM GET returns an editor view containing all records and a separate preview
  selector. Mutation receipts may contain editor records only for the GM.
- SSE data is exactly an identity-free `{schema_version, sequence, revision,
  scene_id}` signal. Reconnect uses `after` and `Last-Event-ID` and rehydrates the
  projection.
- Authentication runs before body, scene ID, preview participant, and cursor
  validation. Stable public errors do not echo private IDs or geometry.

## Accessibility and operating envelope

- Every editor action has form/list controls in addition to pointer placement.
  Doors expose named toggle buttons and current state; fog tools announce mode,
  undo availability, and sync status.
- Player masking does not rely on color alone. Loading, stale, unavailable, and
  preview states are announced. Reduced-motion disables fog transitions.
- Per scene: at most 2,000 barriers, 500 lights, 500 token-vision records, 2,000
  fog operations, 128 polygon vertices per operation, and 65,536 mask samples.
  Commands exceeding a bound fail without revision change.
- Projection also has a deterministic combined-work ceiling of 8,000,000
  sample relationships, checked before raster work. The estimate is mask
  samples multiplied by the sum of fog polygon vertices, applicable authored
  lights, emitted token lights, and observers. A scene may retain records up to
  the durable authoring limits while requiring a lower-resolution future
  projection mode when that audience-specific product exceeds the ceiling; the
  server fails closed instead of beginning unbounded work.

## Acceptance fixtures

- Strict codec, optimistic revision, idempotent replay, append-only restart, and
  corruption tests cover every record and command variant.
- Segment intersection fixtures cover crossings, parallel segments, collinear
  overlap, endpoint joins, windows, and open/closed doors.
- Bright/dim/darkness, darkvision range, cone boundaries, shared vision, manual
  reveal/hide/undo, and square/hex/gridless scene fixtures are deterministic.
- Player GET/SSE/browser state contains no raw barrier, light, fog-operation,
  hidden-token ID/name, credential, observer sense, or GM preview selector.
- Hidden actors are absent from session projection, targets, commands, events,
  initiative, and token projection; crafted commands remain rejected before the
  engine executes.
- Reconnect and restart produce byte-equivalent player masks at the same source
  revisions. A door toggle invalidates the cache and changes only the intended
  projection.
- Browser controls are keyboard operable, mask failure never reveals the full
  map, unsupported geometry never falls back to client-side vision, and the
  performance budget is enforced before projection work.
