# Program Status Board

Status: canonical  
Owner: program-control  
Last updated: 2026-03-05  
Canonical source: `docs/program/backlog.csv`

Use this document as the human dashboard.  
Use `docs/program/backlog.csv` as the task-level source of truth for status, dependencies, owners, and branch names.

Legend: `not_started` | `in_progress` | `blocked` | `pr_open` | `merged`

## Merged baseline history

| Baseline scope | Status | Notes |
|---|---|---|
| Waves 1 through 4 | merged/completed | Backfilled as merged baseline history. |
| Repo cleanup program | merged/completed | Backfilled as merged baseline history. |
| Legacy decommission program | merged/completed | Backfilled as merged baseline history. |

## Active completion tracks

| Track | Scope | Status | Milestone | Notes |
|---|---|---|---|---|
| DOC | Documentation Control | merged | 5A-doc-control | `DOC-01` through `DOC-06` are `merged` in `backlog.csv`; Documentation Control track is complete. |
| ARC | Runtime Decomposition | not_started | 5B-runtime-decomposition | All ARC tasks are `not_started` in `backlog.csv`. |
| CAP | Capability Manifest | not_started | 5C-capability-manifest | All CAP tasks are `not_started` in `backlog.csv`. |
| OBS | Replay, Logging, and Observability | not_started | 5D-observability | All OBS tasks are `not_started` in `backlog.csv`. |
| DBS | Persistence and Query Model | not_started | 5E-persistence | All DBS tasks are `not_started` in `backlog.csv`. |
| AI | Tactical AI Hardening | not_started | 5F-ai-hardening | All AI tasks are `not_started` in `backlog.csv`. |
| FIX | Rules Closure | in_progress | 5G-rules-closure | `FIX-01`, `FIX-02`, and `FIX-06` are `in_progress`, while `FIX-03` and `FIX-05` are `pr_open` in `backlog.csv`; remaining FIX tasks are `not_started`. |
| WLD | World Systems and Campaign Platform | not_started | 5H-world-systems | All WLD tasks are `not_started` in `backlog.csv`. |
| FIN | Completion Gates | not_started | 5I-completion-gates | All FIN tasks are `not_started` in `backlog.csv`. |

## Active branches

| Task ID | Branch | Owner | Status | Notes |
|---|---|---|---|---|
| FIX-01 | `codex/feat/fix-01-close-lucky-attacker-defender-and-saving-throw-cor` | rules_a | in_progress | Closing Lucky correctness for attacks by/against Lucky characters and failed saving throws with deterministic reroll selection and luck-point accounting. |
| FIX-02 | `codex/feat/fix-02-close-great-weapon-master-and-sharpshooter-toggle` | rules_b | in_progress | Closing deterministic GWM/Sharpshooter toggle correctness for damage math, hit modifiers, and legality under advantage/disadvantage. |
| FIX-06 | `codex/feat/fix-06-close-rage-damage-resistance-and-illegal-state-edg` | rules_f | in_progress | Closing Rage damage bonus, resistance scope, illegal activation, and concentration edge-case correctness with deterministic tests. |
| FIX-05 | `codex/feat/fix-05-close-mage-slayer-and-sentinel-reaction-constraint` | rules_e | pr_open | Deterministic Mage Slayer/Sentinel reaction-constraint rules and correctness tests are in PR review. |
| FIX-03 | `codex/feat/fix-03-close-shield-master-reaction-save-and-shove-correc` | rules_c | pr_open | Shield Master save bonus, shove sequencing, and illegal-window correctness helpers/tests are implemented and under review. |

## Open PRs

| Task ID | PR | Owner | Gate status | Notes |
|---|---|---|---|---|
| FIX-05 | [#114](https://github.com/rputnam0/dnd_sim/pull/114) | rules_e | pending | Trigger-window, reach/opportunity, and reaction-lockout correctness updates are under review. |
| FIX-03 | [#115](https://github.com/rputnam0/dnd_sim/pull/115) | rules_c | pending | Adds Shield Master save bonus, bonus-shove timing/sequence legality, and reaction-window correctness tests. |

## Dependency and blocker notes (from backlog.csv)

- `DOC-02`, `DOC-03`, `DOC-04`, and `DOC-06` depend on `DOC-01`.
- DOC dependencies in Track 5A are satisfied (`DOC-01` and downstream DOC tasks are merged).
- No active DOC blockers remain; FIX-01, FIX-02, and FIX-06 rules-closure work are currently in progress on assigned branches.
- `FIX-02` is active and depends on `ARC-04` and `AI-01` per `backlog.csv`.
- `FIX-06` is active and depends on `ARC-05` per `backlog.csv`.
- `FIX-03` is in PR review and depends on `ARC-06` per `backlog.csv`.
- `FIX-05` is in PR review and depends on `ARC-06` per `backlog.csv`.
- Dependency links are informational here; canonical task state remains in `docs/program/backlog.csv`.
