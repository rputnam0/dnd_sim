# Foundry Public Product Observation

Observation date: 2026-08-12

Purpose: capability and workflow benchmark for the standalone DND Sim VTT

Boundary: rendered public product/documentation only

## Sources observed

- <https://foundryvtt.com/demo>
- <https://demo.foundryvtt.com/game>
- <https://foundryvtt.com/kb/>

The public demo was joined through its published Player flow and demo
credential. The rendered Introduction, Exploring This Content, and Credits
documents were read. The official knowledge-base index and all 75 linked
article entries were reviewed at the heading/introductory capability level.

No Foundry source repository, packaged application, network/private API,
download, implementation schema, identifier set, or asset was inspected or
used. Product labels below are evidence locators only; local implementation
uses independently designed contracts and visual expression.

## Observable player workspace

- A scene canvas remains the primary surface while contextual tools and
  directories change around it.
- A left canvas rail groups selection, token, measurement, drawing, wall,
  lighting, sound, tile, note, and region jobs.
- A right sidebar exposes chat, combat, scenes, actors, items, journals,
  rollable tables, cards, playlists, and compendia through compact navigation.
- Scene navigation, a bottom hotbar, user/performance status, settings, tours,
  keybindings, and movable document windows support continuous play without a
  page-per-feature workflow.
- Actor directories and folders open reusable sheets; compendia expose reusable
  packaged content; playlists and optional dice presentation remain reachable
  without replacing the canvas.
- Visible roll/chat controls distinguish multiple audience/presentation modes.

## Knowledge-base capability families

The index describes a product wider than the canvas itself:

1. installation, configuration, hosting, storage, backups, and recovery;
2. world creation, users, invitations, permissions, settings, and launch;
3. actors, items, journals, scenes, folders, compendia, cards, tables, and
   reusable document relationships;
4. canvas layers including tokens, walls, doors, lighting, fog, tiles, notes,
   regions, rulers, drawings, sound, camera, and scene controls;
5. dice, chat, macros, hotbars, keybindings, tours, accessibility-adjacent
   personalization, and troubleshooting;
6. systems, modules, packages, manifests, migrations, localization, and content
   authoring; and
7. audio/video, media optimization, browser support, and operational guidance.

## Clean-room gap result

The current repository is comparatively strong where authority matters:
deterministic encounter commands, revisioned persistence, projected privacy,
scene calibration, tokens, visibility, structured rolls, chat/presence,
journals, drawings, and presentation state. Its largest gap is product
composition and reusable campaign lifecycle: setup/worlds/users, actor/item
libraries and sheets, compendia/packages/backups, a persistent workspace,
hotbars/macros/ad-hoc dice, operational tooling, extension boundaries, and
advanced media.

This evidence produced `docs/foundry_north_star_plan.md`. It does not license
or justify cloning Foundry's interface, internal model, or implementation.
