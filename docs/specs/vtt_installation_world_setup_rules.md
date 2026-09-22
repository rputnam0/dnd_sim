# VTT Installation and World Setup Rules

Status: design gate for the next standalone vertical slice

Last updated: 2026-08-12

## Scope

This slice turns a process containing one bundled demonstration table into an
installation that can own multiple original worlds. It covers first-run
administration, a world dashboard, explicit launch/return transitions, and
participant invitations. Reusable actor/item documents and portable backups
are adjacent stores with separate acceptance gates.

## Installation states

An installation is exactly one of:

- `uninitialized`: no administrator exists and table/world APIs are unavailable;
- `ready`: one or more active administrators exist and the setup claim is
  permanently disabled; or
- `safe_mode`: durable metadata is readable by an administrator, but world
  launch and mutation are disabled because integrity or migration validation
  failed.

The server must never manufacture a plausible ready state when installation
metadata is absent, malformed, partially written, or from an unsupported
version.

## First-run claim and authentication

- The process creates a cryptographically random, one-time bootstrap claim and
  reveals it only to the local operator channel. It is not stored in plaintext,
  placed in a URL, logged after claim, or returned by a discovery endpoint.
- Setup authenticates the bootstrap claim before validating administrator or
  world payload details. A successful claim is atomic and cannot be replayed.
- Administrator passwords are never stored. A memory-hard standard-library
  password derivation stores a per-account random salt, explicit parameters,
  and derived verifier. Comparisons are constant-time.
- Login returns a random, short-lived, revocable bearer session. Persisted
  session state contains only a hash and expiry; a restart may revoke all
  sessions. Passwords and bearer values never enter world events or browser
  storage.
- Authentication failures use one stable identity-free response. A bounded
  per-principal/source attempt budget fails closed without revealing whether an
  account exists.
- Password reset and adding/removing administrators require an already
  authenticated administrator. There is no insecure recovery question or
  silent default password.

## World lifecycle

- The catalog is installation-scoped. Every world has an opaque `world_id`, an
  opaque unique `table_id`, a validated display name, fixed engine-native
  `system_id`, and explicit archived state.
- Create reserves both identities before initializing world-owned stores. A
  world appears launchable only after a durable provisioning receipt proves
  every required store reached its expected empty revision.
- Rename changes metadata only. Archive is irreversible in v1 and never
  deletes bytes. An archived or incompletely provisioned world cannot launch.
- Launch selects one world for the requesting administrator; it does not make a
  process-global active world. Every subsequent table request remains bound to
  its table identity and authenticated principal.
- Returning to setup releases world-owned resources without deleting state.
  Repeated launch/return and process restart must converge on the same durable
  view.
- The bundled Echo Vault content is an explicitly labeled demonstration world,
  created through the same provisioning boundary or imported as a migration;
  it is not the installation identity or an implicit fallback.

## Participants and invitations

- A world starts with the creating administrator as GM. Participant identities
  are durable, but invite secrets and bearer sessions are not public world
  records.
- A GM creates a single-use, expiring invitation scoped to exactly one table
  and requested role. The server stores only its hash. Redeeming it creates or
  binds a participant atomically before returning an ephemeral session bearer.
- Spectator invites cannot own actors. Player ownership references only active
  world actor documents and remains unique per actor.
- Revocation invalidates outstanding invitations and active participant
  sessions without deleting authored content. Role downgrade invalidates GM
  preparation projections synchronously.
- No endpoint accepts a caller-supplied participant identity in place of the
  authenticated principal unless an explicit GM administration contract says
  so.

## Browser journeys

1. An uninitialized installation shows only the setup claim/password form and
   no world or table content.
2. The new administrator creates the first named world, sees it in the world
   dashboard, launches its preparation workspace, and returns to setup.
3. After restart, the administrator logs in, sees the same world, and launches
   the same table identity with no demo fallback.
4. The GM creates a player invitation; a second browser redeems it, joins only
   that world, and receives no GM-only catalog or preparation data.
5. Revoking the player removes access on the next request/stream reconnect;
   stale UI fails closed.
6. Keyboard and screen-reader users can complete setup, create/launch a world,
   generate/copy/revoke an invite, and return to setup. Compact layouts keep the
   primary world action ahead of metadata and administrative tools.

## Hard acceptance gates

- Exact contract/store/API tests cover bootstrap replay, authentication before
  payload validation, password/session secrecy, expiry/revocation, optimistic
  idempotency, partial provisioning rollback/recovery, restart, archive, and
  cross-world isolation.
- Real multi-principal API tests prove a token for world A cannot read, launch,
  stream, or mutate world B and that identity-free errors reveal no catalog
  membership.
- Mounted browser tests and one real-browser journey cover every state above,
  including interrupted setup/login/world hydration with no plausible fallback.
- Corruption enters explicit safe mode; it never initializes over or rewrites
  the damaged installation.
- Full backend/browser suites, Black, ESLint, production build, diff check, and
  one fresh adversarial critic pass are green before composition is accepted.

## Deliberate non-goals for this slice

- OAuth/social login, public account recovery, billing, marketplace identity,
  and internet-facing multi-tenant administration.
- Cross-process clustering or simultaneous writers beyond SQLite's documented
  single-installation transaction model.
- Automatic conversion of external provider identities into local users,
  actors, entitlements, or credentials.
