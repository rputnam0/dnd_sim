from __future__ import annotations

from typing import Any, Callable


def ensure_resource_cap(actor: Any, resource: str, max_value: int) -> None:
    if max_value <= 0:
        return
    existing_max = int(actor.max_resources.get(resource, 0))
    if existing_max < max_value:
        actor.max_resources[resource] = max_value
    cap = int(actor.max_resources[resource])
    if resource not in actor.resources:
        actor.resources[resource] = cap
    else:
        actor.resources[resource] = max(0, min(int(actor.resources[resource]), cap))


def fighter_superiority_dice_count(fighter_level: int) -> int:
    if fighter_level >= 15:
        return 6
    if fighter_level >= 7:
        return 5
    if fighter_level >= 3:
        return 4
    return 0


def barbarian_rage_uses_for_level(barbarian_level: int) -> int:
    if barbarian_level <= 0:
        return 0
    if barbarian_level >= 20:
        # Unlimited in tabletop rules; use a stable high cap for simulation bookkeeping.
        return 99
    if barbarian_level >= 17:
        return 6
    if barbarian_level >= 12:
        return 5
    if barbarian_level >= 6:
        return 4
    if barbarian_level >= 3:
        return 3
    return 2


def sorcery_points_for_level(sorcerer_level: int) -> int:
    if sorcerer_level < 2:
        return 0
    return min(20, sorcerer_level)


def iter_spell_slot_levels_desc(actor: Any) -> list[int]:
    levels: set[int] = set()
    for key in actor.max_resources.keys():
        if not str(key).startswith("spell_slot_"):
            continue
        try:
            level = int(str(key).rsplit("_", 1)[1])
        except ValueError:
            continue
        if level > 0:
            levels.add(level)
    return sorted(levels, reverse=True)


def recover_spell_slots_with_budget(
    actor: Any,
    *,
    budget: int,
    max_individual_slot_level: int,
) -> int:
    if budget <= 0:
        return 0
    recovered_levels = 0
    for slot_level in iter_spell_slot_levels_desc(actor):
        if slot_level > max_individual_slot_level or budget < slot_level:
            continue
        slot_key = f"spell_slot_{slot_level}"
        max_slots = int(actor.max_resources.get(slot_key, 0))
        current_slots = min(int(actor.resources.get(slot_key, 0)), max_slots)
        missing_slots = max(0, max_slots - current_slots)
        recoverable_slots = min(missing_slots, budget // slot_level)
        if recoverable_slots <= 0:
            continue
        actor.resources[slot_key] = current_slots + recoverable_slots
        recovered_levels += recoverable_slots * slot_level
        budget -= recoverable_slots * slot_level
        if budget <= 0:
            break
    return recovered_levels


def apply_inferred_fighter_resources(
    actor: Any,
    *,
    class_level_text: str,
    has_trait: Callable[[Any, str], bool],
    parse_class_level: Callable[[str, str], int],
    superiority_dice_count: Callable[[int], int] = fighter_superiority_dice_count,
) -> None:
    fighter_level = parse_class_level(class_level_text, "fighter")

    if has_trait(actor, "action surge"):
        action_surge_uses = (
            2 if fighter_level >= 17 or has_trait(actor, "action surge (two uses)") else 1
        )
        ensure_resource_cap(actor, "action_surge", action_surge_uses)

    if has_trait(actor, "second wind"):
        ensure_resource_cap(actor, "second_wind", 1)

    superiority_sources = ("combat superiority", "maneuvers", "battle master", "martial adept")
    if any(has_trait(actor, trait_name) for trait_name in superiority_sources):
        superiority_dice = superiority_dice_count(fighter_level)
        if superiority_dice <= 0 and has_trait(actor, "martial adept"):
            superiority_dice = 1
        if superiority_dice > 0:
            ensure_resource_cap(actor, "superiority_dice", superiority_dice)


def apply_inferred_barbarian_resources(
    actor: Any,
    *,
    class_level_text: str,
    has_trait: Callable[[Any, str], bool],
    parse_class_level: Callable[[str, str], int],
) -> None:
    if not has_trait(actor, "rage"):
        return
    barbarian_level = parse_class_level(class_level_text, "barbarian")
    if barbarian_level <= 0 and not actor.class_levels:
        barbarian_level = int(actor.level)
    rage_uses = barbarian_rage_uses_for_level(barbarian_level)
    if rage_uses <= 0:
        return
    ensure_resource_cap(actor, "rage", rage_uses)


def apply_inferred_bard_resources(
    actor: Any,
    *,
    class_level_text: str,
    has_trait: Callable[[Any, str], bool],
    parse_class_level: Callable[[str, str], int],
) -> None:
    if not has_trait(actor, "bardic inspiration"):
        return
    bard_level = int(actor.class_levels.get("bard", 0))
    if bard_level <= 0 and not actor.class_levels:
        bard_level = parse_class_level(class_level_text, "bard")
    if bard_level <= 0 and not actor.class_levels:
        bard_level = int(actor.level)
    if bard_level <= 0:
        return
    ensure_resource_cap(actor, "bardic_inspiration", max(1, int(actor.cha_mod)))


def apply_inferred_sorcerer_resources(
    actor: Any,
    *,
    class_level_text: str,
    has_trait: Callable[[Any, str], bool],
    parse_class_level: Callable[[str, str], int],
) -> None:
    if not has_trait(actor, "font of magic"):
        return
    sorcerer_level = int(actor.class_levels.get("sorcerer", 0))
    if sorcerer_level <= 0 and not actor.class_levels:
        sorcerer_level = parse_class_level(class_level_text, "sorcerer")
    if sorcerer_level <= 0 and not actor.class_levels:
        sorcerer_level = int(actor.level)
    points = sorcery_points_for_level(sorcerer_level)
    if points <= 0:
        return
    ensure_resource_cap(actor, "sorcery_points", points)


def apply_inferred_druid_resources(
    actor: Any,
    *,
    class_level_text: str,
    has_trait: Callable[[Any, str], bool],
    parse_class_level: Callable[[str, str], int],
    druid_wild_shape_uses_for_level: Callable[[int], int],
) -> None:
    if not has_trait(actor, "wild shape"):
        return
    if has_trait(actor, "archdruid"):
        return
    druid_level = int(actor.class_levels.get("druid", 0))
    if druid_level <= 0 and not actor.class_levels:
        druid_level = parse_class_level(class_level_text, "druid")
    if druid_level <= 0 and not actor.class_levels:
        druid_level = int(actor.level)
    if druid_level <= 0:
        return
    ensure_resource_cap(actor, "wild_shape", druid_wild_shape_uses_for_level(druid_level))


def apply_inferred_wizard_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "arcane recovery"):
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    ensure_resource_cap(actor, "arcane_recovery", 1)


def apply_arcane_recovery(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "arcane recovery"):
        return
    uses_remaining = int(actor.resources.get("arcane_recovery", 0))
    if uses_remaining <= 0:
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0 and not actor.class_levels:
        wizard_level = int(actor.level)
    if wizard_level <= 0:
        return
    recovery_budget = max(1, (wizard_level + 1) // 2)
    recovered_levels = recover_spell_slots_with_budget(
        actor,
        budget=recovery_budget,
        max_individual_slot_level=5,
    )
    if recovered_levels <= 0:
        return
    actor.resources["arcane_recovery"] = uses_remaining - 1
