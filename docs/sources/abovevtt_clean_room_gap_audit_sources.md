# AboveVTT Clean-Room Gap Audit — Sources

Audit date: 2026-08-11

Scope: compare observable product capabilities in AboveVTT with the current
`dnd_sim` VTT. AboveVTT source is evidence of feature existence only. It is not
an implementation input. No source, asset, schema, algorithm, identifier, or UI
expression from AboveVTT may be copied into this repository.

## Source Inventory

| citation_id | source_id | title | year | type | classification | confidence_tier | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CIT-001 | abovevtt-store-1.58 | AboveVTT Chrome Web Store listing, version 1.58 | 2026 | official_doc | official | A | Normative stable-product feature surface; updated 2026-07-27. URL: https://chromewebstore.google.com/detail/abovevtt/ipcjcbhpofedihcloggaichibomadlei |
| CIT-002 | abovevtt-repo | cyruzzo/AboveVTT repository and README | 2026 | repo | official | A | Official repository, product positioning, and AGPL-3.0 license. URL: https://github.com/cyruzzo/AboveVTT |
| CIT-003 | abovevtt-pin-scene | AboveVTT scene and map implementation at commit 05df894b9078a63657c4cbfcf4848271ea00797e | 2026 | repo | implementation_reference | B | Pinned 1.59-beta65 mainline corroboration for scene, media-map, grid, UVTT, and portal capabilities. Repo-only behavior is candidate scope unless stable documentation corroborates it. |
| CIT-004 | abovevtt-pin-table | AboveVTT table implementation at commit 05df894b9078a63657c4cbfcf4848271ea00797e | 2026 | repo | implementation_reference | B | Pinned corroboration for tokens, fog, drawings, visibility, combat, dice, and journal workflows. No code was transcribed. |
| CIT-005 | abovevtt-pin-media | AboveVTT media and presentation implementation at commit 05df894b9078a63657c4cbfcf4848271ea00797e | 2026 | repo | implementation_reference | B | Pinned corroboration for audio, weather, projector, cursor, ruler, and peer-media workflows. |
| CIT-006 | dnd-vtt-product-docs | dnd_sim VTT parity plan and browser README at ddf163279bc9c31b167d073bd66933886e99c1ef | 2026 | official_doc | primary | A | Current intended scope and user-visible behavior. |
| CIT-007 | dnd-vtt-runtime | dnd_sim VTT HTTP, scene, store, and contract implementation at ddf163279bc9c31b167d073bd66933886e99c1ef | 2026 | repo | primary | A | Current shipped branch behavior, including scenes, annotations, chat, presence, authority, and projections. |
| CIT-008 | dnd-engine-runtime | dnd_sim interactive session, spatial rules, and roll journal at ddf163279bc9c31b167d073bd66933886e99c1ef | 2026 | repo | primary | A | Engine capabilities that can support VTT work but are not necessarily exposed as VTT product features. |

`type`: `paper`, `thesis`, `standard`, `official_doc`, `repo`, `benchmark`, `blog`, `other`

`classification`: `primary`, `official`, `secondary`, `implementation_reference`, `unsupported`

Confidence tiers:

- `A`: direct, clear primary or official evidence.
- `B`: useful but partial, beta-only, or implementation-reference evidence.
- `C`: weak support or interpretation risk.

## Discovery And Triage Notes

| entry | purpose | used_for_evidence | note |
| --- | --- | --- | --- |
| Official store listing | Establish stable customer-visible scope | yes | Version 1.58 is the normative parity baseline because the listing represents the stable distributed product. |
| Official GitHub repository | Confirm provenance, positioning, and license | yes | Repository cloned separately at `/private/tmp/abovevtt-cleanroom-review-20260811` and pinned before review. |
| Pinned repository manifest and feature files | Corroborate concrete workflows omitted from short marketing copy | yes, with limits | Pin is version 1.59-beta65. Repo-only features are labeled candidate, not stable requirements. Only capability existence was recorded. |
| `docs/abovevtt_feature_parity_plan.md` | Inventory prior local decisions and work status | yes | Treated as planning evidence, then checked against runtime contracts and tests. |
| `apps/vtt-web/README.md` | Inventory browser workflows and declared limitations | yes | Explicitly documents metadata-only scenes and the absence of asset attachment. |
| Current VTT contracts, stores, APIs, and tests | Verify actual local behavior | yes | Runtime evidence overrides optimistic plan wording. |
| Current engine session, spatial, and roll-journal modules | Identify reusable local foundations | yes | Engine-only behavior is classified partial until it is exposed safely through VTT contracts and projections. |

The upstream checkout is evidence-only and remains outside the project worktree.
Implementation agents should consume this audit and its abstract acceptance criteria,
not inspect the upstream checkout.

## Coverage Against Scope-Locked Claims

| claim_id | required_for_go | supporting_citation_ids | status | gap_note |
| --- | --- | --- | --- | --- |
| CLM-001 | yes | CIT-001, CIT-002, CIT-003 | supported | Stable 1.58 and beta 1.59 surfaces are explicitly separated. |
| CLM-002 | yes | CIT-006, CIT-007, CIT-008 | supported | Current implementation was verified from docs and runtime code. |
| CLM-003 | yes | CIT-001, CIT-003, CIT-004, CIT-005 | supported | Major map, token, visibility, preparation, media, and presentation workflows are covered. |
| CLM-004 | yes | CIT-006, CIT-007 | supported | Present, partial, missing, and deliberate-substitution states are distinguished. |
| CLM-005 | yes | CIT-002 | supported | AGPL implementation is excluded from implementation inputs. |
| CLM-006 | yes | CIT-007, CIT-008 | supported | Proposed slices build on existing local authority, revision, projection, and SSE patterns. |
| CLM-007 | no | CIT-005 | partially_supported | Peer audio/video and DM-screen breadth are candidate parity, not launch blockers. |

## Original vs Adaptation Conflict Log

| conflict_id | original_citation_id | adaptation_citation_id | difference_summary | normative_choice | rationale |
| --- | --- | --- | --- | --- | --- |
| CFG-001 | CIT-001 | CIT-003 | Stable listing is 1.58 while pinned main is 1.59-beta65. | original | Stable documented behavior defines parity; beta-only behavior enters a candidate backlog. |
| CFG-002 | CIT-001 | CIT-006 | AboveVTT is embedded in D&D Beyond; dnd_sim owns its engine and content model. | adaptation | Reproduce user jobs through local actors, content, and sheets without D&D Beyond coupling. |
| CFG-003 | CIT-001 | CIT-007 | AboveVTT exposes broad tabletop tools; dnd_sim begins with authoritative engine-driven play. | adaptation | Preserve server authority and privacy as architectural constraints while closing product gaps incrementally. |
| CFG-004 | CIT-003 | CIT-007 | Upstream implementation details differ from local versioned command/store/projection architecture. | adaptation | Use only local contracts and independently designed domain models. |
