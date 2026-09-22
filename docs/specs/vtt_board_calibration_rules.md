# VTT Board Calibration Rules

This is an independent dnd_sim geometry specification. It defines local user
jobs and mathematical invariants; it does not reproduce another VTT's source,
schemas, algorithms, identifiers, assets, or visual design.

## Outcome

A GM can bind an owned map image to a gridless, square, flat-top hex, or
pointy-top hex board using explicit view-space and engine-space units. The same
calibration must reconstruct after restart, invert without ambiguity at cell
centers, and drive rendering, measurement, token bounds, and templates from one
contract.

The session exposes one atomic active-board projection containing the durable
scene-library revision, active scene identity, engine-feet frame, and map
calibration. Token and annotation reads/streams, engine privacy filtering, and
the browser board bind to that same identity. A scene-library/session mismatch
is a loading state with no grid, tokens, or movement controls; it is never a
plausible legacy square board.

## Contract

`vtt.board_calibration.v1` contains:

- `topology`: `gridless`, `square`, `hex_flat`, or `hex_pointy`.
- `origin_x_px`, `origin_y_px`: the view-space center of square cell `(0, 0)`
  or axial hex cell `(0, 0)`, measured from the map's top-left corner.
- `cell_extent_px`: square side length, or the distance between axial `(0, 0)`
  and `(1, 0)` centers for either hex orientation.
- `distance_ft`: engine feet represented by one adjacent-cell step.

All numeric values are finite. Extent and distance are positive and bounded.
The calibrated origin and at least one complete supported cell must intersect
the image. Invalid changes retain the prior scene revision.

Gridless boards retain an explicit transform for ruler, token, fog, and drawing
coordinates but do not expose cell addressing or snap behavior.

## Square geometry

Square cell `(column, row)` has center:

```text
x_px = origin_x_px + column * cell_extent_px
y_px = origin_y_px + row * cell_extent_px
```

Its engine center applies the same relation with `distance_ft` from the
scene's feet origin. Square board distance uses the existing 5e diagonal rule;
calibration itself does not silently choose a different movement rule.

## Hex geometry

Hex cells use integer axial coordinates `(q, r)` and implicit cube coordinate
`s = -q-r`. Adjacency deltas are exactly:

```text
(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)
```

Distance is:

```text
max(abs(dq), abs(dr), abs(dq + dr)) * distance_ft
```

For pointy-top hexes:

```text
x_px = origin_x_px + cell_extent_px * (q + r / 2)
y_px = origin_y_px + cell_extent_px * sqrt(3) / 2 * r
```

For flat-top hexes:

```text
x_px = origin_x_px + cell_extent_px * sqrt(3) / 2 * q
y_px = origin_y_px + cell_extent_px * (r + q / 2)
```

The engine-space center uses the same equations with `distance_ft` and the
scene feet origin. Inverse transforms compute fractional axial coordinates and
use cube rounding: round all three cube components, then repair the component
with the largest rounding error so `q + r + s = 0`. Exact edge ties are resolved
by the deterministic component priority `q`, then `r`, then `s`.

## Bounds and footprints

The map image is a half-open rectangle `[0, width_px) × [0, height_px)`. A cell
is usable only when its entire square or regular-hex polygon lies inside that
rectangle. A token footprint is accepted only when its complete rotated shape
lies within the authoritative board. Square footprints use rotated rectangles;
hex footprints use an explicit bounded set of axial cells. Hex token rotation is
presentation-only and never changes occupied axial cells.

Hex movement commands use canonical calibrated cell-center waypoints. Preview
and commit derive a trusted cube-step cost at the HTTP authority boundary and
the shared engine turn resolver spends that cost; browser-supplied metadata
cannot override it. A path beyond the remaining cube budget is rejected before
engine execution, preserving both session revision and state.
Calibrated hex movement is planar: every waypoint retains the first waypoint's
finite elevation within `1e-6` feet. Vertical or mixed-elevation paths are
rejected before preview or commit instead of receiving a plausible
two-dimensional cube cost.

Gridless maps expose a focusable free-position cursor. Arrow keys move by view
pixels (Shift uses a larger pixel increment), while Enter or Space selects the
ruler/ping point. This path uses the same pixel-to-feet transform as pointer
input and never snaps to a hidden cell lattice.

## Acceptance fixtures

- Strict codec rejects extra fields, non-finite values, zero/negative extent,
  inconsistent topology, and calibrations without a complete usable cell.
- Square and both hex orientations round-trip at cell centers across positive
  and negative coordinates.
- Six axial neighbors are unique, symmetric, and one `distance_ft` away.
- Multi-step hex distances match cube distance and are symmetric.
- Exact edge/corner ties resolve identically across restart and Python/browser.
- Player rendering consumes only the server-projected topology and cells.
- Active-scene changes atomically rebind session, token, annotation, stream,
  and privacy consumers and survive restart.
- Both hex orientations charge one `distance_ft` for each slanted neighbor;
  crafted over-budget preview and commit commands fail without mutation.
- Hex tokens require a bounded connected axial footprint whose acceptance is
  invariant under presentation rotation.
- Unsupported geometry never falls back to a visually plausible square board.
- Gridless ruler and ping placement are operable entirely by keyboard, and
  reduced-motion presentation remains available.
