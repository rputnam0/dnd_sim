# AboveVTT Clean-Room Gap Audit — Decision Report

## 1. Decision Summary

- Selected variant: reproduce the stable user jobs of AboveVTT 1.58 through
  independently designed, engine-native VTT capabilities, delivered in vertical
  slices that retain server authority, replay, privacy, and durability.
- Rejected variants: source port, visual clone, D&D Beyond integration clone,
  frontend-only mock parity, and a breadth-first rewrite.
- Decision date: 2026-08-11.
- Decision owner: dnd_sim product and engineering.
- Upstream evidence pin: `05df894b9078a63657c4cbfcf4848271ea00797e`,
  manifest version `1.59`, tag `1.59-beta65`.
- Local evidence pin: `ddf163279bc9c31b167d073bd66933886e99c1ef`.

The current VTT is not empty: it already has the harder trust foundation—an
authoritative encounter session, legal-choice commands, deterministic replay,
optimistic revisions, audience projections, SQLite persistence, SSE reconnect,
roles, actor ownership, presence, chat, annotations, a ruler, and scene metadata
lifecycle. The parity gap is predominantly tabletop surface area and scene/media
integration, not a need to replace that architecture.

## 2. Variant Comparison

| variant_id | description | strengths | weaknesses | applicability | decision | citation_ids |
| --- | --- | --- | --- | --- | --- | --- |
| V-001 | Clean-room, job-equivalent features on the local authoritative engine | Preserves replay, privacy, local content, and independent design | Requires explicit domain work and staged delivery | All stable parity work | selected | CIT-001, CIT-006, CIT-007, CIT-008 |
| V-002 | Port or translate upstream implementation | Superficially fast | Violates clean-room boundary, imports AGPL/source coupling, conflicts with local architecture | None | rejected | CIT-002 |
| V-003 | Clone upstream screens and interactions visually | Easy screenshot comparison | Copies expression, misses authority and accessibility, creates brittle coupling | None | rejected | CIT-001, CIT-002 |
| V-004 | Implement browser mocks before authoritative domains | Fast demos | State diverges on reconnect and private data becomes unsafe | Prototypes only, never production parity | rejected | CIT-007, CIT-008 |
| V-005 | Replace local content model with D&D Beyond coupling | Matches upstream integration context | Wrong product boundary and entitlement risk | None | rejected | CIT-001, CIT-002, CIT-006 |
| V-006 | One breadth-first VTT rewrite | Single conceptual launch | High integration risk and discards proven foundations | None | rejected | CIT-006, CIT-007, CIT-008 |

### Capability matrix

Status meanings: `present` is usable end to end; `partial` has a real local
foundation but not equivalent user workflow; `missing` has no VTT product slice;
`substitute` deliberately solves the user job differently; `candidate` is
beta-only or non-core evidence.

| capability | status | current local evidence | remaining product job | priority | evidence |
| --- | --- | --- | --- | --- | --- |
| Authoritative encounter and replay | present | Session service, revisioned commands, snapshots, RNG state | Preserve during every new slice | foundation | C-010 |
| Participant roles and actor ownership | present | Protected and open-local access modes | Extend permissions per new entity | foundation | C-011 |
| Presence and reconnectable streams | present | Durable heartbeats and SSE | Add only ephemeral collaboration channels where appropriate | foundation | C-011 |
| Audience-scoped plain chat | present | Durable public/private text | Add structured roll and handout payloads safely | P1 | C-011, C-030 |
| Pings and area templates | partial | Durable ping, circle, cone, line, cube annotations | General drawing, layers, text, undo, permissions | P1 | C-012, C-028 |
| Distance ruler | partial | Local square-grid measurement | Waypoints, shared ruler, optional movement planning | P2 | C-012, C-034 |
| Scene library lifecycle | partial | Metadata CRUD, activation, archive, import/export | Bind active scene to engine map and assets; organize at scale | P0 | C-013, C-023 |
| Map image assets | missing | No asset bytes or URL attached to scene | Upload/URL ingest, ownership, validation, rendering, fallback | P0 | C-020, C-041 |
| Video maps | missing | No media map type | Safe video asset/render controls and reduced-motion fallback | P2 | C-020 |
| Grid calibration | partial | Width, height, grid size, gridless flag | Origin/scale preview, crop/offset, reusable calibration wizard | P0 | C-014, C-022 |
| Hex grids | missing | Square-only scene projection | Two orientations, topology, movement, templates, footprints | P1 | C-014, C-022 |
| UVTT-style import | missing | Metadata JSON only | Safe external-scene importer with asset/grid/barrier mapping | P1 | C-021, C-040 |
| Token lifecycle | partial | Engine actors project as limited tokens | Place, move, duplicate, group, lock, hide, delete, layer | P0 | C-014, C-024 |
| Token presentation | missing | No custom image/scale/aura/elevation model | Independent presentation record and audience projection | P1 | C-024, C-025 |
| Token notes and sheets | substitute | Engine actor facts exist | Private/shared notes and local actor-sheet navigation | P1 | C-025, C-037 |
| Manual fog | missing | No fog domain | Durable reveal/hide commands and player-safe mask | P0 | C-026 |
| Walls, doors, and windows | missing | Engine visibility rules only | Barrier editor, portal state, deterministic LOS projection | P0 | C-015, C-027 |
| Light, vision, and darkness | missing | Engine `can_see` foundation only | Emitters, senses, darkness, preview, shared vision policy | P1 | C-015, C-025, C-027 |
| General drawing and text | missing | Area templates only | Layered shapes/freehand/text/arrows with scoped erase | P1 | C-028 |
| Combat tracker | partial | Engine-driven turns and conditions | Safe GM overrides, grouping, timers, manual encounter prep | P1 | C-029 |
| Structured dice and roll cards | partial | Raw authoritative roll journal foundation | Complete facts, recipients, blind/private views, notation | P0 | C-016, C-030 |
| Actor/monster library | missing | Engine actor types but no VTT preparation library | Search, inspect, stage encounter, drag/place token | P1 | C-037 |
| Journal and handouts | missing | Plain chat only | Foldered/searchable notes, sharing, links, map pins | P2 | C-031 |
| Adventure/book import | substitute | Local engine/content direction | Import owned local campaign packages, not DDB entitlements | P2 | C-038 |
| Sound player | missing | No VTT audio service | Safe tracks, playlists, recipient playback, volume/loop | P2 | C-032 |
| Weather overlays | candidate | None | Accessible cosmetic layer after performance budgets exist | P3 | C-033 |
| Projector/player-view presentation | partial | Role projections exist; no camera session | GM player-view preview and synchronized presentation camera | P1 | C-034 |
| Shared cursors/rulers | candidate | Presence without pointer stream | Throttled ephemeral collaboration signals | P2 | C-034 |
| Peer audio/video/screen share | candidate | None | Optional replaceable integration with consent/moderation | P3 | C-035 |
| GM reference screen | candidate | None | Compose local journal/content panels | P3 | C-036 |
| Linked-scene portals | candidate | None | Authorized transition links after scene attachment | P2 | C-039 |
| Portable campaign packages | partial | Scene metadata export only | Versioned manifest including owned assets and entities | P2 | C-040 |

## 3. Rejection Rationale

V-002 and V-003 fail the clean-room requirement. AboveVTT’s license, source
structures, assets, identifiers, styling, and algorithms are not implementation
inputs. V-004 fails because reconnect, replay, idempotency, and audience privacy
cannot be repaired reliably around client-owned mock state. V-005 reproduces an
integration rather than the user job and would couple the product to proprietary
content and entitlement behavior. V-006 sacrifices already-tested authority and
creates an unnecessarily large migration boundary.

## 4. Original vs Adaptation Resolution

| conflict_id | original_variant | adaptation_variant | normative_choice | compatibility_note | citation_ids |
| --- | --- | --- | --- | --- | --- |
| CFG-001 | Stable AboveVTT 1.58 listing | Pinned 1.59-beta65 main | stable 1.58 | Beta-only capabilities remain candidates until stable corroboration. | CIT-001, CIT-003, CIT-004, CIT-005 |
| CFG-002 | D&D Beyond sheets, books, monsters, entitlements | Engine-native actors, sheets, and owned campaign content | local adaptation | Preserve preparation and play jobs without copying external integration behavior. | CIT-001, CIT-006, CIT-008 |
| CFG-003 | Upstream client and data implementation | Local command/store/projection/SSE architecture | local adaptation | Compatibility is measured by user outcome and acceptance tests, not wire or UI similarity. | CIT-002, CIT-007, CIT-008 |
| CFG-004 | Cloud-provider-specific map access | Provider-neutral owned asset boundary | local adaptation | URL and upload jobs remain possible without embedding upstream provider assumptions. | CIT-001, CIT-007 |

## 5. No-Go Check Result

| condition | status | evidence |
| --- | --- | --- |
| Missing primary citation for core equation or official citation for core rule | pass | Stable parity claims use CIT-001; local claims use CIT-006 through CIT-008. |
| Unresolved unit mismatch | pass | Local feet remain canonical; pixels and grid coordinates are explicit view/calibration units. |
| Unidentifiable parameter set | pass | No fitted model is required; calibration inputs are explicit scene properties. |
| Applicability regime mismatch | pass | Stable 1.58 and beta 1.59 evidence are separated; D&D Beyond coupling is a declared substitution. |
| Missing measurable acceptance gates | pass | Implementation spec defines security, replay, projection, restart, geometry, and performance gates. |
| Core transcription-uncertain claim unresolved | pass | All reviewed evidence was machine-readable; OCR was not used. |
| Upstream source or expression required to implement | pass | The handoff contains abstract jobs and local acceptance criteria only. |

## 6. Locked Defaults

| default_id | field | locked_value | reason | citation_ids |
| --- | --- | --- | --- | --- |
| L-001 | normative parity baseline | Official stable AboveVTT 1.58 listing | Prevent beta churn from silently expanding scope. | CIT-001, CIT-003 |
| L-002 | clean-room boundary | No upstream code, assets, schemas, algorithms, identifiers, or visual imitation | Required by product intent and license-risk posture. | CIT-002 |
| L-003 | authority | Server owns durable state and legal mutations | Preserves existing replay and anti-leak guarantees. | CIT-007, CIT-008 |
| L-004 | privacy | Server builds audience projections; clients do not filter secrets | Existing trustworthy boundary. | CIT-006, CIT-007 |
| L-005 | distance | Feet are canonical engine units; pixels are scene-presentation units | Matches local engine and scene foundations. | CIT-007, CIT-008 |
| L-006 | contracts | Strict, versioned, finite, bounded, unknown-field-rejecting contracts | Matches current VTT contract discipline. | CIT-007 |
| L-007 | content substitution | Local actors and owned/licensed content replace D&D Beyond integration | Reproduces jobs without proprietary coupling. | CIT-001, CIT-006 |
| L-008 | delivery order | Map attachment, tokens, visibility, rolls, prep, then media/presentation | Closes dependency gaps before cosmetic breadth. | CIT-006, CIT-007, CIT-008 |

## 7. Spec Change Protocol

Each slice begins with failing contract/store/API/browser tests, adds only local
designs, and records claim IDs from the evidence table. A change to a locked
default requires a short spec delta: affected default, user job, security/privacy
impact, migration impact, evidence, and acceptance-gate changes. A repo-only beta
capability cannot be promoted to normative parity without current official stable
evidence or an explicit product decision. Any accidental dependence on upstream
source halts that slice and triggers an independent redesign.

## 8. Final Status (Machine Readable)

status = ready_for_implementation
