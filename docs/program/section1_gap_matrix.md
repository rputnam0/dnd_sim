# Section 1 Gap Matrix

Status: canonical  
Owner: program-control  
Last updated: 2026-03-09  
Canonical source: `docs/program/README.md`

This matrix translates the product definition in `docs/roadmap/part_1.md` into a current-state
audit for the live repository. It is the canonical bridge between the Part 1 product target and
Wave 8 Section 2 stabilization work.

## Gap Matrix

| Product pillar | Current repo coverage | Missing product layers | Evidence | Wave 8 closure path |
|---|---|---|---|---|
| Authored adventure first | Partial CRPG-core encounter and campaign sequencing support exists. | No authored dialogue runtime, no creator-facing story packaging, no polished one-shot proving authored rails plus off-rail play. | `src/dnd_sim/campaign_runtime.py`; `src/dnd_sim/encounter_script.py`; `river_line/encounters/` | `8A` truth reset; `8C` creator-boundary hardening; defer dialogue/runtime build until after Wave 8 gates. |
| Tabletop DM feel | Not represented as a governed runtime role. | No AI DM contract, narration policy, canon governance, or explainability surface specific to DM decisions. | `docs/roadmap/part_1.md`; no equivalent runtime module in `src/dnd_sim/` | Wave 8 explicitly defers AI DM implementation and preserves this as a post-stabilization gap. |
| Trustworthy tactical play | Strong deterministic kernel with replay, legality, spell, item, class, and exploration support. | Oversized runtime concentration still makes the authoritative core harder to extract and audit than it should be. | `src/dnd_sim/engine_runtime.py`; `src/dnd_sim/action_legality.py`; `src/dnd_sim/replay.py` | `8D` narrows runtime responsibilities and records truthful waivers while preserving determinism. |
| Real deviation with consequence | Persistent world-state, branching encounters, exploration interactions, and campaign saves exist. | No governed persistent AI-generated side content model, no authored off-rail conversation runtime, no stable public content contract. | `src/dnd_sim/world_state.py`; `src/dnd_sim/snapshot_store.py`; `src/dnd_sim/exploration_interaction.py` | `8C` splits public content from internal harnesses; `8E` tightens persistence/data contracts. |
| Creator-controlled flexibility | Internal content authoring is powerful but too code-centric. | Creator/public content still needed executable escape hatches and loose scripting surfaces before Wave 8. | `src/dnd_sim/io_runtime.py`; `src/dnd_sim/io_models.py`; `river_line/encounters/ley_heart/internal_harness/` | `8B` removes machine-local assumptions; `8C` fences Python hooks into internal-only harness paths. |
| Options-first, freeform-second | Tactical and exploration interactions are structured and replayable. | No public conversation runtime, no DM-mediated freeform translation layer, no presentation layer for open conversation. | `src/dnd_sim/exploration_interaction.py`; `src/dnd_sim/social.py` | Deferred until after Wave 8; current wave only protects the authoritative core those systems will depend on. |
| Creator promise | Repo has canonical data, capability manifests, regression content, and internal tooling. | No non-technical creator toolchain, no safe packaging boundary, no publish/validate/editor workflow. | `docs/program/capability_report.md`; `scripts/content/`; `docs/program/roadmap_2014_backend.md` | `8A` documents the gap truthfully; `8C` establishes the public-content boundary required before creator tooling. |
| Desktop-first one-shot prove-out | Sample/regression content exists and Phase 2 can run as public portable content after Wave 8 portability changes. | No finished product prove-out that combines authored story, AI DM, tactical trust, and persistent consequence in one coherent player experience. | `river_line/encounters/ley_heart/scenarios/ley_heart_phase_2.json` | Wave 8 stops at authoritative-core readiness and explicitly does not claim the one-shot product fantasy is complete. |

## Governing interpretation

The repository is the candidate authoritative core for the Part 1 product. It is not yet the
full Part 1 product backend, and Wave 8 exists to make that distinction explicit, testable, and
safe to build on.
