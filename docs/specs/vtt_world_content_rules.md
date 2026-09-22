# VTT Reusable World Content Rules

Status: active foundation specification

Last updated: 2026-08-12

## Scope

This slice adds original reusable actor and item documents to a world. These
are preparation records, not live encounter actors. They must be safe to edit,
search, share, package, and later deploy through an explicit engine adapter.

## Identity and lifecycle

- Every record is scoped to one `table_id` and has an opaque stable local ID.
  External-provider IDs may appear only in optional provenance.
- Actor and item IDs are permanently unique within their kind, including after
  archive. Active names are Unicode-normalized and unique within kind.
- Create/update/archive commands are revision checked, exactly idempotent, and
  append one canonical event. Archived records are immutable in v1.
- Records are append-only projections backed by a verifiable history and
  recover identically after restart. Corruption fails closed before projection
  or mutation.

## Actor documents

An actor document contains only reusable preparation state:

- name, creature category, size, level/challenge metadata, abilities, armor
  class, maximum hit points, speed modes, senses, languages, traits, action
  definitions, spell/resource maxima, tags, folder, ownership/audience, and
  optional inert notes;
- references to reusable item IDs with bounded integer quantity and explicit
  equipped/attuned preparation flags; and
- optional provider-neutral provenance: provider ID, source-record ID,
  capture/import digest, and attribution.

It never stores current HP, spent resources, initiative, position, conditions,
turn tokens, RNG state, encounter revision, token presentation, or participant
credentials. A deployment snapshot is a separately validated immutable value
derived from one actor revision and explicit deployment choices.

## Item documents

An item document represents reusable equipment, consumables, weapons, armor,
spell-like content, or other bounded rules data. It contains no executable
formula language, HTML, CSS, remote URL, script, or handler name. Rules effects
use an allowlisted declarative shape that the engine adapter must independently
validate before deployment.

An item cannot be archived while an active actor inventory references it unless
the command explicitly supplies and previews a deterministic detach/replacement
plan. The v1 foundation may conservatively reject archival instead.

## Audience and projection

- A GM may read and edit every world record.
- A player may read an actor explicitly assigned to them and the active items
  referenced by that actor, plus records whose audience includes all players.
- A spectator sees only explicitly spectator/public reference material, never
  actor ownership or GM notes.
- Search runs after audience projection and only across safe displayed fields.
  Hidden names, tags, folder IDs, provenance, inventory references, and match
  counts are absent rather than masked.
- Updates that narrow an audience require a privacy-safe invalidation path for
  already hydrated clients when APIs/SSE are added.

## Bounds and inertness

- Maximum active records: 1,000 actors and 10,000 items per table.
- IDs, names, tags, notes, actions, inventory rows, nested rules data, and total
  encoded bytes have explicit finite limits. Numbers are finite and portable.
- Text rejects control/surrogate characters, active markup, executable/data
  URIs, remote locations, and credential-like keys or values at every nested
  level.
- Tags and all set-like relationships are sorted, unique, and compared by code
  point rather than locale.

## Engine boundary

- Content contracts do not import or call the live combat engine.
- A later adapter accepts one exact actor document revision plus resolved item
  revisions, validates them against engine-native construction rules, and
  returns either a complete deployment preview or structured failure.
- Deployment commit binds that preview, creates live state only inside the
  authoritative session transaction, and records source document revisions.
- Editing a reusable actor never silently mutates an already running encounter;
  updating a deployed actor is an explicit previewed command.

## Acceptance fixtures

1. Strict Python codecs reject extra fields, coercion, non-finite values,
   controls/surrogates, active content, credentials, oversize structures,
   duplicate/unsorted tags, and live-runtime fields.
2. Store tests cover create/update/archive, exact retry/conflicting command,
   stale revision, restart, capacity, normalized-name collision, ID reuse,
   inventory referential integrity, item archive rejection, transaction
   interruption, and modified/removed/reordered history.
3. Projection/search matrices cover GM, assigned player, unrelated player, and
   spectator with absence assertions for every hidden relationship.
4. A pure deployment-snapshot test, if present, proves identical actor/item
   revisions produce identical inert input and that no RNG or runtime state is
   accessed.
5. Contracts/store stay route-, filesystem-, network-, and engine-runtime-free;
   API/browser/deployment composition receives separate critic passes.
