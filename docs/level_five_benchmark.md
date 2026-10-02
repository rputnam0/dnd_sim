# Level-five encounter benchmark (L5-01)

This is a bounded, reproducible combat benchmark for the shared simulation engine.
It supplies a party, eight public scenarios, complete tactical declarations,
source-based rule checks, independent trials, difficulty intervals, and replayable
roll records. It does not use the Ley Heart custom simulator.

The [plan](level_five_benchmark_plan.md) tracks delivery. The generated
[difficulty report](../artifacts/benchmarks/level_five/report.md) and
[roll excerpts](../artifacts/benchmarks/level_five/rolls.md) contain the measurements.

## Party and declared scope

All characters are level 5 with proficiency +3. HP uses maximum first-level dice
and fixed average gains thereafter. Each standalone encounter begins at full HP
and resources; the attrition scenario carries them through three waves without rests.

| Character | HP / AC | Enabled combat loadout |
|---|---|---|
| Mara Stone, fighter | 49 / 18 | STR18, CON16; chain mail and shield AC; longsword +7, d8+4 slashing; javelin +7, d6+4; two attacks; one Action Surge; one Second Wind d10+5 |
| Kestrel Reed, rogue | 38 / 16 | DEX18, CON14; studded leather AC; two shortswords +7, d6+4 main / d6 off-hand; shortbow +7, d6+4; Sneak Attack3d6 once per turn; Uncanny Dodge |
| Iona Vale, cleric | 38 / 18 | WIS18, CON14; chain mail and shield AC; mace +5, d6+2 bludgeoning; Sacred Flame2d8, DexDC15; Healing Word and Cure Wounds at slots1–3 |
| Orrin Ash, wizard | 32 / 12 | INT18, DEX14, CON14; unarmored; dagger +5, d4+2; Fire Bolt +7,2d10; Scorching Ray three attacks +7,2d6 each; Fireball8d6, DexDC15; Shield |

Both casters start with 4/3/2 spell slots. Upcast healing is compiled into explicit
named action variants with the actual slot cost and extra dice. The wizard uses
Scorching Ray only at level2 and Fireball only at level3. Rays and weapon attacks
in one declaration share a target; remaining attacks do not retarget after a kill.
Automatic Shield can consume a higher available slot when lower slots are empty.

These archetypes have deliberately restricted combat menus. No subclass powers,
fighting styles, feats, racial riders, concentration spells, stealth, surprise,
counterspells, magic items, or rest recovery are exercised. Cunning Action and
Arcane Recovery may be inferred in actor metadata but the policies never select
them. Channel Divinity, spiritual weapon, spirit guardians, and other common
cleric options are outside this version. Accordingly these numbers describe this
party, not an average optimized level-five party.

Equipment is represented by explicit combat statistics. Ammunition, thrown-weapon
inventory, drawing/stowing, focus/free-hand requirements, and component supply
are assumed sufficient, not verified by this benchmark. The cleric's STR14 meets
chain mail's requirement. No generated equipment is claimed to be a complete
inventory or character-creation validator.

## Encounter design

Enemy stat blocks are original benchmark fixtures, with no claimed official CR.

| Scenario | Stress dimension |
|---|---|
| 01_raider_patrol | Four clustered HP26/AC13 raiders; easy control and useful Fireball geometry |
| 02_veteran_line | Three HP58/AC17 veterans with two +6,d8+3 attacks; melee pressure |
| 03_archer_cover | Five HP35/AC14 archers, +6,d8+3 at range; half-cover barrier |
| 04_cinder_sentinel | HP240/AC16; fire resistance; two +8,2d10+5 attacks; ranged radius10 fire burst5d6, DexDC15 half, recharge5–6 |
| 05_overwhelming_line | Six veterans; recovery, resource depletion, defeat, and death-save pressure |
| 06_spread_patrol | Same four raiders spread apart; movement and reduced area-spell efficiency |
| 07_attrition | Three raiders, then two veterans, then two more; no rest or HP/resource reset |
| 08_five_veterans | Five of the six veterans at the same positions; intermediate pressure |

All positions and cover volumes are explicit in JSON. Movement and range use
the engine's five-foot grid/Chebyshev distance; sphere membership includes cells whose boxes intersect the sphere. These are declared discretization assumptions. Initiative
is individual d20+Dex, with the engine's additional d20+Dex tie-break roll.
Each wave has a 30-round limit. The battle ends on all enemies dead or every
party member unconscious/dead. There is no post-defeat execution or recovery
simulation. Enemies target conscious opponents; the neutral creature-area templates also affect living
zero-HP creatures, including automatic Dex-save failure while unconscious.

## Tactics and verification

`TacticalPolicy` plans a path, primary action, compatible bonus, and explicit
automatic reactions through the ordinary `TurnDeclaration` engine interface.
It accounts for range, cover, standing from prone, spell slots, bonus-spell
restrictions, Sneak Attack opportunities, rescue healing, off-hand prerequisites,
distinct main/off-hand weapon identities, and friendly fire. If unable to attack
or heal, it advances and Dodges.

Conservative/typical/aggressive policies subtract 6/3/0 score points per spent
slot level or class-resource unit. These are transparent heuristic coefficients,
not fitted estimates of human behavior. Enemies always use the aggressive
coefficient. The planner has exact HP, AC, resources and positions; it does not
preview dice. It has no multi-turn search, resistance-aware spell selection,
safe-retreat planning, arbitrary empty-point area aiming, or bonus-first movement.
Moving before acting follows the engine's present declaration contract.
Automatic reactions are engine rules, not a separately optimized decision tree.

The machine-readable [mechanics inventory](../data/benchmarks/level_five/mechanics.json)
maps every permitted action and shared rule category to named executable evidence.
The CLI runs those checks before simulation and refuses unlisted action plans.
Tests use prescribed dice and independently calculated outcomes for the generated
loadouts, plus existing focused rule tests. Passing them verifies these cases;
it does not prove arbitrary combinations or the full game rules correct.

This milestone exposed and repaired six shared-runtime problems:

1. Spell construction lost explicit multiattack counts and self-inclusion flags.
2. Explicit area anchors were filtered back down to only the selected target.
3. Enemy construction dropped area shape and size.
4. A primary kill invalidated its planned off-hand attack and crashed the turn;
   the now-unnecessary follow-up is canceled without another roll or bonus cost.
5. Shield reduced slots without recording them in resource-spending totals.
6. Creature-area saves excluded unconscious targets; blasts now damage them and
   apply death-save failures as appropriate.

The tactical policy also reserves half speed for standing before planning movement.
A transcript audit found and corrected a planner pairing the same physical
shortsword with itself; it now requires different weapons for two-weapon attacks.
Sample tests reconcile actual slot/resource depletion against reported spending.

## Statistical design and reproducibility

The final design is **1,000 trials × eight scenarios × three policies = 24,000**,
master seed `20261002`, chosen before the final run. The earlier ten-trial pilot
was diagnostic; its results are not pooled with the final run. An interrupted
pre-correction sweep is also excluded. SHA256 derives each
seed from master seed, scenario ID, and trial index. Every trial gets a fresh RNG
and strategy instance. Same-index policies start from the same seed, but divergent
decisions consume different draws; this is not a paired significance analysis.
The CLI uses four worker processes by default (`--workers 1` selects serial execution).
Groups merge in design order; tests compare serial and parallel trial archives
and samples byte for byte.

Every proportion has a two-sided 95% Wilson interval. The worst-case half-width
at n=1000 is about 3.1 percentage points. These are marginal sampling intervals,
not joint guarantees for all cells and not confidence in model realism.
Policy spreads are reported separately. No trials are discarded; engine errors
abort the run, and round-limit outcomes are counted as censored.

The report includes defeat, any downing, any confirmed death, all dead at stop,
rounds, remaining HP, actual resource spending, declared action counts, and
quarter/half/full-sample convergence. Quantiles describe outcome variation.
Recorded examples are the first trial and first example of each additional
terminal outcome in each group; they are intentionally not a random sample.

`trials.jsonl.gz` retains every compact trial. Sample archives retain complete
`TrialResult`s, all authoritative roll-journal facts and actual integer RNG draws.
The roll journal covers attacks, saves, damage and healing; the integer stream
also preserves initiative, recharge and death-save draws that lack rich journal
facts. Journal tokens identify the trial; decision telemetry supplies turn/round
plans separately. Recording is observational and checked against the original
full result. Replaying a saved sample compares result, integer draws and journal.

Provenance includes Python version, rules profile, Git commit, and SHA256 digests
of engine/benchmark sources, fixtures, rule JSON, and dependency files. The runner
loads only the versioned party JSON, avoiding local SQLite character overrides.

```sh
uv run python -m dnd_sim.benchmarks.level_five --trials 1000 --seed 20261002
uv run python scripts/benchmarks/plot_level_five.py artifacts/benchmarks/level_five/summary.json
uv run python -m dnd_sim.benchmarks.level_five --trials 20 --scenario 04_cinder_sentinel --output /tmp/dnd-l5-check
uv run python -m dnd_sim.benchmarks.level_five --replay-sample artifacts/benchmarks/level_five/samples/01_raider_patrol__typical__0.json.gz
uv run python -m pytest tests/test_level_five_rules.py tests/test_benchmark_tactics.py tests/test_benchmark_trials.py tests/test_benchmark_report.py
```

Use a fresh output directory for a different design; do not mix old sample
archives with a new run. Full checks use `uv run python -m pytest`; formatting uses
`uv run python -m black .`.

## Sources

Rules source: [SRD5.1](https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf),
with page/section references and evidence in `mechanics.json`. Statistical source:
[NIST Wilson proportion intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

This work includes material taken from the System Reference Document 5.1
(“SRD 5.1”) by Wizards of the Coast LLC and available at
https://dnd.wizards.com/resources/systems-reference-document.
The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International
License available at https://creativecommons.org/licenses/by/4.0/legalcode.
