# Participant invitations — Gauntlet slice

Status: implementation in progress; 2026-10-02. Base: `fd9e12f` / PR #264.

## Outcome and boundary

A GM can invite a player or spectator to an original prepared world, show its
published scene, and revoke access without deleting content. This is still an
encounter-free workspace, not a claim of playable campaign or Foundry parity.
The operating envelope is a protected local installation, one initial GM and
up to ten active guests per world. No GM delegation, actor ownership assignment,
public hosting, accounts/password recovery, or provider linkage is added.

Invitations expire after 24 hours and are single use. Guest bearers live only
in process/browser memory, expire after four hours, and do not survive service
restart or page reload. Rejoining requires another invitation. Durable guest
identities and revocations remain visible to the GM. A lost create response is
recoverable by refreshing the list and revoking/replacing its invitation; a
lost redemption response must never allow reuse of a consumed code.

## Shared transport contract

All routes use no-store and the existing identity-free error envelope. Public
invitation records contain `invitation_id`, `role` (player/spectator),
`created_at`, `expires_at`, `status` (pending/redeemed/revoked/expired), and
`participant` (the existing participant contract or null). No secret/hash is
part of those records. Names are bounded canonical display text (1–80 chars).

- World workspace `GET /api/v1/invitations`: GM only; returns
  `{schema_version: "vtt.world_invitations.v1", world_id, table_id, invitations}`.
- World workspace `POST /api/v1/invitations`: GM only; body
  `{command_id, role}`; returns 201
  `{schema_version: "vtt.invitation_issued.v1", invitation, invitation_token,
  replayed}`. Exact retry returns the same record, `replayed: true` and a null
  token (plaintext is not recoverable). Changed command content returns 409.
- World workspace `POST /api/v1/invitations/{invitation_id}/revoke`: GM only,
  no body, idempotent 204; invalidates the pending code and all linked sessions.
- Installation `POST /api/v1/installation/join`: invitation in Authorization
  bearer header, body `{display_name}`; validates the invitation before payload
  details and again on mutation. Returns the existing `vtt.world_launch.v1`
  envelope with the redeemed principal, exact world/table/path, and guest bearer.
- Existing world return endpoint accepts the current guest bearer and ends
  that browser session. It never returns a guest to the GM dashboard.

Invitation state lives in the installation database as a separately versioned
access store; existing world receipt/schema integrity must remain unchanged.
All protected requests, POST body arrival, and scene streams revalidate guest
expiry/revocation/world archive. Players receive only their own table principal
and any explicitly allowed public roster information; no invitation list or
installation catalog. Existing scene/media audience projections remain the
authority. No credentials enter URLs, logs, storage, clipboard automatically,
or event records. Copying a code is an explicit GM action.

## Checklist and acceptance

- [ ] TDD durable hashed invitation state, atomic single use, bounded capacity,
      exact create retry, restart, expiry and idempotent revocation.
- [ ] Compose guest launch and live canonical authority; prove auth-before-body,
      world isolation, GM-only administration, scene/media projection, request
      and stream revocation, return/relaunch and unchanged authored content.
- [ ] Strict browser transport plus GM invite/copy/revoke panel and separate
      join page; memory-only credentials, stale/late reply guards, clear loss
      of access, keyboard and compact-screen workflows.
- [ ] Real two-principal browser journey plus focused mounted/API tests.
- [ ] Full backend/browser tests, typecheck, build, lint, Black, diff check.
- [ ] Fresh bounded Gauntlet critic; at most one focused correction/re-review;
      document evidence, commit logical blocks, open and attach PR.

Promotion follows the existing charter: reproducible candidate-caused failures
of this journey/privacy/recovery bar only. Broader account management, production
deployment, tamper hardening beyond existing store conventions, and unrelated
engine changes stay outside this slice. The independent final review judges
the working artifact, not builder summaries.
