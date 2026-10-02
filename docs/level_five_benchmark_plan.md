# Level-five encounter validation milestone

Status: in progress  
Owner: simulation-validation  
Last updated: 2026-10-02

## Outcome

Create a reproducible four-character level-five combat benchmark using the shared
engine. Ship explicit character loadouts, varied encounters, source-grounded
mechanic checks, complete tactical declarations, independently seeded trials,
95% confidence intervals, and recorded authoritative rolls. Difficulty claims
apply to this declared rules/loadout/policy envelope, not all D&D parties.

## Checklist (L5-01)

- [ ] Author party and encounters with a finite mechanic/evidence inventory.
- [ ] Prove the used rules with deterministic, independently calculated cases;
      fix regressions exposed on this supported path.
- [ ] Add tactical action/bonus/movement/reaction/resource planning and policy
      comparisons without changing the legacy strategy's default behavior.
- [ ] Add independent trial seeds, Wilson intervals, outcome/resource summaries,
      and observational roll capture with deterministic replay checks.
- [ ] Run encounter stress sweeps and preserve reports, compact trial data,
      representative roll transcripts, provenance, and limitations.
- [ ] Pass focused and full tests, formatting and relevant repository gates;
      commit logical blocks and open a reviewable PR.

Items become checked only after their verification passes and they are in a PR.

## Acceptance

- Four level-five archetypes: fighter, rogue, cleric, wizard. Publish precise
  equipment, resources and modeled combat options; identify excluded features.
- Encounter set spans melee, ranged/cover, area effects, a durable boss, pressure
  on healing/death saves, and sequential resource attrition.
- Every enabled mechanic has named executable evidence; engine errors fail runs
  rather than becoming losses or being silently skipped.
- Complete turns can combine legal primary and bonus actions with movement and
  explicit reaction policy; bonus-spell restrictions and shared resources hold.
- Trial identity and seed survive batching/reordering. Recording rolls consumes
  no additional RNG. Sampled transcripts replay exactly from recorded seeds.
- Fixed sample sizes are declared before final runs. Confidence intervals measure
  Monte Carlo uncertainty; policy sensitivity and model limitations stay separate.
- Reports distinguish defeat, true party death, downing, death, and censoring,
  and include rounds, HP, resource distributions and action/roll diagnostics.

## Progress and handoff

Branch: `codex/level-five-encounter-benchmark`, based on
`codex/vtt-world-preparation-launch` at `fd9e12f`. Initial baseline: 2057 Python
tests passed. Implemented party, eight encounters, policy profiles, rule evidence,
independent sampling, Wilson intervals, roll capture and exact replay. Six shared
runtime defects found through prescribed-dice checks have been repaired.

Pre-sweep validation: 2114 Python tests passed in 26.49s (seven existing seaborn
deprecation warnings); Black and diff whitespace checks passed. Fixed final design:
1000 trials per encounter/policy, eight encounters, three policies, seed20261002.
The first sweep was interrupted and excluded after transcript review found a
same-weapon pairing in the rogue planner. That guard is fixed. Serial/parallel
equivalence passes; the corrected sweep uses four processes with unchanged fixed
sample sizes and seeds. Artifact inspection and PR delivery remain pending.
