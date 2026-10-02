# Recorded roll excerpts

These are actual engine rolls from deterministic replay, not illustrative dice. Full samples include every journal fact and integer draw. Below: first 12 facts per sample.

## 01_raider_patrol / conservative / trial 0

Seed `12558159101570320120`; **party_victory** after 2 rounds. 58 integer draws; 32 journal facts. [Full sample](samples/01_raider_patrol__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_4 | [[30.0, 30.0, 0.0], [25.0, 25.0, 0.0], [20.0, 20.0, 0.0], [15.0, 15.0, 0.0], [10.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | rogue | [] | basic → ['raider_4'] | off_hand_attack → ['raider_4'] | auto |
| 1 | raider_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['raider_2'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |
| 1 | raider_2 | [[10.0, 30.0, 0.0], [5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | raider_4 → rogue | action:basic / d20 | `1d20+4`: 2(kept) | 6 vs 16: miss |
| 2 | rogue → raider_4 | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 13: hit |
| 3 | rogue → raider_4 | action:basic / damage | `1d6+4`: 3(kept) | 7 raw → 7 applied piercing |
| 4 | rogue → raider_4 | action:basic / damage | `3d6`: 3(kept), 5(kept), 2(kept) | 10 raw → 10 applied piercing |
| 5 | rogue → raider_4 | action:off_hand_attack / d20 | `1d20+7`: 10(kept) | 17 vs 13: hit |
| 6 | rogue → raider_4 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 7 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 3(kept) | 7 vs 16: miss |
| 8 | raider_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 12(kept) | 14 vs 15: failure |
| 9 | wizard → raider_1 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 25 applied fire |
| 10 | raider_2 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 11 | wizard → raider_2 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 12 applied fire |
| 12 | raider_4 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |

## 01_raider_patrol / typical / trial 0

Seed `12558159101570320120`; **party_victory** after 2 rounds. 58 integer draws; 32 journal facts. [Full sample](samples/01_raider_patrol__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_4 | [[30.0, 30.0, 0.0], [25.0, 25.0, 0.0], [20.0, 20.0, 0.0], [15.0, 15.0, 0.0], [10.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | rogue | [] | basic → ['raider_4'] | off_hand_attack → ['raider_4'] | auto |
| 1 | raider_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['raider_2'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |
| 1 | raider_2 | [[10.0, 30.0, 0.0], [5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | raider_4 → rogue | action:basic / d20 | `1d20+4`: 2(kept) | 6 vs 16: miss |
| 2 | rogue → raider_4 | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 13: hit |
| 3 | rogue → raider_4 | action:basic / damage | `1d6+4`: 3(kept) | 7 raw → 7 applied piercing |
| 4 | rogue → raider_4 | action:basic / damage | `3d6`: 3(kept), 5(kept), 2(kept) | 10 raw → 10 applied piercing |
| 5 | rogue → raider_4 | action:off_hand_attack / d20 | `1d20+7`: 10(kept) | 17 vs 13: hit |
| 6 | rogue → raider_4 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 7 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 3(kept) | 7 vs 16: miss |
| 8 | raider_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 12(kept) | 14 vs 15: failure |
| 9 | wizard → raider_1 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 25 applied fire |
| 10 | raider_2 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 11 | wizard → raider_2 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 12 applied fire |
| 12 | raider_4 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |

## 01_raider_patrol / aggressive / trial 0

Seed `12558159101570320120`; **party_victory** after 2 rounds. 58 integer draws; 32 journal facts. [Full sample](samples/01_raider_patrol__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_4 | [[30.0, 30.0, 0.0], [25.0, 25.0, 0.0], [20.0, 20.0, 0.0], [15.0, 15.0, 0.0], [10.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | rogue | [] | basic → ['raider_4'] | off_hand_attack → ['raider_4'] | auto |
| 1 | raider_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['raider_2'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |
| 1 | raider_2 | [[10.0, 30.0, 0.0], [5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | raider_4 → rogue | action:basic / d20 | `1d20+4`: 2(kept) | 6 vs 16: miss |
| 2 | rogue → raider_4 | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 13: hit |
| 3 | rogue → raider_4 | action:basic / damage | `1d6+4`: 3(kept) | 7 raw → 7 applied piercing |
| 4 | rogue → raider_4 | action:basic / damage | `3d6`: 3(kept), 5(kept), 2(kept) | 10 raw → 10 applied piercing |
| 5 | rogue → raider_4 | action:off_hand_attack / d20 | `1d20+7`: 10(kept) | 17 vs 13: hit |
| 6 | rogue → raider_4 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 7 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 3(kept) | 7 vs 16: miss |
| 8 | raider_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 12(kept) | 14 vs 15: failure |
| 9 | wizard → raider_1 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 25 applied fire |
| 10 | raider_2 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 11 | wizard → raider_2 | action:Fireball / damage | `8d6`: 6(kept), 3(kept), 2(kept), 2(kept), 4(kept), 1(kept), 4(kept), 3(kept) | 25 raw → 12 applied fire |
| 12 | raider_4 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |

## 02_veteran_line / conservative / trial 0

Seed `16178192625311789988`; **party_victory** after 7 rounds. 140 integer draws; 112 journal facts. [Full sample](samples/02_veteran_line__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0]] | basic → ['veteran_3'] | off_hand_attack → ['veteran_3'] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [15.0, 25.0, 0.0], [20.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fire Bolt → ['veteran_3'] | None → [] | auto |
| 1 | veteran_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 15.0, 0.0], [25.0, 20.0, 0.0], [30.0, 25.0, 0.0]] | action_surge → ['veteran_3'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_3 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 17: hit |
| 2 | rogue → veteran_3 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → veteran_3 | action:off_hand_attack / d20 | `1d20+7`: 12(kept) | 19 vs 17: hit |
| 4 | rogue → veteran_3 | action:off_hand_attack / damage | `1d6`: 2(kept) | 2 raw → 2 applied piercing |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 5 raw → 5 applied slashing |
| 8 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 7(kept) | 13 vs 16: miss |
| 9 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 11(kept) | 17 vs 16: hit |
| 10 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 11 | wizard → veteran_3 | action:Fire Bolt / d20 | `1d20+7`: 2(kept) | 9 vs 17: miss |
| 12 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |

## 02_veteran_line / conservative / trial 288

Seed `754536759598914268`; **enemy_victory** after 11 rounds. 259 integer draws; 180 journal facts. [Full sample](samples/02_veteran_line__conservative__288.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | cleric | [] | Sacred Flame → ['veteran_3'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0]] | action_surge → ['veteran_3'] | None → [] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fire Bolt → ['veteran_3'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [10.0, 5.0, 0.0], [15.0, 10.0, 0.0], [20.0, 15.0, 0.0], [25.0, 20.0, 0.0], [30.0, 25.0, 0.0]] | basic → ['veteran_3'] | off_hand_attack → ['veteran_3'] | auto |
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [15.0, 25.0, 0.0], [20.0, 20.0, 0.0], [25.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_3 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 16(kept) | 18 vs 15: success |
| 2 | cleric → veteran_3 | action:Sacred Flame / damage | `2d8`: 2(kept), 7(kept) | 9 raw → 0 applied radiant |
| 3 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 19(kept) | 26 vs 17: hit |
| 4 | fighter → veteran_3 | action:action_surge / damage | `1d8+4`: 1(kept) | 5 raw → 5 applied slashing |
| 5 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 6(kept) | 13 vs 17: miss |
| 6 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 10(kept) | 17 vs 17: hit |
| 7 | fighter → veteran_3 | action:action_surge / damage | `1d8+4`: 6(kept) | 10 raw → 10 applied slashing |
| 8 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 11(kept) | 18 vs 17: hit |
| 9 | fighter → veteran_3 | action:action_surge / damage | `1d8+4`: 2(kept) | 6 raw → 6 applied slashing |
| 10 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 17(kept) | 23 vs 16: hit |
| 11 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 5 raw → 5 applied slashing |
| 12 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |

## 02_veteran_line / typical / trial 0

Seed `16178192625311789988`; **party_victory** after 6 rounds. 130 integer draws; 101 journal facts. [Full sample](samples/02_veteran_line__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0]] | basic → ['veteran_3'] | off_hand_attack → ['veteran_3'] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [15.0, 25.0, 0.0], [20.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fire Bolt → ['veteran_3'] | None → [] | auto |
| 1 | veteran_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 15.0, 0.0], [25.0, 20.0, 0.0], [30.0, 25.0, 0.0]] | action_surge → ['veteran_3'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_3 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 17: hit |
| 2 | rogue → veteran_3 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → veteran_3 | action:off_hand_attack / d20 | `1d20+7`: 12(kept) | 19 vs 17: hit |
| 4 | rogue → veteran_3 | action:off_hand_attack / damage | `1d6`: 2(kept) | 2 raw → 2 applied piercing |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 5 raw → 5 applied slashing |
| 8 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 7(kept) | 13 vs 16: miss |
| 9 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 11(kept) | 17 vs 16: hit |
| 10 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 11 | wizard → veteran_3 | action:Fire Bolt / d20 | `1d20+7`: 2(kept) | 9 vs 17: miss |
| 12 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |

## 02_veteran_line / typical / trial 65

Seed `9915200167151219418`; **enemy_victory** after 10 rounds. 248 integer draws; 173 journal facts. [Full sample](samples/02_veteran_line__typical__65.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | cleric | [] | Sacred Flame → ['veteran_3'] | None → [] | auto |
| 1 | veteran_3 | [[30.0, 30.0, 0.0], [25.0, 25.0, 0.0], [20.0, 20.0, 0.0], [15.0, 15.0, 0.0], [10.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [0.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['veteran_1'] | None → [] | auto |
| 1 | fighter | [] | action_surge → ['veteran_3'] | None → [] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_3 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 9(kept) | 11 vs 15: failure |
| 2 | cleric → veteran_3 | action:Sacred Flame / damage | `2d8`: 5(kept), 4(kept) | 9 raw → 9 applied radiant |
| 3 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 4(kept) | 10 vs 16: miss |
| 4 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 12(kept) | 18 vs 16: hit |
| 5 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 5 raw → 5 applied slashing |
| 6 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 12(kept) | 18 vs 16: hit |
| 7 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 5(kept) | 8 raw → 8 applied slashing |
| 8 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 16: miss |
| 9 | veteran_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 3(kept) | 5 vs 15: failure |
| 10 | wizard → veteran_1 | action:Fireball / damage | `8d6`: 2(kept), 6(kept), 6(kept), 5(kept), 1(kept), 5(kept), 2(kept), 5(kept) | 32 raw → 32 applied fire |
| 11 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 5(kept) | 12 vs 17: miss |
| 12 | fighter → veteran_3 | action:action_surge / d20 | `1d20+7`: 8(kept) | 15 vs 17: miss |

## 02_veteran_line / aggressive / trial 0

Seed `16178192625311789988`; **party_victory** after 7 rounds. 197 integer draws; 134 journal facts. [Full sample](samples/02_veteran_line__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0]] | basic → ['veteran_3'] | off_hand_attack → ['veteran_3'] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [15.0, 25.0, 0.0], [20.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Scorching Ray → ['veteran_3'] | None → [] | auto |
| 1 | veteran_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 15.0, 0.0], [25.0, 20.0, 0.0], [30.0, 25.0, 0.0]] | action_surge → ['veteran_3'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_3 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 17: hit |
| 2 | rogue → veteran_3 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → veteran_3 | action:off_hand_attack / d20 | `1d20+7`: 12(kept) | 19 vs 17: hit |
| 4 | rogue → veteran_3 | action:off_hand_attack / damage | `1d6`: 2(kept) | 2 raw → 2 applied piercing |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 5 raw → 5 applied slashing |
| 8 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 7(kept) | 13 vs 16: miss |
| 9 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 11(kept) | 17 vs 16: hit |
| 10 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 11 | wizard → veteran_3 | action:Scorching Ray / d20 | `1d20+7`: 2(kept) | 9 vs 17: miss |
| 12 | wizard → veteran_3 | action:Scorching Ray / d20 | `1d20+7`: 9(kept) | 16 vs 17: miss |

## 02_veteran_line / aggressive / trial 559

Seed `1166985207407521804`; **enemy_victory** after 16 rounds. 263 integer draws; 183 journal facts. [Full sample](samples/02_veteran_line__aggressive__559.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_2 | [[10.0, 30.0, 0.0], [5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | rogue | [] | basic → ['veteran_2'] | off_hand_attack → ['veteran_2'] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_3'] | Healing Word (slot 3) → ['rogue'] | auto |
| 1 | veteran_3 | [[30.0, 30.0, 0.0], [25.0, 25.0, 0.0], [20.0, 20.0, 0.0], [15.0, 15.0, 0.0], [10.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-10.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0], [10.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Scorching Ray → ['veteran_3'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 2 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |
| 3 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 2(kept) | 2 raw → 2 applied slashing |
| 4 | rogue → veteran_2 | action:basic / d20 | `1d20+7`: 17(kept) | 24 vs 17: hit |
| 5 | rogue → veteran_2 | action:basic / damage | `1d6+4`: 1(kept) | 5 raw → 5 applied piercing |
| 6 | rogue → veteran_2 | action:basic / damage | `3d6`: 4(kept), 3(kept), 2(kept) | 9 raw → 9 applied piercing |
| 7 | rogue → veteran_2 | action:off_hand_attack / d20 | `1d20+7`: 20(kept) | 27 vs 17: hit |
| 8 | rogue → veteran_2 | action:off_hand_attack / damage | `1d6`: 1(kept), 3(kept) | 4 raw → 4 applied piercing |
| 9 | veteran_3 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 15(kept) | 17 vs 15: success |
| 10 | cleric → veteran_3 | action:Sacred Flame / damage | `2d8`: 1(kept), 6(kept) | 7 raw → 0 applied radiant |
| 11 | cleric → rogue | action:Healing Word (slot 3) / healing | `3d4+4`: 2(kept), 4(kept), 4(kept) | 14 rolled → 2 healed |
| 12 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 16(kept) | 22 vs 16: hit |

## 03_archer_cover / conservative / trial 0

Seed `14677977766777445051`; **party_victory** after 2 rounds. 72 integer draws; 41 journal facts. [Full sample](samples/03_archer_cover__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | archer_1 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_2 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_4 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_3 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['archer_4'] | None → [] | auto |
| 1 | archer_5 | [] | basic → ['wizard'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | archer_1 → wizard | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 14: miss |
| 2 | archer_2 → wizard | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 19: miss |
| 3 | archer_4 → wizard | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 19: hit |
| 4 | archer_4 → wizard | action:basic / damage | `1d8+3`: 2(kept) | 5 raw → 5 applied slashing |
| 5 | archer_3 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |
| 6 | archer_3 → wizard | action:Fireball / saving_throw | `1d20+4`: 2(kept) | 6 vs 15: failure |
| 7 | wizard → archer_3 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 8 | archer_4 → wizard | action:Fireball / saving_throw | `1d20+4`: 10(kept) | 14 vs 15: failure |
| 9 | wizard → archer_4 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 10 | archer_5 → wizard | action:Fireball / saving_throw | `1d20+4`: 8(kept) | 12 vs 15: failure |
| 11 | wizard → archer_5 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 12 | archer_5 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |

## 03_archer_cover / typical / trial 0

Seed `14677977766777445051`; **party_victory** after 2 rounds. 72 integer draws; 41 journal facts. [Full sample](samples/03_archer_cover__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | archer_1 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_2 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_4 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_3 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['archer_4'] | None → [] | auto |
| 1 | archer_5 | [] | basic → ['wizard'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | archer_1 → wizard | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 14: miss |
| 2 | archer_2 → wizard | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 19: miss |
| 3 | archer_4 → wizard | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 19: hit |
| 4 | archer_4 → wizard | action:basic / damage | `1d8+3`: 2(kept) | 5 raw → 5 applied slashing |
| 5 | archer_3 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |
| 6 | archer_3 → wizard | action:Fireball / saving_throw | `1d20+4`: 2(kept) | 6 vs 15: failure |
| 7 | wizard → archer_3 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 8 | archer_4 → wizard | action:Fireball / saving_throw | `1d20+4`: 10(kept) | 14 vs 15: failure |
| 9 | wizard → archer_4 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 10 | archer_5 → wizard | action:Fireball / saving_throw | `1d20+4`: 8(kept) | 12 vs 15: failure |
| 11 | wizard → archer_5 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 12 | archer_5 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |

## 03_archer_cover / aggressive / trial 0

Seed `14677977766777445051`; **party_victory** after 4 rounds. 95 integer draws; 57 journal facts. [Full sample](samples/03_archer_cover__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | archer_1 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_2 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_4 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | archer_3 | [] | basic → ['wizard'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['archer_4'] | None → [] | auto |
| 1 | archer_5 | [] | basic → ['wizard'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | archer_1 → wizard | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 14: miss |
| 2 | archer_2 → wizard | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 19: miss |
| 3 | archer_4 → wizard | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 19: hit |
| 4 | archer_4 → wizard | action:basic / damage | `1d8+3`: 2(kept) | 5 raw → 5 applied slashing |
| 5 | archer_3 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |
| 6 | archer_3 → wizard | action:Fireball / saving_throw | `1d20+4`: 2(kept) | 6 vs 15: failure |
| 7 | wizard → archer_3 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 8 | archer_4 → wizard | action:Fireball / saving_throw | `1d20+4`: 10(kept) | 14 vs 15: failure |
| 9 | wizard → archer_4 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 10 | archer_5 → wizard | action:Fireball / saving_throw | `1d20+4`: 8(kept) | 12 vs 15: failure |
| 11 | wizard → archer_5 | action:Fireball / damage | `8d6`: 1(kept), 4(kept), 4(kept), 2(kept), 1(kept), 5(kept), 5(kept), 1(kept) | 23 raw → 23 applied fire |
| 12 | archer_5 → wizard | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 19: miss |

## 04_cinder_sentinel / conservative / trial 0

Seed `5558580781160890437`; **party_victory** after 9 rounds. 173 integer draws; 120 journal facts. [Full sample](samples/04_cinder_sentinel__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | None → [] | auto |
| 1 | wizard | [] | Fire Bolt → ['cinder_sentinel'] | None → [] | auto |
| 1 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['cinder_sentinel'] | Healing Word → ['rogue'] | auto |
| 2 | rogue | [] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 2 | rogue → cinder_sentinel | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 9(kept) | 16 vs 16: hit |
| 4 | rogue → cinder_sentinel | action:off_hand_attack / damage | `1d6`: 3(kept) | 3 raw → 3 applied piercing |
| 5 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 7(kept) | 14 vs 16: miss |
| 6 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 16(kept) | 23 vs 16: hit |
| 7 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 8 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 5(kept) | 12 vs 16: miss |
| 9 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 10 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 11 | wizard → cinder_sentinel | action:Fire Bolt / d20 | `1d20+7`: 1(kept) | 8 vs 16: miss |
| 12 | cinder_sentinel → rogue | action:basic / d20 | `1d20+8`: 14(kept) | 22 vs 16: hit |

## 04_cinder_sentinel / conservative / trial 31

Seed `5860873138619259636`; **enemy_victory** after 19 rounds. 324 integer draws; 182 journal facts. [Full sample](samples/04_cinder_sentinel__conservative__31.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | wizard | [] | Fire Bolt → ['cinder_sentinel'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['cinder_sentinel'] | Healing Word → ['rogue'] | auto |
| 2 | wizard | [] | Fire Bolt → ['cinder_sentinel'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | wizard → cinder_sentinel | action:Fire Bolt / d20 | `1d20+7`: 6(kept) | 13 vs 16: miss |
| 2 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 3(kept) | 10 vs 16: miss |
| 3 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 16(kept) | 23 vs 16: hit |
| 4 | rogue → cinder_sentinel | action:off_hand_attack / damage | `1d6`: 2(kept) | 2 raw → 2 applied piercing |
| 5 | cinder_sentinel → rogue | action:basic / d20 | `1d20+8`: 18(kept) | 26 vs 16: hit |
| 6 | cinder_sentinel → rogue | action:basic / damage | `2d10+5`: 9(kept), 3(kept) | 8 raw → 8 applied slashing |
| 7 | cinder_sentinel → rogue | action:basic / d20 | `1d20+8`: 8(kept) | 16 vs 16: hit |
| 8 | cinder_sentinel → rogue | action:basic / damage | `2d10+5`: 5(kept), 2(kept) | 12 raw → 12 applied slashing |
| 9 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 7(kept) | 14 vs 16: miss |
| 10 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 9(kept) | 16 vs 16: hit |
| 11 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 6(kept) | 10 raw → 10 applied slashing |
| 12 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 4(kept) | 11 vs 16: miss |

## 04_cinder_sentinel / typical / trial 0

Seed `5558580781160890437`; **party_victory** after 9 rounds. 186 integer draws; 122 journal facts. [Full sample](samples/04_cinder_sentinel__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | None → [] | auto |
| 1 | wizard | [] | Fire Bolt → ['cinder_sentinel'] | None → [] | auto |
| 1 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['cinder_sentinel'] | Healing Word → ['rogue'] | auto |
| 2 | rogue | [] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 2 | rogue → cinder_sentinel | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 9(kept) | 16 vs 16: hit |
| 4 | rogue → cinder_sentinel | action:off_hand_attack / damage | `1d6`: 3(kept) | 3 raw → 3 applied piercing |
| 5 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 7(kept) | 14 vs 16: miss |
| 6 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 16(kept) | 23 vs 16: hit |
| 7 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 8 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 5(kept) | 12 vs 16: miss |
| 9 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 10 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 11 | wizard → cinder_sentinel | action:Fire Bolt / d20 | `1d20+7`: 1(kept) | 8 vs 16: miss |
| 12 | cinder_sentinel → rogue | action:basic / d20 | `1d20+8`: 14(kept) | 22 vs 16: hit |

## 04_cinder_sentinel / typical / trial 81

Seed `16934525012448441131`; **enemy_victory** after 19 rounds. 300 integer draws; 165 journal facts. [Full sample](samples/04_cinder_sentinel__typical__81.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | cinder_sentinel | [] | Cinder Burst → ['rogue'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | second_wind → ['fighter'] | auto |
| 1 | wizard | [] | Fire Bolt → ['cinder_sentinel'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['cinder_sentinel'] | Healing Word → ['rogue'] | auto |
| 2 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → cinder_sentinel | action:Cinder Burst / saving_throw | `1d20+7`: 2(kept) | 9 vs 15: failure |
| 2 | cinder_sentinel → rogue | action:Cinder Burst / damage | `5d6`: 4(kept), 4(kept), 3(kept), 1(kept), 6(kept) | 18 raw → 18 applied fire |
| 3 | fighter → cinder_sentinel | action:Cinder Burst / saving_throw | `1d20+1`: 20(kept) | 21 vs 15: success |
| 4 | cinder_sentinel → fighter | action:Cinder Burst / damage | `5d6`: 4(kept), 4(kept), 3(kept), 1(kept), 6(kept) | 18 raw → 9 applied fire |
| 5 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 17(kept) | 24 vs 16: hit |
| 6 | rogue → cinder_sentinel | action:basic / damage | `1d6+4`: 2(kept) | 6 raw → 6 applied piercing |
| 7 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 19(kept) | 26 vs 16: hit |
| 8 | rogue → cinder_sentinel | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 9 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 8(kept) | 15 vs 16: miss |
| 10 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 9(kept) | 16 vs 16: hit |
| 11 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 4(kept) | 8 raw → 8 applied slashing |
| 12 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 1(kept) | 8 vs 16: miss |

## 04_cinder_sentinel / aggressive / trial 0

Seed `5558580781160890437`; **party_victory** after 8 rounds. 189 integer draws; 127 journal facts. [Full sample](samples/04_cinder_sentinel__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | None → [] | auto |
| 1 | wizard | [] | Scorching Ray → ['cinder_sentinel'] | None → [] | auto |
| 1 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['cinder_sentinel'] | Healing Word (slot 3) → ['rogue'] | auto |
| 2 | rogue | [] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 2 | rogue → cinder_sentinel | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 9(kept) | 16 vs 16: hit |
| 4 | rogue → cinder_sentinel | action:off_hand_attack / damage | `1d6`: 3(kept) | 3 raw → 3 applied piercing |
| 5 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 7(kept) | 14 vs 16: miss |
| 6 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 16(kept) | 23 vs 16: hit |
| 7 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 8 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 5(kept) | 12 vs 16: miss |
| 9 | fighter → cinder_sentinel | action:action_surge / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |
| 10 | fighter → cinder_sentinel | action:action_surge / damage | `1d8+4`: 3(kept) | 7 raw → 7 applied slashing |
| 11 | wizard → cinder_sentinel | action:Scorching Ray / d20 | `1d20+7`: 1(kept) | 8 vs 16: miss |
| 12 | wizard → cinder_sentinel | action:Scorching Ray / d20 | `1d20+7`: 14(kept) | 21 vs 16: hit |

## 04_cinder_sentinel / aggressive / trial 16

Seed `16769747020241563280`; **enemy_victory** after 12 rounds. 240 integer draws; 147 journal facts. [Full sample](samples/04_cinder_sentinel__aggressive__16.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | cinder_sentinel | [] | Cinder Burst → ['rogue'] | None → [] | auto |
| 1 | cleric | [[0.0, -15.0, 0.0], [-5.0, -10.0, 0.0], [-5.0, -5.0, 0.0]] | Cure Wounds (slot 3) → ['fighter'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 25.0, 0.0], [5.0, 30.0, 0.0]] | basic → ['cinder_sentinel'] | off_hand_attack → ['cinder_sentinel'] | auto |
| 1 | wizard | [] | Scorching Ray → ['cinder_sentinel'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 20.0, 0.0], [5.0, 25.0, 0.0], [10.0, 30.0, 0.0]] | action_surge → ['cinder_sentinel'] | None → [] | auto |
| 2 | cinder_sentinel | [] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → cinder_sentinel | action:Cinder Burst / saving_throw | `1d20+7`: 12(kept) | 19 vs 15: success |
| 2 | cinder_sentinel → rogue | action:Cinder Burst / damage | `5d6`: 3(kept), 2(kept), 6(kept), 6(kept), 5(kept) | 22 raw → 11 applied fire |
| 3 | fighter → cinder_sentinel | action:Cinder Burst / saving_throw | `1d20+1`: 1(kept) | 2 vs 15: failure |
| 4 | cinder_sentinel → fighter | action:Cinder Burst / damage | `5d6`: 3(kept), 2(kept), 6(kept), 6(kept), 5(kept) | 22 raw → 22 applied fire |
| 5 | cleric → fighter | action:Cure Wounds (slot 3) / healing | `3d8+4`: 4(kept), 7(kept), 8(kept) | 23 rolled → 22 healed |
| 6 | rogue → cinder_sentinel | action:basic / d20 | `1d20+7`: 19(kept) | 26 vs 16: hit |
| 7 | rogue → cinder_sentinel | action:basic / damage | `1d6+4`: 6(kept) | 10 raw → 10 applied piercing |
| 8 | rogue → cinder_sentinel | action:off_hand_attack / d20 | `1d20+7`: 5(kept) | 12 vs 16: miss |
| 9 | wizard → cinder_sentinel | action:Scorching Ray / d20 | `1d20+7`: 11(kept) | 18 vs 16: hit |
| 10 | wizard → cinder_sentinel | action:Scorching Ray / damage | `2d6`: 5(kept), 3(kept) | 8 raw → 4 applied fire |
| 11 | wizard → cinder_sentinel | action:Scorching Ray / d20 | `1d20+7`: 18(kept) | 25 vs 16: hit |
| 12 | wizard → cinder_sentinel | action:Scorching Ray / damage | `2d6`: 5(kept), 1(kept) | 6 raw → 3 applied fire |

## 05_overwhelming_line / conservative / trial 0

Seed `16470112594821982549`; **enemy_victory** after 6 rounds. 198 integer draws; 141 journal facts. [Full sample](samples/05_overwhelming_line__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_6 | [[30.0, 45.0, 0.0], [25.0, 40.0, 0.0], [20.0, 35.0, 0.0], [15.0, 30.0, 0.0], [10.0, 25.0, 0.0], [5.0, 20.0, 0.0], [0.0, 15.0, 0.0]] | dodge → ['veteran_6'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0]] | basic → ['veteran_6'] | off_hand_attack → ['veteran_6'] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-10.0, 15.0, 0.0], [-5.0, 10.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_6'] | Healing Word → ['rogue'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_6 | action:basic / d20 | `2d20kl1+7`: 16(kept), 20(discarded) | 23 vs 17: hit |
| 2 | rogue → veteran_6 | action:basic / damage | `1d6+4`: 5(kept) | 9 raw → 9 applied piercing |
| 3 | rogue → veteran_6 | action:off_hand_attack / d20 | `2d20kl1+7`: 12(discarded), 1(kept) | 8 vs 17: miss |
| 4 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 5 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 3(kept) | 3 raw → 3 applied slashing |
| 8 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |
| 9 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 11 raw → 11 applied slashing |
| 10 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 1(kept) | 7 vs 16: miss |
| 11 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 12 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |

## 05_overwhelming_line / conservative / trial 23

Seed `10880131136695994647`; **party_victory** after 7 rounds. 244 integer draws; 166 journal facts. [Full sample](samples/05_overwhelming_line__conservative__23.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | rogue | [] | basic → ['veteran_1'] | off_hand_attack → ['veteran_1'] | auto |
| 1 | wizard | [] | Fireball → ['veteran_3'] | None → [] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0]] | action_surge → ['veteran_5'] | None → [] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 2 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 17(kept) | 23 vs 16: hit |
| 3 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 7(kept) | 5 raw → 5 applied slashing |
| 4 | rogue → veteran_1 | action:basic / d20 | `1d20+7`: 6(kept) | 13 vs 17: miss |
| 5 | rogue → veteran_1 | action:off_hand_attack / d20 | `1d20+7`: 11(kept) | 18 vs 17: hit |
| 6 | rogue → veteran_1 | action:off_hand_attack / damage | `1d6`: 3(kept) | 3 raw → 3 applied piercing |
| 7 | rogue → veteran_1 | action:off_hand_attack / damage | `3d6`: 6(kept), 1(kept), 2(kept) | 9 raw → 9 applied piercing |
| 8 | veteran_2 → wizard | action:Fireball / saving_throw | `1d20+2`: 19(kept) | 21 vs 15: success |
| 9 | wizard → veteran_2 | action:Fireball / damage | `8d6`: 5(kept), 1(kept), 4(kept), 2(kept), 5(kept), 2(kept), 5(kept), 4(kept) | 28 raw → 14 applied fire |
| 10 | veteran_3 → wizard | action:Fireball / saving_throw | `1d20+2`: 3(kept) | 5 vs 15: failure |
| 11 | wizard → veteran_3 | action:Fireball / damage | `8d6`: 5(kept), 1(kept), 4(kept), 2(kept), 5(kept), 2(kept), 5(kept), 4(kept) | 28 raw → 28 applied fire |
| 12 | veteran_4 → wizard | action:Fireball / saving_throw | `1d20+2`: 6(kept) | 8 vs 15: failure |

## 05_overwhelming_line / typical / trial 0

Seed `16470112594821982549`; **enemy_victory** after 6 rounds. 198 integer draws; 141 journal facts. [Full sample](samples/05_overwhelming_line__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_6 | [[30.0, 45.0, 0.0], [25.0, 40.0, 0.0], [20.0, 35.0, 0.0], [15.0, 30.0, 0.0], [10.0, 25.0, 0.0], [5.0, 20.0, 0.0], [0.0, 15.0, 0.0]] | dodge → ['veteran_6'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0]] | basic → ['veteran_6'] | off_hand_attack → ['veteran_6'] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-10.0, 15.0, 0.0], [-5.0, 10.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_6'] | Healing Word → ['rogue'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_6 | action:basic / d20 | `2d20kl1+7`: 16(kept), 20(discarded) | 23 vs 17: hit |
| 2 | rogue → veteran_6 | action:basic / damage | `1d6+4`: 5(kept) | 9 raw → 9 applied piercing |
| 3 | rogue → veteran_6 | action:off_hand_attack / d20 | `2d20kl1+7`: 12(discarded), 1(kept) | 8 vs 17: miss |
| 4 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 5 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 3(kept) | 3 raw → 3 applied slashing |
| 8 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |
| 9 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 11 raw → 11 applied slashing |
| 10 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 1(kept) | 7 vs 16: miss |
| 11 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 12 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |

## 05_overwhelming_line / typical / trial 5

Seed `2536008357766756819`; **party_victory** after 10 rounds. 311 integer draws; 215 journal facts. [Full sample](samples/05_overwhelming_line__typical__5.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [0.0, 5.0, 0.0], [5.0, 0.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [0.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | action_surge → ['veteran_4'] | None → [] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-10.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | veteran_6 | [[30.0, 45.0, 0.0], [25.0, 40.0, 0.0], [20.0, 35.0, 0.0], [15.0, 30.0, 0.0], [10.0, 25.0, 0.0], [5.0, 20.0, 0.0], [5.0, 15.0, 0.0]] | dodge → ['veteran_6'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |
| 2 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 3 | veteran_4 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 4 raw → 4 applied slashing |
| 4 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 5 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 4(kept) | 10 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 8 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 9 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 10 | veteran_1 → fighter | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 18: hit |
| 11 | veteran_1 → fighter | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 12 | fighter → veteran_4 | action:action_surge / d20 | `1d20+7`: 8(kept) | 15 vs 17: miss |

## 05_overwhelming_line / aggressive / trial 0

Seed `16470112594821982549`; **enemy_victory** after 7 rounds. 283 integer draws; 184 journal facts. [Full sample](samples/05_overwhelming_line__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_6 | [[30.0, 45.0, 0.0], [25.0, 40.0, 0.0], [20.0, 35.0, 0.0], [15.0, 30.0, 0.0], [10.0, 25.0, 0.0], [5.0, 20.0, 0.0], [0.0, 15.0, 0.0]] | dodge → ['veteran_6'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 10.0, 0.0]] | basic → ['veteran_6'] | off_hand_attack → ['veteran_6'] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-10.0, 15.0, 0.0], [-5.0, 10.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [0.0, 20.0, 0.0], [5.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [[0.0, -15.0, 0.0], [-5.0, -10.0, 0.0], [-10.0, -5.0, 0.0], [-10.0, 0.0, 0.0], [-5.0, 5.0, 0.0]] | Cure Wounds (slot 3) → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_6 | action:basic / d20 | `2d20kl1+7`: 16(kept), 20(discarded) | 23 vs 17: hit |
| 2 | rogue → veteran_6 | action:basic / damage | `1d6+4`: 5(kept) | 9 raw → 9 applied piercing |
| 3 | rogue → veteran_6 | action:off_hand_attack / d20 | `2d20kl1+7`: 12(discarded), 1(kept) | 8 vs 17: miss |
| 4 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 5 | veteran_5 → rogue | action:basic / d20 | `1d20+6`: 8(kept) | 14 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 3(kept) | 3 raw → 3 applied slashing |
| 8 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |
| 9 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 11 raw → 11 applied slashing |
| 10 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 1(kept) | 7 vs 16: miss |
| 11 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 12 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |

## 05_overwhelming_line / aggressive / trial 5

Seed `2536008357766756819`; **party_victory** after 8 rounds. 288 integer draws; 202 journal facts. [Full sample](samples/05_overwhelming_line__aggressive__5.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-15.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [0.0, 5.0, 0.0], [5.0, 0.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [0.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | action_surge → ['veteran_4'] | None → [] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-10.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | veteran_6 | [[30.0, 45.0, 0.0], [25.0, 40.0, 0.0], [20.0, 35.0, 0.0], [15.0, 30.0, 0.0], [10.0, 25.0, 0.0], [5.0, 20.0, 0.0], [5.0, 15.0, 0.0]] | dodge → ['veteran_6'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |
| 2 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 3 | veteran_4 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 4 raw → 4 applied slashing |
| 4 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 9(kept) | 15 vs 16: miss |
| 5 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 4(kept) | 10 vs 16: miss |
| 6 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 16: hit |
| 7 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 8 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 9 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 10 | veteran_1 → fighter | action:basic / d20 | `1d20+6`: 15(kept) | 21 vs 18: hit |
| 11 | veteran_1 → fighter | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 12 | fighter → veteran_4 | action:action_surge / d20 | `1d20+7`: 8(kept) | 15 vs 17: miss |

## 06_spread_patrol / conservative / trial 0

Seed `3998505580300354623`; **party_victory** after 3 rounds. 80 integer draws; 47 journal facts. [Full sample](samples/06_spread_patrol__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_2 | [[0.0, 60.0, 0.0], [-5.0, 55.0, 0.0], [-10.0, 50.0, 0.0], [-15.0, 45.0, 0.0], [-20.0, 40.0, 0.0], [-25.0, 35.0, 0.0], [-30.0, 30.0, 0.0]] | dodge → ['raider_2'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0], [35.0, 25.0, 0.0], [40.0, 30.0, 0.0]] | basic → ['raider_3'] | off_hand_attack → ['raider_3'] | auto |
| 1 | raider_4 | [[60.0, 70.0, 0.0], [55.0, 65.0, 0.0], [50.0, 60.0, 0.0], [45.0, 55.0, 0.0], [40.0, 50.0, 0.0], [35.0, 45.0, 0.0], [30.0, 40.0, 0.0]] | dodge → ['raider_4'] | None → [] | auto |
| 1 | raider_1 | [[-40.0, 35.0, 0.0], [-35.0, 30.0, 0.0], [-30.0, 25.0, 0.0], [-25.0, 20.0, 0.0], [-20.0, 15.0, 0.0], [-15.0, 10.0, 0.0], [-10.0, 5.0, 0.0]] | dodge → ['raider_1'] | None → [] | auto |
| 1 | raider_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3 | action:basic / d20 | `1d20+7`: 1(kept) | 8 vs 13: miss |
| 2 | rogue → raider_3 | action:off_hand_attack / d20 | `1d20+7`: 5(kept) | 12 vs 13: miss |
| 3 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 7(kept) | 11 vs 16: miss |
| 4 | raider_4 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 13(kept), 13(discarded) | 15 vs 15: success |
| 5 | cleric → raider_4 | action:Sacred Flame / damage | `2d8`: 2(kept), 3(kept) | 5 raw → 0 applied radiant |
| 6 | wizard → raider_4 | action:Fire Bolt / d20 | `2d20kl1+7`: 7(kept), 18(discarded) | 14 vs 13: hit |
| 7 | wizard → raider_4 | action:Fire Bolt / damage | `2d10`: 10(kept), 8(kept) | 18 raw → 18 applied fire |
| 8 | raider_1 → fighter | action:basic / d20 | `1d20+4`: 10(kept) | 14 vs 18: miss |
| 9 | fighter → raider_2 | action:action_surge / d20 | `2d20kl1+7`: 7(discarded), 5(kept) | 12 vs 13: miss |
| 10 | fighter → raider_2 | action:action_surge / d20 | `2d20kl1+7`: 7(kept), 19(discarded) | 14 vs 13: hit |
| 11 | fighter → raider_2 | action:action_surge / damage | `1d8+4`: 5(kept) | 9 raw → 9 applied slashing |
| 12 | fighter → raider_2 | action:action_surge / d20 | `2d20kl1+7`: 15(kept), 20(discarded) | 22 vs 13: hit |

## 06_spread_patrol / typical / trial 0

Seed `3998505580300354623`; **party_victory** after 3 rounds. 91 integer draws; 52 journal facts. [Full sample](samples/06_spread_patrol__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_2 | [[0.0, 60.0, 0.0], [-5.0, 55.0, 0.0], [-10.0, 50.0, 0.0], [-15.0, 45.0, 0.0], [-20.0, 40.0, 0.0], [-25.0, 35.0, 0.0], [-30.0, 30.0, 0.0]] | dodge → ['raider_2'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0], [35.0, 25.0, 0.0], [40.0, 30.0, 0.0]] | basic → ['raider_3'] | off_hand_attack → ['raider_3'] | auto |
| 1 | raider_4 | [[60.0, 70.0, 0.0], [55.0, 65.0, 0.0], [50.0, 60.0, 0.0], [45.0, 55.0, 0.0], [40.0, 50.0, 0.0], [35.0, 45.0, 0.0], [30.0, 40.0, 0.0]] | dodge → ['raider_4'] | None → [] | auto |
| 1 | raider_1 | [[-40.0, 35.0, 0.0], [-35.0, 30.0, 0.0], [-30.0, 25.0, 0.0], [-25.0, 20.0, 0.0], [-20.0, 15.0, 0.0], [-15.0, 10.0, 0.0], [-10.0, 5.0, 0.0]] | dodge → ['raider_1'] | None → [] | auto |
| 1 | raider_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3 | action:basic / d20 | `1d20+7`: 1(kept) | 8 vs 13: miss |
| 2 | rogue → raider_3 | action:off_hand_attack / d20 | `1d20+7`: 5(kept) | 12 vs 13: miss |
| 3 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 7(kept) | 11 vs 16: miss |
| 4 | raider_4 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 13(kept), 13(discarded) | 15 vs 15: success |
| 5 | cleric → raider_4 | action:Sacred Flame / damage | `2d8`: 2(kept), 3(kept) | 5 raw → 0 applied radiant |
| 6 | raider_2 → wizard | action:Fireball / saving_throw | `2d20kh1+2`: 7(discarded), 19(kept) | 21 vs 15: success |
| 7 | wizard → raider_2 | action:Fireball / damage | `8d6`: 2(kept), 5(kept), 5(kept), 4(kept), 6(kept), 3(kept), 2(kept), 2(kept) | 29 raw → 14 applied fire |
| 8 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 9(kept), 15(discarded) | 16 vs 13: hit |
| 9 | fighter → raider_1 | action:action_surge / damage | `1d8+4`: 5(kept) | 9 raw → 9 applied slashing |
| 10 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 13(discarded), 12(kept) | 19 vs 13: hit |
| 11 | fighter → raider_1 | action:action_surge / damage | `1d8+4`: 5(kept) | 9 raw → 9 applied slashing |
| 12 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 15(kept), 17(discarded) | 22 vs 13: hit |

## 06_spread_patrol / aggressive / trial 0

Seed `3998505580300354623`; **party_victory** after 3 rounds. 90 integer draws; 48 journal facts. [Full sample](samples/06_spread_patrol__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_2 | [[0.0, 60.0, 0.0], [-5.0, 55.0, 0.0], [-10.0, 50.0, 0.0], [-15.0, 45.0, 0.0], [-20.0, 40.0, 0.0], [-25.0, 35.0, 0.0], [-30.0, 30.0, 0.0]] | dodge → ['raider_2'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0], [35.0, 25.0, 0.0], [40.0, 30.0, 0.0]] | basic → ['raider_3'] | off_hand_attack → ['raider_3'] | auto |
| 1 | raider_4 | [[60.0, 70.0, 0.0], [55.0, 65.0, 0.0], [50.0, 60.0, 0.0], [45.0, 55.0, 0.0], [40.0, 50.0, 0.0], [35.0, 45.0, 0.0], [30.0, 40.0, 0.0]] | dodge → ['raider_4'] | None → [] | auto |
| 1 | raider_1 | [[-40.0, 35.0, 0.0], [-35.0, 30.0, 0.0], [-30.0, 25.0, 0.0], [-25.0, 20.0, 0.0], [-20.0, 15.0, 0.0], [-15.0, 10.0, 0.0], [-10.0, 5.0, 0.0]] | dodge → ['raider_1'] | None → [] | auto |
| 1 | raider_3 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_4'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3 | action:basic / d20 | `1d20+7`: 1(kept) | 8 vs 13: miss |
| 2 | rogue → raider_3 | action:off_hand_attack / d20 | `1d20+7`: 5(kept) | 12 vs 13: miss |
| 3 | raider_3 → rogue | action:basic / d20 | `1d20+4`: 7(kept) | 11 vs 16: miss |
| 4 | raider_4 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 13(kept), 13(discarded) | 15 vs 15: success |
| 5 | cleric → raider_4 | action:Sacred Flame / damage | `2d8`: 2(kept), 3(kept) | 5 raw → 0 applied radiant |
| 6 | raider_2 → wizard | action:Fireball / saving_throw | `2d20kh1+2`: 7(discarded), 19(kept) | 21 vs 15: success |
| 7 | wizard → raider_2 | action:Fireball / damage | `8d6`: 2(kept), 5(kept), 5(kept), 4(kept), 6(kept), 3(kept), 2(kept), 2(kept) | 29 raw → 14 applied fire |
| 8 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 9(kept), 15(discarded) | 16 vs 13: hit |
| 9 | fighter → raider_1 | action:action_surge / damage | `1d8+4`: 5(kept) | 9 raw → 9 applied slashing |
| 10 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 13(discarded), 12(kept) | 19 vs 13: hit |
| 11 | fighter → raider_1 | action:action_surge / damage | `1d8+4`: 5(kept) | 9 raw → 9 applied slashing |
| 12 | fighter → raider_1 | action:action_surge / d20 | `2d20kl1+7`: 15(kept), 17(discarded) | 22 vs 13: hit |

## 07_attrition / conservative / trial 0

Seed `12386736296039820462`; **party_victory** after 8 rounds. 173 integer draws; 106 journal facts. [Full sample](samples/07_attrition__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 15.0, 0.0], [15.0, 20.0, 0.0], [20.0, 25.0, 0.0], [25.0, 30.0, 0.0]] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |
| 1 | wizard | [] | Fireball → ['raider_1_e0_1'] | None → [] | auto |
| 1 | raider_3_e0_1 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-15.0, 15.0, 0.0], [-20.0, 20.0, 0.0], [-20.0, 25.0, 0.0], [-15.0, 30.0, 0.0]] | basic → ['raider_1_e0_1'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_3_e0_1'] | None → [] | auto |
| 2 | rogue | [] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3_e0_1 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 13: hit |
| 2 | rogue → raider_3_e0_1 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → raider_3_e0_1 | action:off_hand_attack / d20 | `1d20+7`: 16(kept) | 23 vs 13: hit |
| 4 | rogue → raider_3_e0_1 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 5 | raider_1_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 6 | wizard → raider_1_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 14 applied fire |
| 7 | raider_2_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 4(kept) | 6 vs 15: failure |
| 8 | wizard → raider_2_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 28 applied fire |
| 9 | raider_3_e0_1 → rogue | action:basic / d20 | `1d20+4`: 15(kept) | 19 vs 16: hit |
| 10 | raider_3_e0_1 → rogue | action:basic / damage | `1d6+2`: 4(kept) | 3 raw → 3 applied slashing |
| 11 | fighter → raider_1_e0_1 | action:basic / d20 | `1d20+7`: 20(kept) | 27 vs 13: hit |
| 12 | fighter → raider_1_e0_1 | action:basic / damage | `1d8+4`: 1(kept), 7(kept) | 12 raw → 12 applied slashing |

## 07_attrition / typical / trial 0

Seed `12386736296039820462`; **party_victory** after 9 rounds. 203 integer draws; 126 journal facts. [Full sample](samples/07_attrition__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 15.0, 0.0], [15.0, 20.0, 0.0], [20.0, 25.0, 0.0], [25.0, 30.0, 0.0]] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |
| 1 | wizard | [] | Fireball → ['raider_1_e0_1'] | None → [] | auto |
| 1 | raider_3_e0_1 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0], [-15.0, 15.0, 0.0], [-20.0, 20.0, 0.0], [-20.0, 25.0, 0.0], [-15.0, 30.0, 0.0]] | basic → ['raider_1_e0_1'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_3_e0_1'] | None → [] | auto |
| 2 | rogue | [] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3_e0_1 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 13: hit |
| 2 | rogue → raider_3_e0_1 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → raider_3_e0_1 | action:off_hand_attack / d20 | `1d20+7`: 16(kept) | 23 vs 13: hit |
| 4 | rogue → raider_3_e0_1 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 5 | raider_1_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 6 | wizard → raider_1_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 14 applied fire |
| 7 | raider_2_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 4(kept) | 6 vs 15: failure |
| 8 | wizard → raider_2_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 28 applied fire |
| 9 | raider_3_e0_1 → rogue | action:basic / d20 | `1d20+4`: 15(kept) | 19 vs 16: hit |
| 10 | raider_3_e0_1 → rogue | action:basic / damage | `1d6+2`: 4(kept) | 3 raw → 3 applied slashing |
| 11 | fighter → raider_1_e0_1 | action:basic / d20 | `1d20+7`: 20(kept) | 27 vs 13: hit |
| 12 | fighter → raider_1_e0_1 | action:basic / damage | `1d8+4`: 1(kept), 7(kept) | 12 raw → 12 applied slashing |

## 07_attrition / typical / trial 987

Seed `1006308757995676937`; **enemy_victory** after 16 rounds. 336 integer draws; 226 journal facts. [Full sample](samples/07_attrition__typical__987.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_2_e0_1 | [[10.0, 35.0, 0.0], [5.0, 30.0, 0.0], [0.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [-5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | raider_1_e0_1 | [[-10.0, 35.0, 0.0], [-15.0, 30.0, 0.0], [-10.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [0.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 15.0, 0.0], [15.0, 20.0, 0.0], [20.0, 25.0, 0.0], [25.0, 30.0, 0.0]] | action_surge → ['raider_3_e0_1'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_3_e0_1'] | Healing Word → ['fighter'] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0], [30.0, 30.0, 0.0]] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |
| 1 | wizard | [] | Scorching Ray → ['raider_2_e0_1'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | raider_2_e0_1 → rogue | action:basic / d20 | `1d20+4`: 18(kept) | 22 vs 16: hit |
| 2 | raider_2_e0_1 → rogue | action:basic / damage | `1d6+2`: 4(kept) | 3 raw → 3 applied slashing |
| 3 | raider_1_e0_1 → rogue | action:basic / d20 | `1d20+4`: 10(kept) | 14 vs 16: miss |
| 4 | raider_1_e0_1 → fighter | action:basic / d20 | `1d20+4`: 20(kept) | 24 vs 18: hit |
| 5 | raider_1_e0_1 → fighter | action:basic / damage | `1d6+2`: 2(kept), 6(kept) | 10 raw → 10 applied slashing |
| 6 | raider_2_e0_1 → fighter | action:basic / d20 | `1d20+4`: 8(kept) | 12 vs 18: miss |
| 7 | fighter → raider_3_e0_1 | action:action_surge / d20 | `1d20+7`: 18(kept) | 25 vs 13: hit |
| 8 | fighter → raider_3_e0_1 | action:action_surge / damage | `1d8+4`: 1(kept) | 5 raw → 5 applied slashing |
| 9 | fighter → raider_3_e0_1 | action:action_surge / d20 | `1d20+7`: 2(kept) | 9 vs 13: miss |
| 10 | fighter → raider_3_e0_1 | action:action_surge / d20 | `1d20+7`: 4(kept) | 11 vs 13: miss |
| 11 | fighter → raider_3_e0_1 | action:action_surge / d20 | `1d20+7`: 8(kept) | 15 vs 13: hit |
| 12 | fighter → raider_3_e0_1 | action:action_surge / damage | `1d8+4`: 6(kept) | 10 raw → 10 applied slashing |

## 07_attrition / aggressive / trial 0

Seed `12386736296039820462`; **party_victory** after 11 rounds. 249 integer draws; 155 journal facts. [Full sample](samples/07_attrition__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 5.0, 0.0], [5.0, 10.0, 0.0], [10.0, 15.0, 0.0], [15.0, 20.0, 0.0], [20.0, 25.0, 0.0], [25.0, 30.0, 0.0]] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |
| 1 | wizard | [] | Fireball → ['raider_1_e0_1'] | None → [] | auto |
| 1 | raider_3_e0_1 | [] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0], [10.0, 10.0, 0.0], [15.0, 15.0, 0.0], [20.0, 20.0, 0.0], [25.0, 25.0, 0.0], [30.0, 30.0, 0.0]] | action_surge → ['raider_3_e0_1'] | None → [] | auto |
| 1 | raider_1_e0_1 | [[-10.0, 35.0, 0.0], [-5.0, 30.0, 0.0], [0.0, 25.0, 0.0], [5.0, 20.0, 0.0], [10.0, 15.0, 0.0], [15.0, 20.0, 0.0], [20.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_1_e0_1'] | Healing Word (slot 3) → ['rogue'] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → raider_3_e0_1 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 13: hit |
| 2 | rogue → raider_3_e0_1 | action:basic / damage | `1d6+4`: 4(kept) | 8 raw → 8 applied piercing |
| 3 | rogue → raider_3_e0_1 | action:off_hand_attack / d20 | `1d20+7`: 16(kept) | 23 vs 13: hit |
| 4 | rogue → raider_3_e0_1 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 5 | raider_1_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 17(kept) | 19 vs 15: success |
| 6 | wizard → raider_1_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 14 applied fire |
| 7 | raider_2_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 4(kept) | 6 vs 15: failure |
| 8 | wizard → raider_2_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 2(kept), 1(kept), 5(kept), 6(kept), 3(kept), 2(kept) | 28 raw → 28 applied fire |
| 9 | raider_3_e0_1 → rogue | action:basic / d20 | `1d20+4`: 15(kept) | 19 vs 16: hit |
| 10 | raider_3_e0_1 → rogue | action:basic / damage | `1d6+2`: 4(kept) | 3 raw → 3 applied slashing |
| 11 | fighter → raider_3_e0_1 | action:action_surge / d20 | `1d20+7`: 20(kept) | 27 vs 13: hit |
| 12 | fighter → raider_3_e0_1 | action:action_surge / damage | `1d8+4`: 1(kept), 7(kept) | 12 raw → 12 applied slashing |

## 07_attrition / aggressive / trial 828

Seed `16208312914598314367`; **enemy_victory** after 16 rounds. 364 integer draws; 224 journal facts. [Full sample](samples/07_attrition__aggressive__828.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | raider_3_e0_1 | [[30.0, 35.0, 0.0], [25.0, 30.0, 0.0], [20.0, 25.0, 0.0], [15.0, 20.0, 0.0], [10.0, 15.0, 0.0], [5.0, 10.0, 0.0], [5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['raider_2_e0_1'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['raider_3_e0_1'] | Healing Word (slot 3) → ['rogue'] | auto |
| 1 | rogue | [] | basic → ['raider_3_e0_1'] | off_hand_attack → ['raider_3_e0_1'] | auto |
| 1 | raider_2_e0_1 | [[10.0, 35.0, 0.0], [5.0, 30.0, 0.0], [0.0, 25.0, 0.0], [-5.0, 20.0, 0.0], [0.0, 15.0, 0.0], [5.0, 10.0, 0.0], [10.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | fighter | [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]] | basic → ['raider_2_e0_1'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | raider_3_e0_1 → rogue | action:basic / d20 | `1d20+4`: 14(kept) | 18 vs 16: hit |
| 2 | raider_3_e0_1 → rogue | action:basic / damage | `1d6+2`: 2(kept) | 2 raw → 2 applied slashing |
| 3 | raider_1_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 9(kept) | 11 vs 15: failure |
| 4 | wizard → raider_1_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 4(kept), 4(kept), 3(kept), 2(kept), 5(kept), 6(kept) | 33 raw → 33 applied fire |
| 5 | raider_2_e0_1 → wizard | action:Fireball / saving_throw | `1d20+2`: 13(kept) | 15 vs 15: success |
| 6 | wizard → raider_2_e0_1 | action:Fireball / damage | `8d6`: 5(kept), 4(kept), 4(kept), 4(kept), 3(kept), 2(kept), 5(kept), 6(kept) | 33 raw → 16 applied fire |
| 7 | raider_3_e0_1 → cleric | action:Sacred Flame / saving_throw | `1d20+2`: 14(kept) | 16 vs 15: success |
| 8 | cleric → raider_3_e0_1 | action:Sacred Flame / damage | `2d8`: 1(kept), 3(kept) | 4 raw → 0 applied radiant |
| 9 | cleric → rogue | action:Healing Word (slot 3) / healing | `3d4+4`: 3(kept), 2(kept), 2(kept) | 11 rolled → 2 healed |
| 10 | rogue → raider_3_e0_1 | action:basic / d20 | `1d20+7`: 16(kept) | 23 vs 13: hit |
| 11 | rogue → raider_3_e0_1 | action:basic / damage | `1d6+4`: 2(kept) | 6 raw → 6 applied piercing |
| 12 | rogue → raider_3_e0_1 | action:basic / damage | `3d6`: 4(kept), 4(kept), 5(kept) | 13 raw → 13 applied piercing |

## 08_five_veterans / conservative / trial 0

Seed `5124593117553265138`; **party_victory** after 11 rounds. 279 integer draws; 191 journal facts. [Full sample](samples/08_five_veterans__conservative__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0]] | basic → ['veteran_5'] | off_hand_attack → ['veteran_5'] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-20.0, 25.0, 0.0], [-15.0, 20.0, 0.0], [-10.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0], [10.0, 0.0, 0.0]] | dodge → ['veteran_4'] | None → [] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(kept), 5(discarded) | 11 vs 15: failure |
| 2 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 6(kept), 5(kept) | 11 raw → 11 applied radiant |
| 3 | rogue → veteran_5 | action:basic / d20 | `2d20kl1+7`: 9(discarded), 3(kept) | 10 vs 17: miss |
| 4 | rogue → veteran_5 | action:off_hand_attack / d20 | `2d20kl1+7`: 4(kept), 15(discarded) | 11 vs 17: miss |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 20(kept) | 26 vs 16: hit |
| 6 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 1(kept), 8(kept) | 6 raw → 6 applied slashing |
| 7 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |
| 8 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 9 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 10 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 11 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |
| 12 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |

## 08_five_veterans / conservative / trial 1

Seed `1395957837632404571`; **enemy_victory** after 17 rounds. 320 integer draws; 222 journal facts. [Full sample](samples/08_five_veterans__conservative__1.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0], [35.0, 25.0, 0.0]] | basic → ['veteran_4'] | off_hand_attack → ['veteran_4'] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [5.0, 25.0, 0.0], [10.0, 20.0, 0.0], [15.0, 15.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | Healing Word → ['rogue'] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [25.0, 25.0, 0.0], [30.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['veteran_1'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_4 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 17: hit |
| 2 | rogue → veteran_4 | action:basic / damage | `1d6+4`: 6(kept) | 10 raw → 10 applied piercing |
| 3 | rogue → veteran_4 | action:off_hand_attack / d20 | `1d20+7`: 19(kept) | 26 vs 17: hit |
| 4 | rogue → veteran_4 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 5 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 11(kept) | 17 vs 16: hit |
| 6 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 7(kept) | 5 raw → 5 applied slashing |
| 7 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 8 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 11 raw → 11 applied slashing |
| 9 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(kept), 5(discarded) | 11 vs 15: failure |
| 10 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 4(kept), 7(kept) | 11 raw → 11 applied radiant |
| 11 | cleric → rogue | action:Healing Word / healing | `1d4+4`: 3(kept) | 7 rolled → 7 healed |
| 12 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |

## 08_five_veterans / typical / trial 0

Seed `5124593117553265138`; **party_victory** after 8 rounds. 242 integer draws; 161 journal facts. [Full sample](samples/08_five_veterans__typical__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0]] | basic → ['veteran_5'] | off_hand_attack → ['veteran_5'] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-20.0, 25.0, 0.0], [-15.0, 20.0, 0.0], [-10.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0], [10.0, 0.0, 0.0]] | dodge → ['veteran_4'] | None → [] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(kept), 5(discarded) | 11 vs 15: failure |
| 2 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 6(kept), 5(kept) | 11 raw → 11 applied radiant |
| 3 | rogue → veteran_5 | action:basic / d20 | `2d20kl1+7`: 9(discarded), 3(kept) | 10 vs 17: miss |
| 4 | rogue → veteran_5 | action:off_hand_attack / d20 | `2d20kl1+7`: 4(kept), 15(discarded) | 11 vs 17: miss |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 20(kept) | 26 vs 16: hit |
| 6 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 1(kept), 8(kept) | 6 raw → 6 applied slashing |
| 7 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |
| 8 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 9 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 10 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 11 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |
| 12 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |

## 08_five_veterans / typical / trial 3

Seed `6213116281262164776`; **enemy_victory** after 7 rounds. 201 integer draws; 134 journal facts. [Full sample](samples/08_five_veterans__typical__3.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0]] | basic → ['veteran_5'] | off_hand_attack → ['veteran_5'] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [-5.0, 25.0, 0.0], [-10.0, 20.0, 0.0], [-10.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['veteran_3'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 4(kept) | 10 vs 16: miss |
| 2 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 5(kept) | 11 vs 16: miss |
| 3 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(discarded), 11(kept) | 13 vs 15: failure |
| 4 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 2(kept), 7(kept) | 9 raw → 9 applied radiant |
| 5 | veteran_4 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 6 | veteran_4 → rogue | action:basic / damage | `1d8+3`: 1(kept) | 2 raw → 2 applied slashing |
| 7 | rogue → veteran_5 | action:basic / d20 | `2d20kl1+7`: 17(discarded), 9(kept) | 16 vs 17: miss |
| 8 | rogue → veteran_5 | action:off_hand_attack / d20 | `2d20kl1+7`: 5(discarded), 3(kept) | 10 vs 17: miss |
| 9 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 16(kept) | 22 vs 16: hit |
| 10 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 1(kept) | 4 raw → 4 applied slashing |
| 11 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 12 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 2(kept) | 5 raw → 5 applied slashing |

## 08_five_veterans / aggressive / trial 0

Seed `5124593117553265138`; **enemy_victory** after 8 rounds. 229 integer draws; 157 journal facts. [Full sample](samples/08_five_veterans__aggressive__0.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | None → [] | auto |
| 1 | rogue | [[10.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [-5.0, 5.0, 0.0], [-10.0, 10.0, 0.0]] | basic → ['veteran_5'] | off_hand_attack → ['veteran_5'] | auto |
| 1 | veteran_1 | [[-20.0, 30.0, 0.0], [-20.0, 25.0, 0.0], [-15.0, 20.0, 0.0], [-10.0, 15.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_4 | [[40.0, 30.0, 0.0], [35.0, 25.0, 0.0], [30.0, 20.0, 0.0], [25.0, 15.0, 0.0], [20.0, 10.0, 0.0], [15.0, 5.0, 0.0], [10.0, 0.0, 0.0]] | dodge → ['veteran_4'] | None → [] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [15.0, 25.0, 0.0], [10.0, 20.0, 0.0], [5.0, 15.0, 0.0], [0.0, 10.0, 0.0], [-5.0, 5.0, 0.0]] | basic → ['rogue'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(kept), 5(discarded) | 11 vs 15: failure |
| 2 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 6(kept), 5(kept) | 11 raw → 11 applied radiant |
| 3 | rogue → veteran_5 | action:basic / d20 | `2d20kl1+7`: 9(discarded), 3(kept) | 10 vs 17: miss |
| 4 | rogue → veteran_5 | action:off_hand_attack / d20 | `2d20kl1+7`: 4(kept), 15(discarded) | 11 vs 17: miss |
| 5 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 20(kept) | 26 vs 16: hit |
| 6 | veteran_1 → rogue | action:basic / damage | `1d8+3`: 1(kept), 8(kept) | 6 raw → 6 applied slashing |
| 7 | veteran_1 → rogue | action:basic / d20 | `1d20+6`: 6(kept) | 12 vs 16: miss |
| 8 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 14(kept) | 20 vs 16: hit |
| 9 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 6(kept) | 9 raw → 9 applied slashing |
| 10 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 18(kept) | 24 vs 16: hit |
| 11 | veteran_3 → rogue | action:basic / damage | `1d8+3`: 4(kept) | 7 raw → 7 applied slashing |
| 12 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 19(kept) | 25 vs 16: hit |

## 08_five_veterans / aggressive / trial 1

Seed `1395957837632404571`; **party_victory** after 13 rounds. 308 integer draws; 212 journal facts. [Full sample](samples/08_five_veterans__aggressive__1.json.gz)

First six declared turns (full decisions are in the sample):

| Round | Actor | Move (feet-space waypoints) | Main → targets | Bonus → targets | Reaction |
|---:|---|---|---|---|---|
| 1 | rogue | [[10.0, 0.0, 0.0], [15.0, 5.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0], [35.0, 25.0, 0.0]] | basic → ['veteran_4'] | off_hand_attack → ['veteran_4'] | auto |
| 1 | veteran_2 | [[0.0, 30.0, 0.0], [5.0, 25.0, 0.0], [10.0, 20.0, 0.0], [15.0, 15.0, 0.0], [20.0, 10.0, 0.0], [25.0, 15.0, 0.0], [30.0, 20.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | veteran_5 | [[-10.0, 45.0, 0.0], [-15.0, 40.0, 0.0], [-20.0, 35.0, 0.0], [-25.0, 30.0, 0.0], [-25.0, 25.0, 0.0], [-20.0, 20.0, 0.0], [-15.0, 15.0, 0.0]] | dodge → ['veteran_5'] | None → [] | auto |
| 1 | cleric | [] | Sacred Flame → ['veteran_5'] | Healing Word (slot 3) → ['rogue'] | auto |
| 1 | veteran_3 | [[20.0, 30.0, 0.0], [25.0, 25.0, 0.0], [30.0, 25.0, 0.0]] | basic → ['rogue'] | None → [] | auto |
| 1 | wizard | [] | Fireball → ['veteran_1'] | None → [] | auto |

| # | Source → target | Action / fact | Dice faces | Total / outcome |
|---:|---|---|---|---|
| 1 | rogue → veteran_4 | action:basic / d20 | `1d20+7`: 18(kept) | 25 vs 17: hit |
| 2 | rogue → veteran_4 | action:basic / damage | `1d6+4`: 6(kept) | 10 raw → 10 applied piercing |
| 3 | rogue → veteran_4 | action:off_hand_attack / d20 | `1d20+7`: 19(kept) | 26 vs 17: hit |
| 4 | rogue → veteran_4 | action:off_hand_attack / damage | `1d6`: 5(kept) | 5 raw → 5 applied piercing |
| 5 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 11(kept) | 17 vs 16: hit |
| 6 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 7(kept) | 5 raw → 5 applied slashing |
| 7 | veteran_2 → rogue | action:basic / d20 | `1d20+6`: 13(kept) | 19 vs 16: hit |
| 8 | veteran_2 → rogue | action:basic / damage | `1d8+3`: 8(kept) | 11 raw → 11 applied slashing |
| 9 | veteran_5 → cleric | action:Sacred Flame / saving_throw | `2d20kh1+2`: 9(kept), 5(discarded) | 11 vs 15: failure |
| 10 | cleric → veteran_5 | action:Sacred Flame / damage | `2d8`: 4(kept), 7(kept) | 11 raw → 11 applied radiant |
| 11 | cleric → rogue | action:Healing Word (slot 3) / healing | `3d4+4`: 3(kept), 2(kept), 1(kept) | 10 rolled → 10 healed |
| 12 | veteran_3 → rogue | action:basic / d20 | `1d20+6`: 7(kept) | 13 vs 16: miss |
