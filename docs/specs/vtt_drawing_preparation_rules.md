# VTT Drawing and Preparation Rules

This is an independent dnd_sim product specification derived from the local
clean-room capability audit. It does not reproduce another VTT's source,
schemas, identifiers, assets, algorithms, or visual expression.

## Outcome

A Game Master can mark an active calibrated scene with durable freehand paths,
rectangles, ellipses, arrows, and plain-text labels; organize them above or
below tokens; share them with an explicit table audience; update or remove one
record without broad erasure; and recover the exact result after reconnect or
restart. Players may create and manage only their own drawings when table
annotation policy already permits them. Spectators remain read-only.

Scene preparation also needs deterministic library filtering and a portable
local campaign package. Those are separate sub-slices in this workstream: the
drawing schema must stabilize first so a package can reference it without
rewriting durable history.

## Authority and units

- Drawings are durable annotation records in engine world feet, never browser
  pixels or DOM geometry. The browser converts feet through the active board
  calibration for presentation only.
- A mutation carries the current board revision and one exact drawing record.
  The server binds table, active scene, authenticated author, and audience
  before append. Exact retries replay; stale or conflicting commands do not
  mutate history.
- The server is authoritative for accepted geometry, style bounds, ownership,
  layer, and visibility. Clients do not send HTML, CSS, URLs, executable text,
  blend modes, filters, or unbounded paths.
- Existing annotation audience projection applies before HTTP and SSE
  delivery. A private drawing is absent for unauthorized participants.

## Drawing records

All records use `vtt.annotation.v1` and the existing annotation identity,
scene, author, and audience fields. Supported drawing variants are:

- `freehand_drawing`: an ordered path of 2–512 distinct finite feet-space
  points;
- `shape_drawing`: a non-degenerate axis-aligned rectangle or ellipse defined
  by two opposite corners;
- `arrow_drawing`: a non-degenerate planar segment with a bounded arrowhead;
- `text_drawing`: a finite anchor and 1–500 characters of canonical plain
  text, including line breaks but excluding control characters.

Every drawing has a style with a canonical lower-case `#rrggbb` stroke, an
optional fill, opacity from 0.05 through 1, bounded positive stroke width in
feet, and `solid` or `dashed` line style. Text adds bounded font size and an
optional canonical background color. Layer is `under_tokens` or `over_tokens`;
ordering within a layer is stable by annotation ID. `locked` is presentation
metadata: it prevents accidental browser editing but never weakens server
ownership checks.

## Bounds and failure behavior

- At most 2,000 active annotations per table and 512 points per freehand path.
- Each drawing's coordinate bounds must fit the active calibrated map's usable
  feet rectangle before append; labels use their anchor and arrows include the
  bounded head extent.
- Canonical text is Unicode plain text with no C0/C1 control characters other
  than line feed; markup remains inert text.
- Put/delete remains record-scoped. No rectangle erase, wildcard ID, scene
  clear, or audience-wide erase endpoint exists.
- Authentication precedes protected body validation. Public errors use stable
  codes and never echo hidden drawing IDs, text, authors, or audiences.
- Malformed, over-budget, off-board, unauthorized, or stale mutations leave
  revision, event sequence, and the current projection unchanged.

## Browser workflow and accessibility

- An independent drawing toolbar exposes type, layer, audience, colors,
  opacity, line style, and geometry. It is usable with labeled native controls
  and does not depend on pointer-only gestures.
- The calibrated board renders under-token drawings before tokens and
  over-token drawings after tokens from one strict projection. SVG text is
  emitted as text content, never HTML.
- The annotation manager identifies type, layer, author, and lock state;
  selection and record-scoped removal remain keyboard accessible.
- Loading, malformed projection, or calibration failure renders no plausible
  drawing geometry or mutation controls. Save/error status is announced.
- Reduced-motion mode disables any drawing entrance or selection animation.

## Acceptance fixtures

- Strict Python and TypeScript codecs round-trip every variant and reject extra
  fields, bad colors, control text, degenerate shapes/arrows, replacement-like
  path tricks, non-finite coordinates, excessive points, and unsupported layer
  or style values.
- Protected API tests cover GM/player/spectator ownership, private audience
  absence, active-scene and map-bound checks, exact retry, stale rejection,
  restart, SSE reconnect, and unchanged state on every rejection.
- Square, flat-hex, pointy-hex, and gridless fixtures project the same feet
  controls to expected view coordinates; calibration remains the only
  feet/pixel transform.
- Browser tests create each variant with keyboard-operable controls, render
  both layers and inert text, update one record, remove one record, and retain
  unrelated/private records.
