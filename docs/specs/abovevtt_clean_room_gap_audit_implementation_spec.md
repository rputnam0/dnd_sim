# AboveVTT Clean-Room Gap Audit — Implementation Specification

This specification is an independent dnd_sim design based on user jobs. It does
not prescribe or reproduce AboveVTT internals, naming, schemas, algorithms,
styling, or assets.

## 1. Build Plan

### Slice 0 — clean-room acceptance registry

- Add a local capability registry mapping claim IDs to job stories, tests, and
  status; never link it to upstream files.
- Record the stable parity baseline version and local evidence commit.
- Require a clean-room attestation in reviews for these slices.

### Slice 1 — map-backed active scenes

- Introduce a provider-neutral asset service with opaque asset IDs, ownership,
  MIME/media kind, dimensions/duration, integrity metadata, and lifecycle state.
- Extend scene metadata with an optional map asset reference and a versioned
  calibration record. Keep engine feet canonical and calculate view transforms
  from explicit calibration.
- Make scene activation an authoritative command that binds one scene revision to
  the running session. Restart and reconnect must reconstruct the same binding.
- Render static images first. Add video only after static asset security,
  performance, and fallback gates pass.

### Slice 2 — token lifecycle and presentation

- Separate engine actor identity from scene token presentation.
- Add authoritative token place, move, update-presentation, hide, lock, group,
  layer, and remove commands with expected revisions and idempotent command IDs.
- Project token identity, statistics, notes, and visibility per participant role
  and ownership. Never send hidden records to unauthorized clients.
- Add square footprints first; design hex footprints only with the hex rules spec.

### Slice 3 — visibility, fog, and drawing

- Add independently designed barrier segments, closable portals, light emitters,
  vision policies, darkness, and GM-owned manual-fog records.
- Compute a server-owned visibility result from active scene geometry, portal
  states, fog, token location, and engine senses. Send player-safe results, not GM
  source geometry when that geometry is private.
- Add GM player-view preview from the same projection path.
- Generalize annotations into bounded, layered drawing commands after fog
  correctness is established.

### Slice 4 — structured rolls and combat controls

- Finalize attack, save, check, healing, and applied-damage facts in the local
  roll journal without extra RNG draws.
- Project structured roll cards for public, private, blind, self, and GM
  audiences. Hidden modifiers remain absent rather than client-obscured.
- Add only combat controls represented by engine commands and replayable state
  transitions. Freeform overrides require explicit, audited command semantics.

### Slice 5 — preparation, content, and journal

- Build an engine-native actor/content library with provenance, search, preview,
  encounter staging, and token placement.
- Add journal folders, notes, handouts, sharing audiences, local actor/content
  links, and map pins with server projections.
- Add isolated importers for explicitly supported user-owned formats. Treat all
  imports as untrusted and translate into local contracts.

### Slice 6 — media and presentation

- Add a basic sound player with safe assets, playlists, audience playback state,
  volume, loop, stop, and browser-autoplay recovery.
- Add GM player-view and projector camera sessions; shared cursors and rulers are
  throttled ephemeral signals, not durable event-log noise.
- Evaluate weather, linked-scene portals, DM screen, advanced mixer, and peer
  media as separate candidate decisions. None blocks stable core parity.

Dependencies remain minimal: standard local HTTP/SQLite/browser foundations are
preferred. New media decoders, geometry libraries, or storage providers require
an explicit dependency and threat-model review.

## 2. Data and Interface Mapping

Names below describe local concepts, not upstream structures.

| field | meaning | units | source_equation_or_rule | citation_ids |
| --- | --- | --- | --- | --- |
| `asset_id` | Opaque identifier for an owned or approved external media record | none | Provider-neutral map and sound job | C-020, C-032, C-041 |
| `media_kind` | Validated static image, video, or audio category | enum | Render only explicitly supported media | C-020, C-032 |
| `scene_revision` | Optimistic concurrency version for scene changes | integer | Existing revision discipline | C-010, C-013 |
| `active_scene_id` | Scene revision bound to the running VTT session | none | Active metadata must equal tactical projection | C-013 |
| `calibration.origin` | View-space location of grid origin | pixels | Explicit world-to-view transform | C-014, C-022 |
| `calibration.cell_extent` | View-space cell size | pixels per cell | Explicit world-to-view transform | C-014, C-022 |
| `calibration.distance` | Engine distance represented by a cell | feet per cell | Feet remain canonical | C-014, C-022 |
| `calibration.topology` | Gridless, square, or supported hex orientation | enum | Explicit topology, never inferred silently | C-022 |
| `token_id` | Scene-local token presentation identity | none | Token lifecycle is distinct from actor identity | C-024 |
| `actor_id` | Optional authoritative engine actor link | none | Local engine substitution for external sheets/stat blocks | C-025, C-037 |
| `token_pose` | Position, footprint, rotation, elevation, and layer | feet, degrees, layer index | Scene presentation state | C-024, C-025 |
| `token_visibility` | Hidden state and audience-safe presentation policy | enum | Server projection owns secrecy | C-024, C-027 |
| `barrier_record` | Bounded scene segment with sight/movement behavior | scene coordinates | Visibility authoring job | C-027 |
| `portal_state` | Open/closed state of a closable barrier opening | enum | Door interaction job | C-027 |
| `light_emitter` | Origin, range, shape, and audience policy for scene light | feet and degrees | Dynamic light job | C-025, C-027 |
| `fog_operation` | GM-authored reveal/hide geometry and sequence | scene coordinates | Manual fog job | C-026 |
| `drawing_record` | Bounded layered shape, path, arrow, or sanitized text | scene coordinates | General drawing job | C-028 |
| `roll_fact_id` | Immutable link to an authoritative completed engine roll | none | Never roll during projection | C-016, C-030 |
| `roll_audience` | Public, self, GM, explicit participants, or blind policy | enum | Recipient-choice job with server privacy | C-030 |
| `journal_audience` | Owners/readers for a note or handout | principal IDs | Shared journal job | C-031 |
| `presentation_epoch` | Ephemeral projector/camera synchronization identity | monotonic integer | Avoid stale camera messages | C-034 |

Every durable request includes `schema_version`, `session_id`, `table_id`, a
typed command, `command_id`, and `expected_revision` where the aggregate is
revisioned. Responses expose sanitized change signals and current projections,
following existing local conventions.

## 3. Algorithm Procedure (Coding Form)

For each durable VTT command:

1. Authenticate before parsing attacker-controlled body or cursor details.
2. Validate strict schema version, table/session binding, command ID, expected
   revision, finite geometry, bounded collections, string lengths, ownership,
   role, and referenced-entity existence.
3. Resolve idempotent replay. The same principal, table, command ID, and canonical
   request returns the original result; conflicting reuse fails without mutation.
4. Begin a local transaction and compare the authoritative aggregate revision.
5. Apply the command through the relevant domain service. If it affects an
   engine actor or encounter, use engine legal transitions rather than directly
   editing projected state.
6. Append immutable event/fact records and update the projection revision in the
   same transaction. Store asset references, never untrusted filesystem paths.
7. Build separate GM, player, spectator, and explicit-recipient projections on
   the server. Omit secrets; do not send redactable placeholders when existence
   itself is private.
8. Commit, then publish a sanitized sequence/revision change signal. Reconnect
   uses the durable view and signals after the client cursor.
9. The browser fetches the current projection, renders media through validated
   asset endpoints, and treats ephemeral cursor/camera signals as disposable.
10. On any failure, emit a stable non-leaking error and leave durable state,
    revision, RNG, and event sequence unchanged.

Asset ingestion is a separate workflow:

1. Authorize ownership and allowed source type.
2. For uploads, stream into bounded temporary storage while computing integrity
   metadata. For remote URLs, apply the approved destination, redirect, DNS, size,
   timeout, and content policy.
3. Detect actual content type and decode metadata in an isolated boundary.
4. Reject malformed, unsupported, oversized, or unsafe content before creating a
   usable asset record.
5. Promote atomically, then let a separate scene command reference the asset ID.

## 4. Numerical Stability and Fallbacks

| scenario | risk | fallback/disable rule | citation_ids |
| --- | --- | --- | --- |
| Non-finite or extreme geometry | crashes, overflow, huge payloads | Reject before mutation; enforce scene, path-point, and coordinate bounds. | C-014, C-026, C-028 |
| Calibration too small or degenerate | unstable transforms and unusable selection | Require positive finite cell extent and invertible transform; retain prior calibration on failure. | C-022 |
| Unsupported hex behavior | incorrect movement or templates | Keep topology unavailable until geometry and engine-rule fixtures pass. | C-022 |
| Visibility recomputation exceeds budget | input lag and stale projections | Reject excessive geometry, cache by scene revision, and fall back to last complete projection with visible stale-state notice. | C-027 |
| Remote media unavailable | blank table or repeated fetch | Show explicit fallback; never change active scene or retry without bounds. | C-020, C-041 |
| Video or audio autoplay rejected | silent or blocked media | Provide user gesture recovery and static/paused fallback; never loop permission prompts. | C-020, C-032 |
| Animation exceeds accessibility/performance budget | motion sickness or dropped frames | Honor reduced motion, disable weather/video, and preserve static gameplay. | C-020, C-033 |
| Roll fact incomplete | misleading card or extra RNG | Do not synthesize totals or reroll; show a typed unavailable stage to authorized viewers. | C-016, C-030 |
| SSE gap or reconnect | divergent clients | Fetch authoritative current projection, then resume after the last accepted sequence. | C-010 |

## 5. Acceptance Gates and Kill Criteria

| gate_id | metric | threshold | comparison target | fail_action |
| --- | --- | --- | --- | --- |
| G-001 | Unauthorized secret fields in player/spectator payloads | exactly zero across contract, HTTP, SSE, and browser fixtures | current privacy guarantees | block_merge |
| G-002 | Same command replay mutations | zero extra events, revisions, RNG draws, or asset writes | current idempotency behavior | block_merge |
| G-003 | Restart reconstruction | byte-equivalent canonical durable projection for accepted fixtures | pre-restart projection | block_merge |
| G-004 | Active scene consistency | engine projection references exactly the activated scene revision | scene command result | block_merge |
| G-005 | Asset security corpus | all private, loopback, redirect-bypass, oversized, spoofed-type, and malformed cases rejected | threat-model fixtures | block_merge |
| G-006 | Token ownership | every unauthorized mutation rejected before durable change | role/ownership matrix | block_merge |
| G-007 | Visibility privacy | hidden tokens and private geometry absent from unauthorized projections | GM truth fixtures | block_merge |
| G-008 | Fog reconnect | same player-visible mask after reconnect and restart | committed fog revision | block_merge |
| G-009 | Roll determinism | projected cards consume zero RNG and match committed authoritative facts | fixed-seed journal fixtures | block_merge |
| G-010 | Import atomicity | malformed package creates zero usable partial entities or assets | import fixture corpus | block_merge |
| G-011 | Contract migration | every supported stored schema upgrades deterministically or fails with actionable typed error | version fixture matrix | block_merge |
| G-012 | Core interaction performance | agreed p95 pan, token-drag preview, command acknowledgement, and visibility recompute budgets on reference scenes | recorded pre-slice baseline | block_merge |
| G-013 | Accessibility | keyboard operation, focus recovery, contrast, text alternatives, and reduced-motion checks pass | project accessibility checklist | block_merge |
| G-014 | Clean-room review | no upstream source, asset, identifier, visual imitation, or derived algorithm in diff | this audit boundary | block_merge |

Kill a slice—not the program—if it cannot preserve server authority, privacy,
replay, or bounded resource use. Move the feature behind an explicit unsupported
state until a safe local design exists.

## 6. Evaluation Requirements

- Use deterministic contract/store/API tests before browser tests for every
  durable domain.
- Exercise GM, owning player, non-owning player, spectator, unauthenticated, stale
  revision, idempotent replay, restart, and reconnect cases.
- Maintain a small, medium, and adversarial reference-scene corpus for static,
  video, square, gridless, and eventually hex scenes.
- Report p50/p95 command acknowledgement, projection size, visibility compute,
  reconnect time, and browser frame time for the worst reference scene.
- Run security tests for URL ingestion, MIME spoofing, malformed imports, unsafe
  text, oversized geometry, and secret-bearing errors.
- Review user workflows by job completion, not pixel similarity to AboveVTT.
- Keep candidate features out of the stable parity score until promoted by an
  explicit product decision.

## 7. Traceability Map

| implementation_decision | claim_ids | citation_ids | rationale |
| --- | --- | --- | --- |
| Map-backed scene binding is first | C-013, C-014, C-020, C-022 | CIT-001, CIT-006, CIT-007 | Tokens, fog, drawing, presentation, and packages depend on a real active map. |
| Provider-neutral assets | C-020, C-032, C-041 | CIT-001 | Satisfies map/sound jobs without importing provider-specific assumptions. |
| Independent token aggregate linked optionally to actor | C-024, C-025, C-037 | CIT-001, CIT-004, CIT-008 | Separates tabletop presentation from rules state while retaining authority. |
| Server-owned visibility projection | C-015, C-026, C-027 | CIT-001, CIT-007, CIT-008 | Prevents hidden-token, fog, and geometry leaks. |
| Roll cards derive from journal facts | C-016, C-030 | CIT-001, CIT-008 | Prevents client rerolls and supports recipient privacy. |
| Local content substitution | C-025, C-037, C-038 | CIT-001, CIT-006, CIT-008 | Reproduces preparation jobs without D&D Beyond dependency. |
| Media and presentation after core table | C-032, C-033, C-034, C-035 | CIT-001, CIT-005 | Keeps optional high-cost features from destabilizing core parity. |

## 8. Spec Delta (Required)

| delta_id | baseline_spec | change_summary | rationale | citation_ids |
| --- | --- | --- | --- | --- |
| D-001 | `docs/abovevtt_feature_parity_plan.md` scene metadata lifecycle | Require active scene revision to bind to an engine-rendered map asset. | Metadata-only scenes do not complete the map-selection job. | C-013, C-020 |
| D-002 | Current square scene projection | Add explicit calibration and later supported hex topology. | Stable parity includes grid setup and hex. | C-014, C-022 |
| D-003 | Engine actor projection | Add scene token lifecycle and presentation as a separate aggregate. | Tokens need tabletop operations independent of actor facts. | C-024, C-025 |
| D-004 | Engine spatial visibility | Add VTT barrier, portal, light, fog, and audience-projection domains. | Rules visibility alone does not implement map vision. | C-015, C-026, C-027 |
| D-005 | Area annotation store | Add a bounded general drawing layer after visibility. | Stable parity includes text and drawing. | C-012, C-028 |
| D-006 | Raw roll journal foundation | Add finalized facts and audience-specific structured cards. | Current facts do not complete dice/chat delivery. | C-016, C-030 |
| D-007 | Scene metadata import/export | Add versioned campaign manifests only after related domains stabilize. | Portable play requires assets and entity relationships. | C-040 |
| D-008 | Existing roles and presence | Add projector/camera and shared-pointer signals as separate ephemeral channels. | Presentation state has different durability and traffic needs. | C-034 |

## 9. Locked Defaults For Coding (Required)

| default_id | field | locked_value | reason | citation_ids |
| --- | --- | --- | --- | --- |
| L-001 | implementation evidence | This audit plus local code only; upstream checkout prohibited | Preserve clean-room independence. | CIT-002 |
| L-002 | stable scope | Official AboveVTT 1.58 jobs | Avoid silently adopting beta churn. | CIT-001, CIT-003 |
| L-003 | durable authority | Server command, transaction, event/fact, projection, sanitized signal | Preserve local invariants. | CIT-007, CIT-008 |
| L-004 | authentication order | Authenticate before request/cursor validation on protected routes | Prevent validation oracle and wasted work. | CIT-007 |
| L-005 | privacy | Omit unauthorized data at server projection | Client redaction is not a security boundary. | CIT-006, CIT-007 |
| L-006 | distance units | Feet canonical; scene pixels confined to calibration/render boundaries | Avoid rules/view ambiguity. | CIT-007, CIT-008 |
| L-007 | identifiers | Opaque local IDs with explicit table/session binding | Avoid path/provider/source coupling. | CIT-007 |
| L-008 | geometry | Finite, bounded, explicitly versioned coordinates and topology | Security and deterministic replay. | CIT-007 |
| L-009 | RNG | Projection consumes zero RNG and never reconstructs a roll | Preserve authoritative results. | CIT-008 |
| L-010 | content | Owned, licensed, user-authored, or redistributable local content only | Avoid entitlement and provenance risk. | CIT-001, CIT-006 |
| L-011 | beta candidates | Disabled until explicit promotion | Keep parity measurable and scope stable. | CIT-003, CIT-004, CIT-005 |
