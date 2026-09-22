# VTT Workspace Shell Rules

Status: active implementation specification

Last updated: 2026-08-12

## Scope

This slice composes the existing encounter map and feature panels into a
persistent tabletop workspace. It changes presentation ownership only. It does
not change engine, scene, token, visibility, chat, journal, or media authority.

## Roles and workspaces

- A `gm` has Play and Prepare workspaces.
- A `player` has Play only.
- A `spectator` has Play only and receives only read-only capabilities already
  present in the projected panels.
- Changing role immediately revalidates the active workspace and panel. A
  previously selected GM-only panel must not remain rendered during a role
  downgrade.

Play surfaces are combat, actions, chat, journal, participants, presentation,
and rules events. Prepare surfaces are scenes, tokens, visibility, journal, and
presentation. A panel may be available in both modes but has one stable ID.

## State and persistence

- Workspace mode and active panel are presentation-only.
- The map slot is identity-stable across every mode and panel transition.
- A strict preference codec accepts only known mode and panel IDs.
- Preferences are scoped by role and may use local storage.
- Credentials, participant IDs, actor IDs, session/table IDs, private content,
  projections, and API payloads must never be persisted by the shell.
- Invalid, stale, or now-unauthorized preferences fall back to the first
  authorized surface without rendering the invalid panel for a frame.

## Layout and access

- DOM order is: app status, map, primary actions, authorized workspace panel,
  auxiliary navigation. CSS may position these differently on wide screens.
- The map and primary actions remain mounted while auxiliary panels switch.
- The compact layout keeps map and primary actions before preparation and
  activity surfaces.
- Connection state, revision, role/display name, active scene, and encounter
  round have a compact representation; responsive CSS must not simply hide
  them.
- Skip links target the map, primary actions, and current workspace panel.

## Navigation semantics

- Workspace-mode controls use native buttons or tabs with an explicit selected
  state.
- Panel navigation uses a labeled tablist. Every tab has an accessible name and
  `aria-selected` state and points to one tabpanel.
- Left/Right and Home/End move tab focus; Enter/Space activates when manual
  activation is used. Native click remains supported.
- Switching a panel by mouse or shortcut does not steal focus into its content.
- The selected panel heading is present even while its domain is loading or
  unavailable.
- A consolidated polite announcement identifies workspace and panel changes;
  domain errors keep their existing assertive semantics.

## Security and authority

- Panel filtering is presentation defense in depth, never authorization.
- The server remains responsible for every read and mutation permission.
- The shell receives already-created domain controllers and React content; it
  does not construct bearer headers or inspect event payloads.
- The shell cannot synthesize actor, token, scene, or encounter state.

## Acceptance fixtures

Mounted tests must prove:

1. switching Chat → Journal → Participants preserves the same map and primary
   action component instances;
2. GM Play → Prepare exposes the expected panel set and returning to Play
   restores an authorized play panel;
3. downgrading GM → player while a preparation panel is selected synchronously
   removes Prepare and renders no GM-only panel;
4. spectator navigation contains no preparation surface;
5. invalid persisted IDs are rejected and valid non-sensitive IDs round-trip;
6. no persistence write contains any supplied credential-like or table identity
   value;
7. skip links and tab/tab-panel relationships are exact; and
8. source/CSS regression proves compact DOM order and a visible compact status
   strip.
