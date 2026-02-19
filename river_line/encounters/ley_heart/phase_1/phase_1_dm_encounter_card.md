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
> They incorporate the Phase 1 sim’s balancing sweep (lower DCs / to-hit and adjusted damage dice), so you never need to apply an offset at the table.

### Action Options (choose one each round)

These options are available only while the linked pylon remains alive.

**Harpoon Winch (Present alive)**
- **Attack:** +7 to hit, range 60/180, 1 target
- **Hit:** 1d10+4 piercing/force
- Target is **grappled** (escape DC 16)

**Guilt Fog (Past alive; Recharge 5–6)**
- **Area:** 30-ft cone
- **Save:** DC 14 Con
- **Fail:** 3d6 necrotic and the target **can’t regain HP until the start of the Engine’s next turn**
- **Success:** Half damage, no rider

**Boiler Vent (Recharge 5–6)**
- **Area:** 15-ft cone
- **Save:** DC 14 Con
- **Fail:** 3d6 fire and **pushed 10 ft**
- **Success:** Half damage, no push

**Time Shear (Future alive; Recharge 4–6)**
- **Target:** 1 creature within 90 ft
- **Save:** DC 13 Wis
- **Fail:** 2d6+1 psychic and **Slowed until end of its next turn**:
  - speed halved
  - no reactions
  - on its turn it can take **either** an action **or** a bonus action (not both)
- **Success:** Half damage, no slow

**Slam (Reach 10 ft; only if someone is in reach)**
- **Attack:** +8 to hit, reach 10 ft, 1 target
- **Hit:** 2d6+2 bludgeoning

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
- **Fail:** 1d6+1 lightning and **no reactions** until the start of their next turn
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
Source: `/Users/rexputnam/Documents/projects/dnd_sim/river_line/encounters/ley_heart/scenarios/ley_heart_phase_1.json`
- Pylon HP / AC: 39 / 12
- Procedure DC: 13
- Pulse save DC: 15
- Breakpoints: 30 / 15
- Procedure mode: pass-on-fail (first in initiative keeps trying until success; then passes on failure)
- Initiative: rolled once and kept
- Boss enabled; lair mode: best-available; target mode: random
- Boss canonical setpoints (used by the sim): `damage_scalar=1.0`, `save_dc_offset=0`, `attack_bonus_offset=0`, `temporal_reversal_recharge_min=5`

## Known simplifications (simulation vs table)
- **Present pylon “push 10 ft”** rider is not fully simulated as forced movement.
- **Tail Tap** is modeled as an accuracy penalty in the sim (instead of fully simulating prone’s advantage/disadvantage ecosystem).
- **Undertow** is modeled as a targeted restraint check rather than a true 10-ft-square placement puzzle.

---

# Appendix B — Simulation Results (50,000 Trials Each)

All results below use seed `20260219` and are Monte Carlo estimates (mean/median).

## Scenario: Baseline (focus-fire order past → present → future)
Source: `/Users/rexputnam/Documents/projects/dnd_sim/river_line/results/20260219T231406Z_baseline_canonical_baked_50k/summary.json`
- Mean rounds to destroy all pylons: 6.612 (median 6)
- Mean pylon kill rounds: Past 2.145, Present 4.289, Future 6.611
- Mean damage taken: Isak 21.935, Fury 22.575, Squanch 16.914
- Mean damage dealt: Isak 45.583, Fury 49.255, Squanch 22.160
- Down chance: Isak 0.070%, Fury 0.282%, Squanch 0.910%
- Mean ki spent: Isak 1.265, Fury 1.274
- Mean Procedure attempts / successes:
  - Isak 1.912 / 0.825
  - Fury 2.432 / 1.524
  - Squanch 1.606 / 1.031
- Mean boss action uses (per fight): Guilt Fog 1.377, Time Shear 3.035, Harpoon 0.812, Boiler Vent 0.328, Slam 0.050
- Mean boss lair uses (per fight): Phase Flicker 4.529, Arc Flash 2.082, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 2.441

## Scenario: Baseline + fail-forward (next Procedure attempt has advantage after a failure)
Source: `/Users/rexputnam/Documents/projects/dnd_sim/river_line/results/20260219T231419Z_proc_adv_canonical_baked_50k/summary.json`
- Mean rounds to destroy all pylons: 6.430 (median 6)
- Mean pylon kill rounds: Past 2.062, Present 4.152, Future 6.430
- Mean damage taken: Isak 21.780, Fury 22.176, Squanch 16.448
- Mean damage dealt: Isak 45.888, Fury 49.165, Squanch 21.948
- Down chance: Isak 0.048%, Fury 0.244%, Squanch 0.684%
- Mean ki spent: Isak 1.311, Fury 1.285
- Mean Procedure attempts / successes:
  - Isak 1.720 / 0.865
  - Fury 2.223 / 1.543
  - Squanch 1.352 / 1.014
- Mean boss action uses (per fight): Guilt Fog 1.352, Time Shear 2.968, Harpoon 0.776, Boiler Vent 0.293, Slam 0.044
- Mean boss lair uses (per fight): Phase Flicker 4.366, Arc Flash 2.065, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 2.397

## Scenario: Aggressive play (both monks focus-fire and Flurry whenever ki is available)
Source: `/Users/rexputnam/Documents/projects/dnd_sim/river_line/results/20260219T231434Z_double_monk_flurry_canonical_baked_50k/summary.json`
- Mean rounds to destroy all pylons: 5.478 (median 5)
- Mean pylon kill rounds: Past 1.857, Present 3.565, Future 5.478
- Mean damage taken: Isak 37.493, Fury 17.239, Squanch 11.127
- Mean damage dealt: Isak 49.952, Fury 48.974, Squanch 18.074
- Down chance: Isak 0.136%, Fury 0.012%, Squanch 0.130%
- Mean ki spent: Isak 2.513, Fury 2.267
- Mean Procedure attempts / successes:
  - Isak 1.791 / 0.766
  - Fury 2.232 / 1.387
  - Squanch 1.445 / 0.922
- Mean boss action uses (per fight): Guilt Fog 1.284, Time Shear 2.558, Harpoon 0.588, Boiler Vent 0.164, Slam 0.027
- Mean boss lair uses (per fight): Phase Flicker 3.418, Arc Flash 2.060, Undertow 0.000
- Mean Temporal Reversal uses (per fight): 2.213

## Scenario: Split pressure (parallel mode; monks split onto two pylons)
Source: `/Users/rexputnam/Documents/projects/dnd_sim/river_line/results/20260219T231447Z_split_two_pylons_canonical_baked_50k/summary.json`
- Mean rounds to destroy all pylons: 5.734 (median 6)
- Mean pylon kill rounds: Past 4.799, Present 4.217, Future 4.511
- Mean damage taken: Isak 22.109, Fury 13.173, Squanch 25.016
- Mean damage dealt: Isak 44.360, Fury 46.616, Squanch 26.024
- Down chance: Isak 0.006%, Fury 0.010%, Squanch 0.982%
- Mean ki spent: Isak 0.413, Fury 0.473
- Mean Procedure attempts / successes:
  - Isak 3.561 / 1.422
  - Fury 2.753 / 1.788
  - Squanch 2.737 / 2.057
- Mean boss action uses (per fight): Guilt Fog 2.271, Time Shear 1.792, Harpoon 0.788, Boiler Vent 0.224, Slam 0.015
- Mean boss lair uses (per fight): Phase Flicker 3.314, Arc Flash 1.790, Undertow 0.630
- Mean Temporal Reversal uses (per fight): 1.857
