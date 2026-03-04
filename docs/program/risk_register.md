# Risk Register

Status: canonical  
Owner: integration-review  
Last updated: 2026-03-04  
Canonical source: `docs/program/README.md`

## High-risk areas

| Risk ID | Area | Required mitigation | Gate |
|---|---|---|---|
| R-01 | Documentation drift | Merge `DOC-01` through `DOC-05` before any large code track; fail CI on doc drift. | 5A |
| R-02 | Engine decomposition | Extract bounded modules in dependency order and compare deterministic replays before and after every ARC merge. | 5B |
| R-03 | Reaction and timing regressions | Isolate reaction windows in `reaction_runtime.py` and require trigger-order golden tests. | ARC-06 |
| R-04 | Capability false positives | Require explicit unsupported reason codes and tested-state coverage before content is marked executable. | CAP-05 |
| R-05 | Observability overhead | Keep event payloads structured and deterministic; run replay/perf comparisons on every observability merge. | 5D |
| R-06 | Persistence migration breakage | Add forward and rollback migrations with mixed old/new read tests. | 5E |
| R-07 | AI tactical regressions | Require benchmark corpus and rationale traces before AI merges. | 5F |
| R-08 | Rules closure churn | Close feat and rage gaps with deterministic feature-specific tests before broader world-system merges. | 5G |
| R-09 | World-state schema churn | Land canonical state tables before quest, faction, and campaign runtime work. | 5E and 5H |
| R-10 | Completion declared too early | Block completion on every `FIN-*` gate and do not rely on partial checklist state. | 5I |

## Operational rules

- Rebase every hotspot task after any merge touching the same module.
- Preserve replay diff artifacts for any deterministic drift.
- Do not add transitional compatibility shims without a removal task in `backlog.csv`.
- Do not mark a task merged until `status_board.md` reflects the same state.
