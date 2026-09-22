# Foundry-North-Star VTT Plan

Status: active product and implementation charter

Owner: VTT program

Last updated: 2026-09-22

This plan expands the clean-room AboveVTT parity program into a high-quality,
standalone virtual tabletop. Foundry Virtual Tabletop is a capability and
product-workflow benchmark, not a source-code, schema, asset, naming, or visual
dependency.

## Clean-room observation record

The comparison was performed on 2026-08-12 using only Foundry's public,
rendered product surfaces:

- the official public demo at <https://foundryvtt.com/demo>, joined as a
  published demo Player account;
- the rendered in-product Introduction, Exploring This Content, and Credits
  pages;
- the visible player workspace, scene navigation, canvas tool rail, hotbar,
  chat roll modes, participant/performance display, actor directory,
  compendium browser, audio controls, dice module, and settings surfaces; and
- the 75 rendered entries linked by the official
  [knowledge-base index](https://foundryvtt.com/kb/), including setup,
  documents, canvas, dice/cards, hosting, extension development, and content
  creation.

No Foundry implementation source, private endpoint, packaged asset, internal
schema, or downloadable application artifact was inspected. The result below
describes user jobs and observable capabilities in this product's own terms.

## Gauntlet charter

- **Outcome:** A GM can install or host this product, create an original D&D 5e
  campaign, prepare reusable content and scenes, invite players, and run a
  polished multi-session game without editing Python or database rows.
- **Deliverable:** A standalone web VTT, authoritative Python services,
  durable world data, original interface and assets, optional provider-neutral
  character import, operator workflows, and reproducible evidence.
- **Primary quality bar:** The player and GM journeys represented by the
  Foundry public demo and knowledge-base capability taxonomy, implemented with
  this repository's deterministic engine and security model.
- **Hard gates:** Server authority; deterministic preview/commit; restart and
  replay recovery; authentication before protected-input validation;
  per-recipient privacy; bounded media and geometry; stable identity-free
  errors; clean-room provenance; keyboard and screen-reader workflows;
  reduced-motion and high-contrast support; responsive map-first interaction;
  production build, backend/browser tests, lint, format, and diff checks.
- **Evidence:** Contract/store/API tests; real-driver encounter tests;
  restart/import/export fixtures; mounted component workflows; multi-principal
  browser journeys; automated accessibility and viewport checks; visual
  baselines; performance budgets; fresh-context critic verdicts.
- **Operating envelope:** Modern desktop Chromium/Firefox/Safari first; a
  responsive tablet/phone companion workflow; one GM plus up to ten connected
  players or spectators per table; hundreds of scenes, thousands of reusable
  content records, hundreds of tokens per active scene, four-hour sessions,
  bounded first-party media, and D&D 5e as the first engine-native system.
- **Constraints:** Original product expression. No Foundry or AboveVTT source,
  assets, identifiers, layouts, or schemas. No D&D Beyond credential capture,
  private-endpoint scraping, entitlement bypass, redistribution of proprietary
  material, remote-code installation, or untrusted Python execution.
- **Finding promotion rule:** Promote only a reproducible problem in changed
  code or a missing user job in the supported envelope that violates a hard
  gate. Security, privacy, data loss, or legal risk may interrupt immediately.
- **Backlog sink:** `docs/vtt_gauntlet_backlog.md`.
- **Critic budget:** One fresh critic and one focused re-review per vertical
  workstream, followed by an integrated journey critic.
- **Stop control:** Continue in bounded vertical slices until the active slice
  passes all local gates and an independent critic accepts it. Product-wide
  completion requires every P0/P1 workstream below, not merely a polished demo.
- **Autonomy:** Routine architecture, implementation, testing, and corrective
  work are autonomous. Escalate only destructive actions, external publishing,
  materially expanded authority, or unresolved product choices.

## What the public Foundry surfaces demonstrate

Foundry's strength is not one canvas feature. It is the composition of a
persistent tabletop workspace, reusable world documents, extensible rules
packages, and operator tooling.

| Capability family | Observable product job | Current `dnd_sim` state | Gap priority |
|---|---|---|---|
| Workspace | Keep the scene canvas present while switching contextual tools, directories, chat, combat, sheets, and movable documents | Capable map and panels are stacked in one long Echo Vault page | P0 |
| World lifecycle | Install/configure, create a world, create users, launch, invite, return to setup, and recover | One hard-coded solo table composition | P0 |
| Actors and items | Create reusable protagonists, NPCs, monsters, equipment, spells, effects, and actor sheets | Runtime encounter actors exist; no safe reusable world actor/item documents | P0 |
| Scene preparation | Create scenes; place maps, walls, lights, tiles, notes, sounds, regions, tokens, and weather by canvas layer | Strong scenes, maps, tokens, fog, barriers, lights, drawings, pins, and sound; no tiles, regions, weather, or visual authoring workflow | P1 |
| Combat and rolls | Select/target/move tokens; use sheets; resolve encounter order; emit rich roll/chat results | Strong authoritative combat, movement, tracker correction, and structured roll cards | Strong foundation |
| Chat and social | Public/private/blind/self roll modes, in/out-of-character chat, participants, A/V | Public/private chat and presence; no user-selectable ad-hoc roll modes or A/V | P1/P2 |
| Journals | Searchable multi-page handouts, links, permissions, map notes, movable reader/editor | Structured audience-safe journal, links, pins, search; no rich multi-window editor | P1 |
| Libraries | Folders, compendia, reusable packs, import/export, adventure bundles | Journal folders and scene metadata export only | P0 |
| Automation | Hotbar, chat/dice macros, rollable tables, cards, scene-region behaviors | No authoritative ad-hoc dice, macro intents, roll tables, cards, or region behavior system | P1/P2 |
| Media | Playlists, global/local volumes, positional sound, animated maps/tiles, optimized assets | Durable playlists and private static media; no positional audio or animated visual media | P2 |
| Personalization | Configurable keybinds, client/world settings, tours, layout preferences, localization | Fixed shortcuts and limited local audio preferences | P1/P2 |
| Ecosystem | Systems, modules, manifests, migrations, permissions, content packages, marketplace-quality packaging | No public extension boundary | P1 architecture, P3 execution |
| Operations | Backups/snapshots, restore, safe mode, migrations, hosting/TLS/storage guidance | SQLite durability and restart tests; no world backup/restore UI or production hosting product | P0/P1 |
| Quality | Responsive controls, accessible workflows, performance telemetry and troubleshooting | Good semantic foundations; no real-browser accessibility/visual/performance gate | P0 |

## Product architecture target

```text
VttApplication
├── SetupAndWorlds
│   ├── first-run administrator setup
│   ├── world dashboard and backups
│   └── invite / join / participant management
├── TableWorkspace
│   ├── persistent scene canvas and tool rail
│   ├── play workspace: combat, actions, chat, rolls, participants
│   ├── prepare workspace: scenes, actors, tokens, visibility, journal, sound
│   ├── contextual inspectors and movable document windows
│   └── local layout, keybinding, contrast, and motion preferences
├── WorldDocuments
│   ├── actors, items, effects, journals, scenes, encounters
│   ├── folders, tags, search, compendia, roll tables, macros
│   └── versioned world packages and migrations
├── AuthoritativeRuntime
│   ├── deterministic D&D 5e rules and rolls
│   ├── encounter, spatial, visibility, and audience projection
│   └── idempotent commands, event history, replay, and recovery
└── IntegrationBroker
    ├── provider-neutral import envelope and preview
    ├── scoped, expiring, revocable grants
    └── declarative extension contributions
```

## Ordered vertical workstreams

### P0 — Standalone product foundation

- [x] Replace the long document with a persistent, role-aware workspace shell.
- [ ] Add first-run GM setup, durable worlds/tables/users, invite/join, and world
      switching.
- [ ] Add reusable actor and item documents, actor sheets, actor search, and
      safe actor-to-token/encounter deployment.
- [ ] Add complete versioned world export, previewed import, backup, restore,
      and migration fixtures.
- [ ] Add real-browser GM/two-player journeys, accessibility automation,
      viewport screenshots, and four-hour/session-load budgets.

### P1 — Mature preparation and play

- [ ] Consolidate map tools into one mutually exclusive tool-state machine.
- [ ] Add pan/zoom/fit/fullscreen and direct-on-map scene, token, wall, light,
      fog, sound, and pin authoring.
- [ ] Add scene/actor/item/journal/audio folders, tags, favorites, fuzzy search,
      and reusable compendium packs.
- [ ] Add encounter templates and editable rosters sourced only from validated
      world actors.
- [ ] Add authoritative ad-hoc dice, user-selected roll audiences, hotbar slots,
      and capability-limited macro intents.
- [ ] Add provider-neutral character import with preview, provenance, conflict
      handling, atomic commit, and rollback.
- [ ] Add persistent per-user layout, keybinding, motion, contrast, and
      accessibility preferences without storing table credentials.

### P2 — Advanced presentation

- [ ] Add tiles, overhead layers, animated image/video media, weather, camera
      bookmarks, authored transitions, and positional ambient sound.
- [ ] Add rollable tables, cards/decks, rich journal pages, and bounded
      declarative scene-region triggers.
- [ ] Add optional 3D dice driven only by authoritative roll facts.
- [ ] Add optional consent-based A/V with explicit device controls.
- [ ] Add localization and content-authoring guidance.

### P3 — Extension ecosystem

- [ ] Add strict integration manifests, scoped grants, a provider adapter
      registry, deterministic import envelopes, and declarative UI/command
      contributions.
- [ ] Build an optional D&D Beyond companion only from documented/authorized or
      explicitly user-exported data; never couple provider IDs to core actors.
- [ ] Defer executable third-party modules until an independently verified
      out-of-process or WASM sandbox with brokered capabilities exists.

## Active Gauntlet loop: workspace foundation

The first slice is deliberately architectural. It reuses the existing panels
and server contracts while changing their composition.

Acceptance conditions:

1. The tactical map remains mounted while users switch workspace panels or a
   GM switches between Play and Prepare.
2. Players and spectators cannot navigate to or render GM-only preparation
   panels; GM Prepare mode is explicit rather than inferred from disabled forms.
3. Combat/action controls remain adjacent to the map and before auxiliary
   content in responsive DOM order.
4. Chat, journal, participants, combat, scenes, tokens, visibility, sound, and
   event history are reachable in one navigation action when authorized.
5. Connection, revision, role/identity, active scene, and round remain available
   at desktop and compact widths.
6. Map, actions, and workspace panel have skip targets; tabs expose selection
   and keyboard semantics; panel changes move focus only on explicit request.
7. Only validated non-sensitive mode/panel preferences may persist. Bearer
   credentials, participant projections, and private content never enter local
   storage.
8. Focused mounted tests, the default browser build/test suite, ESLint, and
   `git diff --check` pass before critic review.

Later slices must not be marked complete merely because their controls are
present. Each requires the complete contract, authority, persistence,
projection, accessibility, and recovery path for its stated user job.

### Workspace verdict

Accepted on 2026-08-12 after one adversarial correction wave. The shipped
composition keeps the tactical map, primary command surface, combat tracker,
and every authorized live controller mounted while switching Play/Prepare and
tool tabs. It removes GM-only panels synchronously on role downgrade; exposes
exact tab/tabpanel and active skip-target relationships; preserves matching
DOM/visual order at compact widths; and persists only a strict mode/panel
preference when storage is explicitly supplied. Evidence: production browser
build, 136 browser tests, ESLint, a direct 390×844 browser workflow, and an
independent accepted critic verdict.

## Active Gauntlet loop: worlds and reusable content

The next slice owns self-service campaign data without pretending that a
catalog record alone launches a playable table.

Acceptance conditions:

1. World identities and table identities are opaque, permanently unique, and
   durable across restart; active Unicode-normalized names are unique.
2. World create/rename/archive is append-only, optimistic, exactly idempotent,
   bounded, tamper evident, and safe across all transaction-exit paths.
3. Reusable actor and item records are inert, world/table scoped, audience
   safe, bounded, searchable only through projected text, and contain no live
   encounter state.
4. Actor inventory references validated reusable item IDs; document update and
   archive preserve referential integrity and never synthesize engine state.
5. Launching worlds, participant administration, actor deployment, complete
   packages, backup/restore, and migrations remain explicit later gates rather
   than hidden side effects of this foundation.

The world catalog contract/store foundation passed its first correction wave
and an independent re-review: 36 focused tests cover restart, exact replay,
tamper detection, Unicode scalar validation, and `BaseException` transaction
cleanup. Reusable actor/item contracts and storage now pass 71 focused tests,
including immutable nested documents, inventory reference integrity, audience
projection, search, restart, replay, and normalized inert-text checks. These
remain storage foundations, not actor sheets or deployment.

### Current implementation checkpoint

The previous temporary checkout was recovered into a durable sibling worktree
on 2026-09-07; see `vtt_recovery_2026_09_07.md` for provenance and verification.

The active end-to-end slice is installation administration:

- [ ] Deliver the first-run claim only to the local operator, then claim an
      administrator through an authenticated, bounded setup request.
- [ ] Log in with a revocable memory-only browser session and hydrate the
      authoritative administrator and world catalog.
- [ ] Create, rename, and explicitly archive durable world records with exact
      retry and conflict recovery.
- [ ] Prove lost/unverified authentication, failed hydration, safe mode, and
      logout clear private catalog content. An uncertain authenticated mutation
      may retain its last verified snapshot only with an explicit pending
      notice and disabled mutations; it must never invent success or launch.
- [ ] Pass backend and mounted browser tests, a real browser journey, and an
      independent integration critic before accepting the slice.

The dashboard must clearly label world launch as unavailable until actual
provisioning is implemented. The existing root route remains a separately
labeled demonstration table; it is never used as a created world's fallback.

### Administration verification — 2026-09-22

The setup/login/world-dashboard implementation is present at `/setup` with a
separate loopback administration service. An independent bounded reviewer
accepted the API and browser state machine: 27 backend tests, 17 browser
installation tests, and four additional mounted probes covered authority loss,
safe mode, storage-failure recovery, and late replies after logout. No material
review finding remains in that scope.

The full Python suite passes 2,036 tests. The default browser gate passes strict
TypeScript checking, production build, and 163 tests; ESLint and Black also
pass. A new mandatory browser typecheck
exposed real error-path defects in the recovered journal and sound clients;
10 regressions now prove strict typed errors, recovery details, private-view
clearing, and useful roll-face diagnostics. Test fixtures now satisfy their
actual contracts instead of bypassing missing fields.

Final visual acceptance is still pending: the browser tool reported no
available browser while the Mac was locked on this resume. Do not mark the
administration checklist accepted solely on mounted tests. After browser
verification, the next product slice is real empty-world provisioning and
launch, then participant invitations and validated actor deployment.
