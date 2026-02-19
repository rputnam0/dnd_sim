import random
import math
import statistics
from dataclasses import dataclass

# -----------------------------
# Dice + combat helpers
# -----------------------------


def roll(d: int, n: int = 1) -> int:
    return sum(random.randint(1, d) for _ in range(n))


def half_damage(x: int) -> int:
    # 5e resistance halves, rounding down
    return x // 2


def attack_roll(
    atk_bonus: int, target_ac: int, disadvantage: bool = False, advantage: bool = False
):
    # advantage/disadvantage cancel
    if advantage and disadvantage:
        advantage = disadvantage = False

    if advantage:
        r = max(random.randint(1, 20), random.randint(1, 20))
    elif disadvantage:
        r = min(random.randint(1, 20), random.randint(1, 20))
    else:
        r = random.randint(1, 20)

    crit = r == 20
    hit = crit or (r + atk_bonus >= target_ac)
    return hit, crit


def weapon_damage(die: int, die_n: int, flat: int, crit: bool = False) -> int:
    dice = die_n * (2 if crit else 1)
    return roll(die, dice) + flat


# -----------------------------
# PC model
# -----------------------------


@dataclass
class PC:
    name: str
    hp: int
    ki: int = 0
    ki_spent: int = 0
    next_disadvantage: bool = False
    pulse_damage: int = 0
    rider_count: int = 0


# -----------------------------
# Simulation
# -----------------------------


def simulate_phase1(
    n_trials: int = 50_000,
    seed: int | None = 1,
    # Pylon stats
    pylon_ac: int = 15,
    pylon_hp: int = 45,
    # Procedure DC
    proc_dc: int = 15,
    # Druid procedure bonuses (adjust for your druid build)
    druid_past_bonus: int = 1,  # Religion/Performance/Persuasion etc.
    druid_future_bonus: int = 7,  # Insight/Investigation etc.
    # Fury procedure bonus for Present
    fury_present_bonus: int = 5,  # Arcana +5 from your sheet
    # Whether Prism pulse counts as "magical" for gnomish advantage on WIS saves
    prism_magical: bool = False,
    # Who is in pulse range (10 ft)?
    monks_in_pulse_range: bool = True,
    druid_in_pulse_range: bool = False,
):
    """
    Models:
    - Isak (Open Hand): staff +8 (1d6+5), unarmed +7 (1d6+4), Savage Attacker on first staff hit each turn,
      Flurry uses 1 ki to make 2 bonus unarmed strikes (net +1 bonus strike vs default).
    - Fury: all attacks +8 (1d6+5), Flurry same as above.
    - Druid: Produce Flame +7 to hit, 2d8 (no flat). Procedure attempt is "free" (doesn't consume Action).
    - Present pylon: Fury spends one "attack" to do the procedure (home rule), leaving 1 attack + bonus action.
    - Exposed is treated as applying for the full round (procedure happens early).
    - Breakpoint pulses at 30 and 15; if you cross both in one round, you take both pulses.
    - Riders: only Future rider (disadvantage on next attack) is modeled mechanically; others are tracked but
      assumed not to change DPR (push/no-reactions).
    """

    if seed is not None:
        random.seed(seed)

    # Collect outputs
    total_rounds = []
    isak_ki_spent = []
    fury_ki_spent = []
    isak_pulse_dmg = []
    fury_pulse_dmg = []
    druid_pulse_dmg = []
    isak_riders = []
    fury_riders = []
    druid_riders = []

    def summary(arr):
        arr_sorted = sorted(arr)
        mean = statistics.mean(arr_sorted)
        med = statistics.median(arr_sorted)
        p10 = arr_sorted[int(0.10 * len(arr_sorted))]
        p90 = arr_sorted[int(0.90 * len(arr_sorted)) - 1]
        return mean, med, p10, p90

    for _ in range(n_trials):
        # NOTE: Isak HP wasn't provided in your paste; set to a placeholder so "TPK during phase" can be detected.
        isak = PC("Isak", hp=60, ki=8)
        fury = PC("Fury", hp=71, ki=8)
        druid = PC("Druid", hp=52, ki=0)

        def pulse(pylon_type: str):
            # pylon_type in {"past","present","future"}
            targets = []
            if monks_in_pulse_range:
                targets += [isak, fury]
            if druid_in_pulse_range:
                targets += [druid]

            for c in targets:
                # Save mods inferred from your sheets / a generic druid:
                # Isak: CON +2, DEX +4, WIS +2 (gnome advantage vs "magical" Prism if prism_magical=True)
                # Fury: CON +3, DEX +5, WIS +4
                # Druid baseline: CON +2, DEX +1, WIS +4
                if c.name == "Isak":
                    if pylon_type == "past":
                        mod, adv = 2, False
                    elif pylon_type == "present":
                        mod, adv = 4, False
                    else:
                        mod, adv = 2, prism_magical
                elif c.name == "Fury":
                    if pylon_type == "past":
                        mod, adv = 3, False
                    elif pylon_type == "present":
                        mod, adv = 5, False
                    else:
                        mod, adv = 4, False
                else:  # Druid
                    if pylon_type == "past":
                        mod, adv = 2, False
                    elif pylon_type == "present":
                        mod, adv = 1, False
                    else:
                        mod, adv = 4, False

                s = (
                    max(random.randint(1, 20), random.randint(1, 20))
                    if adv
                    else random.randint(1, 20)
                ) + mod
                success = s >= proc_dc
                dmg = roll(6, 2)
                if success:
                    dmg = half_damage(dmg)

                c.hp -= dmg
                c.pulse_damage += dmg

                if not success:
                    c.rider_count += 1
                    if pylon_type == "future":
                        c.next_disadvantage = True  # disadvantage on next attack

        def druid_attack(exposed: bool) -> int:
            hit, crit = attack_roll(7, pylon_ac, disadvantage=druid.next_disadvantage)
            druid.next_disadvantage = False
            if not hit:
                return 0
            dice = 4 if crit else 2
            base = roll(8, dice)  # Produce Flame 2d8
            return base if exposed else half_damage(base)

        def druid_proc(pylon_type: str) -> bool:
            bonus = druid_past_bonus if pylon_type == "past" else druid_future_bonus
            return (random.randint(1, 20) + bonus) >= proc_dc

        def isak_turn(exposed: bool) -> int:
            dmg_total = 0
            flurry = exposed and isak.ki > 0

            savage_used = False

            # 2 staff attacks: +8, 1d6+5
            for _ in range(2):
                hit, crit = attack_roll(8, pylon_ac, disadvantage=isak.next_disadvantage)
                isak.next_disadvantage = False
                if hit:
                    base = weapon_damage(6, 1, 5, crit)
                    # Savage Attacker once/turn on melee weapon damage roll:
                    if not savage_used:
                        alt = weapon_damage(6, 1, 5, crit)
                        base = max(base, alt)
                        savage_used = True
                    dmg_total += base if exposed else half_damage(base)

            # Bonus action unarmed: +7, 1d6+4
            n_bonus = 2 if flurry else 1
            if flurry:
                isak.ki -= 1
                isak.ki_spent += 1
            for _ in range(n_bonus):
                hit, crit = attack_roll(7, pylon_ac, disadvantage=isak.next_disadvantage)
                isak.next_disadvantage = False
                if hit:
                    base = weapon_damage(6, 1, 4, crit)
                    dmg_total += base if exposed else half_damage(base)

            return dmg_total

        def fury_full_turn(exposed: bool) -> int:
            dmg_total = 0
            flurry = exposed and fury.ki > 0

            # 2 attacks: +8, 1d6+5
            for _ in range(2):
                hit, crit = attack_roll(8, pylon_ac, disadvantage=fury.next_disadvantage)
                fury.next_disadvantage = False
                if hit:
                    base = weapon_damage(6, 1, 5, crit)
                    dmg_total += base if exposed else half_damage(base)

            n_bonus = 2 if flurry else 1
            if flurry:
                fury.ki -= 1
                fury.ki_spent += 1
            for _ in range(n_bonus):
                hit, crit = attack_roll(8, pylon_ac, disadvantage=fury.next_disadvantage)
                fury.next_disadvantage = False
                if hit:
                    base = weapon_damage(6, 1, 5, crit)
                    dmg_total += base if exposed else half_damage(base)

            return dmg_total

        def fury_present_turn(exposed: bool) -> int:
            """Present pylon: Fury uses one 'attack' to do Procedure; has 1 attack remaining + bonus action."""
            dmg_total = 0
            flurry = exposed and fury.ki > 0

            # 1 remaining attack: +8, 1d6+5
            hit, crit = attack_roll(8, pylon_ac, disadvantage=fury.next_disadvantage)
            fury.next_disadvantage = False
            if hit:
                base = weapon_damage(6, 1, 5, crit)
                dmg_total += base if exposed else half_damage(base)

            n_bonus = 2 if flurry else 1
            if flurry:
                fury.ki -= 1
                fury.ki_spent += 1
            for _ in range(n_bonus):
                hit, crit = attack_roll(8, pylon_ac, disadvantage=fury.next_disadvantage)
                fury.next_disadvantage = False
                if hit:
                    base = weapon_damage(6, 1, 5, crit)
                    dmg_total += base if exposed else half_damage(base)

            return dmg_total

        rounds = 0

        # Focus-fire pylons in order
        for pylon_type in ["past", "present", "future"]:
            hp = pylon_hp
            trig30 = False
            trig15 = False

            while hp > 0 and isak.hp > 0 and fury.hp > 0 and druid.hp > 0:
                rounds += 1
                pre_hp = hp

                # Determine exposure (procedure early in round)
                if pylon_type == "past":
                    exposed = druid_proc("past")
                elif pylon_type == "future":
                    exposed = druid_proc("future")
                else:
                    # Fury does Present procedure (costs an "attack")
                    exposed = (random.randint(1, 20) + fury_present_bonus) >= proc_dc

                # Party attacks this round
                dmg = 0
                dmg += druid_attack(exposed)
                dmg += isak_turn(exposed)
                if pylon_type == "present":
                    dmg += fury_present_turn(exposed)
                else:
                    dmg += fury_full_turn(exposed)

                hp -= dmg

                # Breakpoints (can trigger both in one round)
                if (not trig30) and pre_hp > 30 and hp <= 30:
                    trig30 = True
                    pulse(pylon_type)

                if (not trig15) and pre_hp > 15 and hp <= 15:
                    trig15 = True
                    pulse(pylon_type)

        # Record trial
        total_rounds.append(rounds)
        isak_ki_spent.append(isak.ki_spent)
        fury_ki_spent.append(fury.ki_spent)
        isak_pulse_dmg.append(isak.pulse_damage)
        fury_pulse_dmg.append(fury.pulse_damage)
        druid_pulse_dmg.append(druid.pulse_damage)
        isak_riders.append(isak.rider_count)
        fury_riders.append(fury.rider_count)
        druid_riders.append(druid.rider_count)

    return {
        "rounds_mean_med_p10_p90": summary(total_rounds),
        "isak_ki_mean_med_p10_p90": summary(isak_ki_spent),
        "fury_ki_mean_med_p10_p90": summary(fury_ki_spent),
        "isak_pulse_dmg_mean_med_p10_p90": summary(isak_pulse_dmg),
        "fury_pulse_dmg_mean_med_p10_p90": summary(fury_pulse_dmg),
        "druid_pulse_dmg_mean_med_p10_p90": summary(druid_pulse_dmg),
        "isak_riders_mean_med_p10_p90": summary(isak_riders),
        "fury_riders_mean_med_p10_p90": summary(fury_riders),
        "druid_riders_mean_med_p10_p90": summary(druid_riders),
    }


if __name__ == "__main__":
    # Baseline druid: Past bonus +1, Future bonus +7, Present handled by Fury Arcana +5
    out = simulate_phase1(
        n_trials=50_000,
        seed=1,
        druid_past_bonus=1,
        druid_future_bonus=7,
        fury_present_bonus=5,
        prism_magical=False,
        druid_in_pulse_range=False,
    )

    for k, v in out.items():
        print(f"{k}: {v}")
