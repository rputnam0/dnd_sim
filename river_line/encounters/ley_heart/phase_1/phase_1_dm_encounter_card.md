# Ley Heart — Phase 1: The Three Anchors (DM Encounter Card)

The Drowned Engine is *present*, but not yet *vulnerable*. Three pylons—Past, Present, and Future—pin the ley current in place. Until those anchors are broken, the Engine cannot be harmed.

## Read-Aloud (Optional)

The chamber thrums like a tuning fork struck underwater. Three pylons stand around a central dais—iron tags and names fused into a memorial spike, a crackling dynamo sealed with a safety band, and a prism that doesn’t quite exist in the same moment twice.  
Above the dais, the Drowned Engine hangs motionless, watching through the current. Your first blows skid off the anchors in showers of sparks.  
If you want the Engine, you’ll have to break time’s moorings first.

---

## Encounter At a Glance

**Win condition:** Destroy all three pylons.  
**Boss in Phase 1:** Stationary, immune to damage, but *actively* punishes mistakes using abilities tied to which pylons remain.  
**Pylon loop:** A pylon is **Resistant** until someone completes its **Procedure** to make it **Exposed**, then the party burns it down while the window is open.

**Boss ability gating (by pylon alive):**
- **Past (Iron Memorial) alive:** Boss can use **Guilt Fog** (Action, recharge) and **Undertow** (Lair).
- **Present (Arcane Dynamo) alive:** Boss can use **Harpoon Winch** (Action) and **Arc Flash** (Lair), plus **Winch Pull** (Legendary).
- **Future (Crystal Prism) alive:** Boss can use **Time Shear** (Action, recharge), **Phase Flicker** (Lair), and **Temporal Reversal** (breakpoint reaction; recharge).

---

## Battlefield & Positioning

Use three pylon nodes evenly spaced around the central dais.

**Suggested geometry (matches current sim assumptions):**
- **Pylon-to-pylon:** 30 ft
- **Boss (center) to each pylon:** ~17 ft

**Tactical pressure:**
- Players who go into melee with a pylon risk **Breakpoint Pulses**.
- The boss tries to **force** someone into the **center** via harpoon + pull, then punishes with close-range options.

---

## Shared Pylon Rules (All Three)

### Pylon Stat Line (tuned for the 3-player party)
- **AC:** 12  
- **HP:** 39  
- **Damage Resistance:** Resistant to all damage while not **Exposed** (halve damage).

### Exposed
- While **Exposed**, the pylon loses its resistance and takes normal damage.
- **Duration (current design):** Exposed **until the end of the exposing creature’s next turn**.
- **Refresh:** If a pylon is already Exposed, further Procedures typically have no effect until it expires (keep the loop clean).

### Breakpoints (and “can’t nova through it” rule)
- Each pylon has two breakpoints: **30 HP** and **15 HP**.
- Hitting a breakpoint triggers a **Breakpoint Pulse** (below).
- **One breakpoint per attack:** If a single hit would cross multiple breakpoints, it stops at the next breakpoint and triggers only that pulse.

### Breakpoint Pulse (All Pylons)
- **Trigger:** When a pylon is reduced to **30 HP** or **15 HP**.
- **Area:** Creatures within **10 ft** of that pylon.
- **Save DC:** 15 (save type varies by pylon).
- **Damage:** **2d6** (type varies by pylon).
- **On success:** Half damage, no rider.
- **On failure:** Full damage + rider.

---

## The Pylons (Procedures + Pulses)

### 1) Past Pylon — Iron Memorial (Roll Call)

Iron tags and names are fused into the column, humming with regret.

**Procedure: Final Roll Call**
- **Bonus Action**, within **5 ft**
- **Check:** DC 13 **Performance** or **Persuasion** or **Religion**
- **Success:** Past pylon becomes **Exposed**
- **Failure:** No effect

**Breakpoint Pulse: Memorial Pulse**
- **Save:** DC 15 **Constitution**
- **Damage:** 2d6 **necrotic**
- **Fail rider:** **No reactions** until the start of the target’s next turn

---

### 2) Present Pylon — Arcane Dynamo (Safety Seal)

A regulator housing thrums with constrained lightning; the seal is intact.

**Procedure: Cut the Safety Seal**
- **Bonus Action**, within **5 ft**
- **Check:** DC 13 **Thieves’ Tools** or **Arcana**
- **Success:** Present pylon becomes **Exposed**
- **Failure:** No effect

**Breakpoint Pulse: Dynamo Pulse**
- **Save:** DC 15 **Dexterity**
- **Damage:** 2d6 **lightning**
- **Fail rider:** **Pushed 10 ft** directly away from the pylon

---

### 3) Future Pylon — Crystal Prism (Sync Dial)

The prism jitters out of phase; an etched dial rotates like it’s searching for the correct timeline.

**Procedure: Set the Sync Dial**
- **Bonus Action**, within **30 ft** and line of sight
- **Check:** DC 13 **Investigation** or **Insight**
- **Success:** Future pylon becomes **Exposed**
- **Failure:** No effect

**Breakpoint Pulse: Prism Pulse**
- **Save:** DC 15 **Wisdom**
- **Damage:** 2d6 **psychic**
- **Fail rider:** **Disadvantage** on the target’s next attack roll before the end of its next turn

---

## The Drowned Engine (Phase 1: Anchored Turret)

**Phase state**
- **Speed 0**, anchored to the central dais
- **Immune to all damage** until all three pylons are destroyed
- **Action economy:** 1 Action on its turn, 1 Legendary Action per round, 1 Lair Action at initiative 20

> **These boss numbers are already “baked” for play.**  
> They incorporate the Phase 1 sim’s balancing sweep (lower DCs / to-hit), and use the boss’s full damage dice (no scalar), so you never need to apply an offset at the table.

### Action Options (choose one each round)

These options are available only while the linked pylon remains alive.

**Harpoon Winch (Present alive)**
- **Attack:** +7 to hit, range 60/180, 1 target
- **Hit:** 2d10+4 piercing/force
- Target is **grappled** (escape DC 16)

**Guilt Fog (Past alive; Recharge 5–6)**
- **Area:** 30-ft cone
- **Save:** DC 14 Con
- **Fail:** 4d8 necrotic and the target **can’t regain HP until the start of the Engine’s next turn**
- **Success:** Half damage, no rider

**Boiler Vent (Recharge 5–6)**
- **Area:** 15-ft cone
- **Save:** DC 14 Con
- **Fail:** 4d8 fire and **pushed 10 ft**
- **Success:** Half damage, no push

**Time Shear (Future alive; Recharge 4–6)**
- **Target:** 1 creature within 90 ft
- **Save:** DC 13 Wis
- **Fail:** 3d8 psychic and **Slowed until end of its next turn**:
  - speed halved
  - no reactions
  - on its turn it can take **either** an action **or** a bonus action (not both)
- **Success:** Half damage, no slow

**Slam (Reach 10 ft; only if someone is in reach)**
- **Attack:** +8 to hit, reach 10 ft, 1 target
- **Hit:** 2d8+6 bludgeoning

### Legendary Actions (1 per round)

Use at the end of a PC’s turn.

**Winch Pull (Present alive; requires a grappled target)**
- Pull the grappled creature **20 ft** (no save)

**Tail Tap (always)**
- 1 creature within 10 ft makes **DC 13 Str** save or is **knocked prone**

**Temporal Reversal (Future alive; Recharge 5–6)**
- **Trigger:** When a pylon would hit a breakpoint (30 or 15 HP)
- **Effect:** Reduce that hit’s damage to the pylon by **10**
- **Recharge:** At the start of its turn, roll 1d6; on a **5–6**, the Engine regains this reaction

### Lair Actions (Initiative 20; 1 per round)

Choose one option tied to an active pylon.

**Undertow (Past alive)**
- Choose a 10-ft square; creatures there make **DC 13 Str** save or are **restrained** until the start of their next turn

**Arc Flash (Present alive)**
- Up to 2 creatures make **DC 13 Dex** save
- **Fail:** 2d6 lightning and **no reactions** until the start of their next turn
- **Success:** Half damage, keep reactions

**Phase Flicker (Future alive; Pylon Defense)**
- Choose 1 pylon: until the next initiative 20 it gains **+2 AC** and **Damage Threshold 5** (ignore hits under 5 damage)

---

## Running Phase 1 Smoothly (Table Procedure)

1) **Initiative 20:** Lair Action (only from pylons still alive).  
2) **Engine’s turn:** Pick the best available Action (based on which pylons are alive and who is exposed / grappled).  
3) **PC turns:** Procedures + attacks; remember Exposed windows.  
4) **Breakpoint Pulses:** Trigger at 30 and 15 HP; resolve immediately.

**Tracking tips**
- Put two tick boxes on each pylon: **30** and **15**. When checked, that pulse is spent.
- Place an “EXPOSED” marker next to a pylon, with the exposer’s name on it; remove it at end of that exposer’s next turn.
- If Present is alive: put a ring on any grappled PC; move them toward the dais with Pull.

---

# Appendix A — Simulation Assumptions (Current Baseline)

This appendix captures the assumptions used for the current Phase 1 simulation runs.

## Core rules assumptions (5e 2014 + homebrew mechanics)
- **Procedure is a Bonus Action** (not an action).
- **Exposed duration:** until the **end of the exposing creature’s next turn**.
- **One breakpoint per attack** (can’t cross both 30 and 15 in one hit).
- **Unexposed damage multiplier:** 0.5 (resistance).
- **Pulse targeting:** assumes only **one** PC is within 10 ft of a pulsing pylon (players minimize exposure).
- **Positioning model:** pylons are equidistant; boss is at center; PCs avoid center unless pulled.

## Baseline scenario settings (from JSON)
Source: `river_line/encounters/ley_heart/scenarios/ley_heart_phase_1.json`
- Pylon HP / AC: 39 / 12
- Procedure DC: 13
- Pulse save DC: 15
- Breakpoints: 30 / 15
- Procedure mode: pass-on-fail (first in initiative keeps trying until success; then passes on failure)
- Procedure checks are rolled by **whoever is attempting the Procedure** (using that creature’s own skill modifiers); `procedure_actors` is present in JSON but **not used** unless you switch `procedure_mode` to `fixed_actor`
- Initiative: rolled once and kept
- Healing assumptions: **no Healing Word** and **no Wholeness of Body** (damage taken is “no-heal”)
- Boss enabled; lair mode: best-available; target mode: random
- Pulse targeting: `single_alternating_monk` (sim assumes only one PC is in 10 ft; it alternates between the two monks, starting randomly)
- Boss action priority (sim tie-break): Guilt Fog → Boiler Vent → Time Shear → Harpoon → Slam
- Boss lair selection: `best_available` (conditional order: Phase Flicker if a pylon is “weak”, else Arc Flash, else Undertow)
- Boss canonical setpoints (used by the sim): `damage_scalar=1.0`, `save_dc_offset=0`, `attack_bonus_offset=0`, `temporal_reversal_recharge_min=5`

## Known simplifications (simulation vs table)
- Boss cones/areas are approximated as hitting **N targets** in the sim (Baseline: Guilt Fog 2, Boiler Vent 1, Arc Flash 2), not true templates + placement.
- **Present pylon “push 10 ft”** rider is not fully simulated as forced movement.
- **Tail Tap** is modeled as an accuracy penalty in the sim (instead of fully simulating prone’s advantage/disadvantage ecosystem).
- **Undertow** is modeled as a targeted restraint check rather than a true 10-ft-square placement puzzle.
- Procedure range/LoS is not enforced in the sim (table rules on the card are the intended play experience).

---

# Appendix B — Simulation Results (50,000 Trials Each)

All results below use seed `20260219` and are Monte Carlo estimates (mean/median).

## Scenario: Baseline (focus-fire order past → present → future)
Source: `river_line/results/20260220T020151Z_baseline_boss_original_damage_50k/summary.json`
- Mean rounds to destroy all pylons: 5.680 (median 6)
- Mean pylon kill rounds: Past 2.004, Present 3.762, Future 5.679
- Mean damage taken: Isak 21.886, Fury 22.968, Squanch 18.295
- Mean damage dealt: Isak 44.198, Fury 46.794, Squanch 26.005
- Down chance: Isak 0.144%, Fury 0.842%, Squanch 1.648%
- Mean ki spent: Isak 1.295, Fury 1.250
- Mean Procedure attempts / successes:
  - Isak 1.844 / 0.787
  - Fury 2.297 / 1.429
  - Squanch 1.488 / 0.953
- Mean boss action uses (per fight): Guilt Fog 1.057, Time Shear 1.737, Harpoon 0.228, Boiler Vent 0.064, Slam 0.006
- Mean boss lair uses (per fight): Phase Flicker 3.649, Arc Flash 2.031, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 1.907

## Scenario: Baseline + fail-forward (next Procedure attempt has advantage after a failure)
Source: `river_line/results/20260220T020458Z_proc_adv_boss_original_damage_50k/summary.json`
- Mean rounds to destroy all pylons: 5.545 (median 6)
- Mean pylon kill rounds: Past 1.927, Present 3.654, Future 5.545
- Mean damage taken: Isak 21.506, Fury 22.534, Squanch 17.688
- Mean damage dealt: Isak 44.483, Fury 47.040, Squanch 25.477
- Down chance: Isak 0.116%, Fury 0.768%, Squanch 1.314%
- Mean ki spent: Isak 1.329, Fury 1.277
- Mean Procedure attempts / successes:
  - Isak 1.658 / 0.833
  - Fury 2.071 / 1.440
  - Squanch 1.215 / 0.916
- Mean boss action uses (per fight): Guilt Fog 1.024, Time Shear 1.679, Harpoon 0.192, Boiler Vent 0.051, Slam 0.006
- Mean boss lair uses (per fight): Phase Flicker 3.526, Arc Flash 2.019, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 1.863

## Scenario: Aggressive play (both monks focus-fire and Flurry whenever ki is available)
Source: `river_line/results/20260220T020517Z_double_monk_flurry_boss_original_damage_50k/summary.json`
- Mean rounds to destroy all pylons: 4.918 (median 5)
- Mean pylon kill rounds: Past 1.780, Present 3.294, Future 4.918
- Mean damage taken: Isak 39.751, Fury 18.412, Squanch 11.909
- Mean damage dealt: Isak 48.376, Fury 46.616, Squanch 22.007
- Down chance: Isak 0.684%, Fury 0.150%, Squanch 0.404%
- Mean ki spent: Isak 2.254, Fury 1.942
- Mean Procedure attempts / successes:
  - Isak 1.778 / 0.755
  - Fury 2.186 / 1.355
  - Squanch 1.419 / 0.908
- Mean boss action uses (per fight): Guilt Fog 0.946, Time Shear 1.414, Harpoon 0.132, Boiler Vent 0.031, Slam 0.004
- Mean boss lair uses (per fight): Phase Flicker 2.895, Arc Flash 2.023, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 1.751

## Scenario: Split pressure (parallel mode; monks split onto two pylons)
Source: `river_line/results/20260220T020625Z_split_two_pylons_boss_original_damage_50k/summary.json`
- Mean rounds to destroy all pylons: 5.396 (median 5)
- Mean pylon kill rounds: Past 4.496, Present 3.943, Future 4.200
- Mean damage taken: Isak 27.016, Fury 20.042, Squanch 33.100
- Mean damage dealt: Isak 42.267, Fury 43.798, Squanch 30.933
- Down chance: Isak 0.270%, Fury 0.614%, Squanch 9.678%
- Mean ki spent: Isak 0.380, Fury 0.426
- Mean Procedure attempts / successes:
  - Isak 3.372 / 1.351
  - Fury 2.598 / 1.688
  - Squanch 2.519 / 1.891
- Mean boss action uses (per fight): Guilt Fog 2.165, Time Shear 1.667, Harpoon 0.760, Boiler Vent 0.155, Slam 0.007
- Mean boss lair uses (per fight): Phase Flicker 3.043, Arc Flash 1.732, Undertow 0.620
- Mean Temporal Reversal uses (per fight): 1.777
