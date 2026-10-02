# What this milestone establishes

The shared engine now has a reproducible, bounded level-five combat benchmark:
four generated characters, eight encounters, three tactical policies, and 24,000
completed trials. There were no engine errors or round-limit outcomes in the
corrected sweep. The [audit](audit.json) recomputed every outcome count, checked
HP/resource bounds and 2,851 source fingerprints, and replayed all 38 saved
transcripts exactly. The mechanic inventory ran 121 tests; the full suite passed
2,114 tests.

Read the [full report](report.md) for intervals, resource distributions and policy
comparisons, and the [roll excerpts](rolls.md) for actual decisions and dice.
These are measurements of the declared loadouts and policies; they are not
calibrated estimates for arbitrary human parties.

## Difficulty findings

For the typical policy, 1,000 trials per encounter:

| Encounter | Victory, 95% Wilson interval | Any member downed | Any confirmed death |
|---|---:|---:|---:|
| Clustered raiders | 100.0% [99.6, 100.0] | 0.0% | 0.0% |
| Three veterans | 99.7% [99.1, 99.9] | 49.4% | 0.9% |
| Archers behind cover | 100.0% [99.6, 100.0] | 23.1% | 0.0% |
| Cinder Sentinel | 97.0% [95.7, 97.9] | 70.6% | 3.2% |
| Six veterans | 6.5% [5.1, 8.2] | 99.6% | 14.8% |
| Spread raiders | 100.0% [99.6, 100.0] | 0.0% | 0.0% |
| Three waves, no rest | 99.9% [99.4, 100.0] | 34.4% | 0.4% |
| Five veterans | 34.7% [31.8, 37.7] | 97.9% | 18.0% |

The model exposes a steep difficulty increase as veterans are added. Five veterans
produce a useful intermediate failure case. Policy changes matter: their victory
rate ranges from 33.5% to 40.4%, while six veterans remain severe at 5.9–9.7%.

Victory rate hides costs. Against the boss, the cleric spends an average of
3.97 first-level, 2.19 second-level, and 0.79 third-level slots. Against the
archers, the wizard spends almost both third-level slots (mean1.99). These fights
can be costly even when the party usually wins. Spreading the raiders increases
mean duration from 2.21 to 3.09 rounds under this policy; the geometry comparison
also changes spell spending and cannot be reduced to an enemy-count label.

Observed death is not a monotonic danger score: five veterans cause more confirmed
deaths than six in the typical-policy sample, despite fewer defeats. Five-veteran
fights last longer (8.5 versus 6.6 mean rounds); earlier all-unconscious termination
is a plausible contributor to the difference. This is an inference, not a causal
decomposition. Eventual party death cannot be estimated from these stopping rules.

## What improved

The benchmark found six shared-runtime defects: dropped spell attack/self-target
fields, area victims filtered back to the anchor, dropped enemy area geometry,
off-hand declarations failing after a primary kill, missing Shield expenditure
accounting, and area damage skipping unconscious creatures. Each repair has a
focused regression. The tactical planner also now accounts for standing movement
and distinct main/off-hand weapons.

The reports distinguish defeat, downing, confirmed death and unresolved trials;
they preserve actual resource expenditure and reproducible seeds. Statistical
uncertainty is separated from policy differences and incomplete modeling.

## Remaining priorities

1. **Broaden the verified loadouts.** Add concentration/control spells, common
   cleric offensive options, and selected subclass features through the same
   prescribed-dice checks. This party intentionally omits those features.
2. **Improve and calibrate tactics.** The planner has no multi-turn resource
   horizon, resistance-aware spell choice, attack retargeting, or bonus-first
   movement. A conservative wizard can finish a loss with unused slots. Compare
   recorded choices against curated human tactical examples before treating the
   policy as representative of players.
3. **Strengthen unrestricted declaration validation.** The benchmark enforces
   different light weapons for its off-hand combinations. The general engine's
   off-hand predicate still checks only an Attack action and the bonus weapon's
   light/melee properties; arbitrary declarations outside this planner need
   stronger primary-weapon validation.
4. **Model post-defeat outcomes if TPK probability is needed.** Continuing death
   saves, finishing attacks, stabilization, capture and rescue requires a defined
   encounter-end policy. The present report deliberately stops at combat defeat.

The [scope and source document](../../../docs/level_five_benchmark.md) lists the
remaining rules, equipment, geometry and information assumptions. Passing this
benchmark is evidence for this combat slice, not full 2014 rules parity.
