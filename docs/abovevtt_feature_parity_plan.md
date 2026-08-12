# AboveVTT Feature-Parity Plan

Status: active implementation plan  
Owner: VTT program  
Last updated: 2026-08-11

This plan defines an independent VTT product built on the authoritative
`dnd_sim` engine. AboveVTT is the user-experience benchmark, not a source-code
dependency. Its repository is AGPL-3.0, so this implementation must use its own
contracts, code, assets, naming, and visual design.

## Reference baseline

The parity baseline is AboveVTT 1.58, as observed in its official public
surfaces on 2026-07-26:

- [AboveVTT repository](https://github.com/cyruzzo/AboveVTT)
- [AboveVTT wiki](https://github.com/cyruzzo/AboveVTT/wiki)
- [AboveVTT browser listing](https://chromewebstore.google.com/detail/abovevtt/ipcjcbhpofedihcloggaichibomadlei)
- [1.58 release notes](https://github.com/cyruzzo/AboveVTT/wiki/Current-Release-Patch-Notes)

"Parity" means that the corresponding tabletop job can be completed. It does
not require identical interaction design, D&D Beyond integration, or internal
implementation. Where AboveVTT delegates rules to D&D Beyond, this product
should prefer the local deterministic rules engine.

## Product principles

- The server is authoritative for rules, turns, resources, hit points,
  conditions, initiative, and canonical token positions.
- Clients send versioned intent commands and receive audience-filtered read
  models. They never mutate canonical state directly.
- Preview and commit use the same rules path. Rejected commands leave state and
  RNG unchanged.
- Every committed command is idempotent, append-only, restart-safe, and
  replayable.
- Feet are the canonical spatial unit. Grid cells and pixels are projections.
- GM secrets, hidden tokens, fog, and private rolls are enforced by server-side
  projection, not merely hidden by CSS.
- Original or user-supplied content is used for demos. No proprietary D&D
  Beyond content or AboveVTT assets are bundled.

## Parity ladder

### P0 — Solo authoritative table

Goal: finish one original combat encounter entirely through the VTT boundary,
then restart and recover it exactly.

- [x] Transactional engine session with preview, commit, revision checks, and
      idempotent retries.
- [x] Complete actor runtime codec and deterministic RNG snapshot/restore.
- [x] Shared batch/interactive turn resolution with a real declaration prompt.
- [x] Append-only SQLite command, receipt, and snapshot store.
- [x] Fixed-roster initiative cursor with round, victory, defeat, and timeout.
- [x] Strict `vtt.command.v1` application boundary over engine sessions.
- [x] Versioned square-grid scene and token projection.
- [x] Public action metadata, initiative, HP, condition, and rules-event read
      model.
- [x] Authoritative legal movement, action, and target choice read model.
- [x] HTTP JSON endpoints for singleton load/read/preview/commit.
- [x] Server-sent event stream with reconnect cursor and heartbeat.
- [x] Browser table with map, token selection, movement preview, action palette,
      target selection, initiative, HP/conditions, rules log, and outcome.
- [x] End-to-end deterministic completion, restart, replay, and duplicate-command
      test.

P0 acceptance: a user can open a table, play every prompted actor turn through
the browser, see authoritative results, finish the encounter, restart the
service, and recover byte-identical state without duplicate mutation.

### P1 — Shared tabletop essentials

Goal: cover the core DM/player jobs advertised by AboveVTT.

- [ ] Campaign, table, participant, role, and token-ownership models.
      Strict participant, roster, role, actor-ownership, bearer-access,
      in-memory browser credential, and annotation-audience foundations are
      implemented; campaign and table lifecycle remain.
- [x] Multi-client presence, reconnect, optimistic concurrency, and event deltas.
      The durable server-timed heartbeat log aggregates multiple browser clients,
      derives online/away/offline status, survives restart, retries idempotently,
      and exposes only a safe roster view plus sanitized reconnect signals.
- [ ] Public, GM-only, player-private, and blind roll/chat audiences.
      Annotation and durable plain-text chat reads/events enforce public, role,
      participant, and owned-actor audiences. Chat authors retain access to
      their own outbound private messages, GMs can moderate, and spectators are
      read-only. Private/blind authoritative roll presentation remains.
- [ ] Dice tray and structured roll cards tied to rules events.
      This requires the engine-owned, no-reroll journal defined in
      [`vtt_roll_journal_plan.md`](vtt_roll_journal_plan.md). Base attack and raw
      damage RNG boundaries now retain honest facts without changing outcomes;
      final timing-hook, save/check, applied-damage, projection, and card work
      remains.
- [ ] Scene create, duplicate, activate, archive, import, and export.
      The durable metadata lifecycle and GM browser manager are implemented,
      including explicit successor selection before archiving an active scene.
      This remains open until activation attaches the running combat session and
      map asset rather than changing metadata selection alone.
- [ ] Map image/video metadata, crop, scale, offset, grid calibration, and
      gridless mode.
- [ ] Token create, move, rotate, resize, lock, hide, group-select, copy, and
      delete.
- [ ] Token ownership, nameplate, HP bar, conditions, aura, elevation, and
      footprint.
- [ ] Ruler, waypoints, movement cost, ping, and area templates.
      A local 5e grid ruler, durable shared pings, strict renderer-neutral
      geometry, persisted circle/cone/line/cube placement, and revision-checked
      annotation removal are implemented. Shared ruler waypoints, automatic
      ping expiry, template editing, and terrain costs remain.
- [ ] Freehand drawing, shapes, text labels, colors, opacity, and erase.
- [ ] Manual fog reveal/hide plus per-participant fog projection.
- [ ] Walls, doors, windows, terrain barriers, and line-of-sight geometry.
- [ ] Light sources, darkvision, token vision, darkness, and GM preview-as-player.
- [ ] Combat tracker controls: add/remove, initiative, next/previous, round,
      delay/ready, and manual override audit event.

P1 acceptance: one GM and two players can join the same table, perceive only
their authorized state, explore a walled/fogged scene, roll and chat privately
or publicly, and complete authoritative combat through reconnects.

### P2 — Session preparation and content workflow

Goal: make ongoing campaign preparation and play convenient rather than merely
possible.

- [ ] Actor sheets for PCs, NPCs, monsters, companions, and custom actors.
- [ ] Searchable rules/content library with capability support indicators.
- [ ] Encounter builder and reusable encounter templates.
- [ ] Drag actors from the library to create linked tokens.
- [ ] Custom stat blocks with roll buttons, area templates, and rules tooltips.
- [ ] Journal tree, rich notes, handouts, audience sharing, and map pins.
- [ ] Scene folders, token folders, tags, favorites, and fuzzy search.
- [ ] Token appearance presets, wildcard images, numbering, and default settings.
- [ ] Cross-scene portals, return portals, secret portals, and encounter-preserving
      transitions.
- [ ] Audio library, playlists, per-user volume, positional audio tokens, and
      synchronized playback.
- [ ] Weather and ambient visual overlays.
- [ ] Import/export packages with explicit schema versions and migrations.

P2 acceptance: a GM can prepare and run a multi-scene original one-shot without
editing database rows or Python files, and can export then re-import the whole
table on a fresh installation.

### P3 — Advanced presentation and ecosystem

Goal: match the convenience and polish expected of a mature browser VTT while
using this product's own identity.

- [ ] Pop-out panels, configurable layout, keyboard shortcuts, command palette,
      and accessible touch/tablet controls.
- [ ] Animated maps/tokens/auras, camera bookmarks, player view focus, and
      scene transitions.
- [ ] Optional 3D dice visualization driven by authoritative roll events.
- [ ] Optional peer audio/video with explicit consent and device controls.
- [ ] Cloud asset providers and resumable uploads behind provider adapters.
- [ ] Extension/plugin API with versioned permissions and sandboxed capabilities.
- [ ] Localization, reduced motion, color-blind-safe indicators, and screen-reader
      workflows.
- [ ] Performance budgets for large maps, hundreds of tokens, dynamic vision,
      and long-running campaigns.

P3 acceptance: the table remains usable and recoverable during a four-hour
session on supported desktop and tablet browsers, including large scenes and
optional media features.

## Component map

| Component | Authority | First parity responsibility |
| --- | --- | --- |
| `interactive` driver | rules engine | Encounter prompts, declarations, outcomes, replay |
| VTT session service | application server | Translate VTT intents, transact, persist, recover |
| projection service | application server | Legal choices and audience-filtered table state |
| scene domain | application server | Feet, grids, tokens, bounds, map metadata |
| visibility domain | application server | Walls, doors, fog, light, line of sight |
| transport gateway | network edge | HTTP, event stream, auth, reconnect cursors |
| browser client | presentation | Canvas, panels, interaction state, accessibility |
| asset service | infrastructure | User assets, derivatives, quotas, portability |

## Delivery rules

- Implement vertically: every milestone must include contracts, persistence,
  projection, UI where applicable, and tests for one complete user job.
- Add a schema version and strict validation before persisting any new domain.
- Keep engine state and presentation state separate; never persist pixels as
  authoritative movement coordinates.
- Add migration tests before changing a persisted schema.
- Add audience-leak tests before exposing multiplayer state.
- Record manual GM overrides as commands/events rather than mutating storage.
- Treat compatibility with old snapshots and command retries as release gates.

## Current implementation sequence

1. Finish the fixed-roster encounter cursor and terminal outcomes. Done on the
   active implementation branch.
2. Put it behind the restart-safe VTT session service. Done on the active
   implementation branch.
3. Add strict scene coordinates and public actor/token projection. Done on the
   active implementation branch.
4. Build and consume the legal-choice/table read model. Done on the active
   implementation branch; pull-request review remains.
5. Add the HTTP and reconnectable event-stream gateway. Done on the active
   implementation branch.
6. Ship the browser P0 loop and its deterministic restart test. Done except for
   browser-driven automation.
7. Build P1 vertically, beginning with participant-scoped access and shared,
   renderer-neutral map annotations before fog and visibility depend on them.
   Durable pings plus circle, cone, line, and cube templates now complete the
   first browser-facing annotation lifecycle, including explicit deletion.
8. Add durable participant-scoped table chat before structured roll cards.
   The append-only chat log, HTTP/SSE boundary, moderation policy, and
   open-local and protected private-audience compositions are implemented.
9. Add the scene-library metadata lifecycle and browser manager. Done for
   create, duplicate, activate, explicit-safe archive, import, and export;
   combat-session/map attachment remains a separate open boundary.
10. Add durable participant presence. Done for open-local and protected tables,
    including server-owned epoch timestamps, multi-client aggregation,
    reconnectable sanitized signals, optimistic retries, and safe browser UI.
11. Complete engine-bound roll finalization and project authoritative cards.
