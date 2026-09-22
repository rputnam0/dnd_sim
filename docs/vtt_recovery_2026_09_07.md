# Standalone VTT recovery checkpoint — 2026-09-07

The previous VTT checkout under the operating system's temporary directory was
no longer present when work resumed. The original engine checkout was preserved
without modification. VTT work now lives in a durable sibling checkout on
`codex/vtt-standalone-recovered`, based on
`ddf163279bc9c31b167d073bd66933886e99c1ef`.

## Recovery evidence

- Git references, stashes, and unreachable objects did not contain the later
  uncommitted VTT source.
- A read-only audit identified 704 successful historical patch events across
  18 local task logs. Only patches with a recorded successful application were
  replayed; 20 failed attempts were excluded.
- Static patch extraction and narrowly parsed formatting operations recovered
  872 successful patch/format calls. Historical JavaScript and arbitrary shell
  commands were not executed.
- Dependency declarations and lockfiles were restored through their original
  package-manager operations. Environments and tool caches are not source.
- The original generated Echo Vault map was recovered byte-for-byte. Its
  SHA-256 is
  `90ece48257967087c27ac6ae2da497434526f88811242b9ae7a267cbee0d6b89`.
- Raw task logs, extracted manifests, recovery scripts, credentials, and local
  database files are not included in this repository.

## Resume checks

The recovered installation identity (39 tests), world catalog (36 tests), and
reusable content (71 tests) foundations passed. Eight previously unfinished
integration-normalization cases reproduced before correction; the corrected
integration boundary now passes 83 focused tests. The four foundations together
pass 229 tests. The runtime-logger ownership check also passes after restoring
the missing catalog/integration logger declarations.

Recovery is not a product-completion claim. The next vertical slice is the
administrator setup/login/dashboard journey. World provisioning, table launch,
participant invitations, actor deployment, and complete world backup/restore
remain explicit product gates in `foundry_north_star_plan.md`.
