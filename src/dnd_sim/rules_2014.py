from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from dnd_sim.models import ActionDefinition, ActorRuntimeState

_DAMAGE_RE = re.compile(r"^(?:(\d+)d(\d+))?([+-]\d+)?$")
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")
_SHIELD_MASTER_INCAPACITATING_CONDITIONS = {
    "incapacitated",
    "paralyzed",
    "petrified",
    "stunned",
    "unconscious",
}
_RAGE_BLOCKING_CONDITIONS = {
    "incapacitated",
    "paralyzed",
    "petrified",
    "stunned",
    "unconscious",
}
_RAGE_RESISTANCE_DAMAGE_TYPES = {"bludgeoning", "piercing", "slashing"}
_CANONICAL_DAMAGE_TYPES = (
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "force",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
)
_EventT = TypeVar("_EventT", bound="CombatEvent")


@dataclass(slots=True, kw_only=True)
class CombatEvent:
    sequence: int = 0
    cancelled: bool = False
    cancel_reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        self.cancelled = True
        self.cancel_reason = reason


@dataclass(slots=True)
class ActionDeclaredEvent(CombatEvent):
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    round_number: int | None = None
    turn_token: str | None = None


@dataclass(slots=True)
class AttackRollEvent(CombatEvent):
    rng: random.Random
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    roll: "AttackRollResult"
    target_ac: int
    to_hit_modifier: int
    actors: dict[str, ActorRuntimeState]
    resources_spent: dict[str, dict[str, int]]
    round_number: int | None = None
    turn_token: str | None = None


@dataclass(slots=True)
class ReactionWindowOpenedEvent(CombatEvent):
    window: str
    reactor: ActorRuntimeState
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    round_number: int | None = None
    turn_token: str | None = None


@dataclass(slots=True)
class AttackResolvedEvent(CombatEvent):
    rng: random.Random
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    roll: "AttackRollResult"
    target_ac: int
    actors: dict[str, ActorRuntimeState]
    resources_spent: dict[str, dict[str, int]]
    timing_engine: "CombatTimingEngine | None" = None
    round_number: int | None = None
    turn_token: str | None = None

    @property
    def outcome(self) -> str:
        return "hit" if self.roll.hit else "miss"


@dataclass(slots=True)
class DamageRollEvent(CombatEvent):
    rng: random.Random
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    roll: "AttackRollResult"
    raw_damage: int
    actors: dict[str, ActorRuntimeState]
    resources_spent: dict[str, dict[str, int]]
    target_can_see_attacker: bool
    bundle: "DamageBundle | None" = None
    timing_engine: "CombatTimingEngine | None" = None
    round_number: int | None = None
    turn_token: str | None = None


@dataclass(slots=True)
class DamageResolvedEvent(CombatEvent):
    attacker: ActorRuntimeState
    target: ActorRuntimeState
    action: ActionDefinition
    roll: "AttackRollResult"
    raw_damage: int
    applied_damage: int
    bundle: "DamageBundle | None" = None
    resolution: "DamageBundleResolution | None" = None
    round_number: int | None = None
    turn_token: str | None = None


@dataclass(frozen=True, slots=True)
class ReactionWindowResult:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ListenerSubscription:
    subscription_id: int
    event_type: type[CombatEvent]
    listener_name: str


@dataclass(slots=True)
class _ListenerRegistration:
    subscription_id: int
    event_type: type[CombatEvent]
    listener: Callable[[CombatEvent], None]
    priority: int
    listener_name: str


class CombatTimingEngine:
    def __init__(self) -> None:
        self._next_subscription_id = 1
        self._next_event_sequence = 1
        self._registrations: dict[int, _ListenerRegistration] = {}
        self._listeners_by_event: dict[type[CombatEvent], list[_ListenerRegistration]] = {}

    @staticmethod
    def _resolve_listener_name(
        listener: Callable[[CombatEvent], None],
        override: str | None,
    ) -> str:
        if override:
            return override
        explicit_name = getattr(listener, "name", None)
        if isinstance(explicit_name, str) and explicit_name:
            return explicit_name
        candidate = getattr(listener, "__name__", None)
        if isinstance(candidate, str) and candidate:
            return candidate
        return listener.__class__.__name__

    def subscribe(
        self,
        event_type: type[_EventT],
        listener: Callable[[_EventT], None],
        *,
        priority: int = 0,
        name: str | None = None,
    ) -> ListenerSubscription:
        listener_name = self._resolve_listener_name(listener=listener, override=name)
        registration = _ListenerRegistration(
            subscription_id=self._next_subscription_id,
            event_type=event_type,
            listener=listener,
            priority=int(priority),
            listener_name=listener_name,
        )
        self._next_subscription_id += 1
        self._registrations[registration.subscription_id] = registration
        listeners = self._listeners_by_event.setdefault(event_type, [])
        listeners.append(registration)
        return ListenerSubscription(
            subscription_id=registration.subscription_id,
            event_type=event_type,
            listener_name=registration.listener_name,
        )

    def unsubscribe(self, subscription: ListenerSubscription | int) -> bool:
        subscription_id = (
            subscription.subscription_id
            if isinstance(subscription, ListenerSubscription)
            else int(subscription)
        )
        registration = self._registrations.pop(subscription_id, None)
        if registration is None:
            return False
        listeners = self._listeners_by_event.get(registration.event_type, [])
        self._listeners_by_event[registration.event_type] = [
            item for item in listeners if item.subscription_id != subscription_id
        ]
        return True

    def _iter_ordered_listeners(self, event_type: type[CombatEvent]) -> list[_ListenerRegistration]:
        registrations: dict[int, _ListenerRegistration] = {}
        for base in event_type.mro():
            if not isinstance(base, type):
                continue
            if not issubclass(base, CombatEvent):
                continue
            for registration in self._listeners_by_event.get(base, []):
                registrations[registration.subscription_id] = registration
        ordered = list(registrations.values())
        ordered.sort(
            key=lambda item: (
                -int(item.priority),
                item.listener_name,
                item.subscription_id,
            )
        )
        return ordered

    def emit(self, event: _EventT) -> _EventT:
        event.sequence = self._next_event_sequence
        self._next_event_sequence += 1
        for registration in self._iter_ordered_listeners(type(event)):
            if event.cancelled:
                break
            registration.listener(event)
        return event


@dataclass(slots=True)
class AttackRollResult:
    hit: bool
    crit: bool
    natural_roll: int
    total: int


@dataclass(slots=True)
class DeathSaveResult:
    became_stable: bool
    became_dead: bool
    regained_consciousness: bool


@dataclass(frozen=True, slots=True)
class PowerAttackToggleState:
    active: bool
    to_hit_modifier: int = 0
    damage_bonus: int = 0
    reason: str | None = None


@dataclass(slots=True)
class DamageRollResult:
    rolled: int
    applied: int


@dataclass(slots=True)
class DamagePacket:
    amount: int
    damage_type: str
    source: str
    is_magical: bool = False
    crit_expanded: bool = False


@dataclass(slots=True)
class DamageBundle:
    packets: list[DamagePacket] = field(default_factory=list)

    @property
    def raw_total(self) -> int:
        return sum(max(0, int(packet.amount)) for packet in self.packets)

    def add_packet(self, packet: DamagePacket) -> None:
        if int(packet.amount) <= 0:
            return
        self.packets.append(packet)

    @staticmethod
    def _packet_distribution_key(packet: DamagePacket) -> tuple[str, str, int, int]:
        return (
            str(packet.damage_type).lower(),
            str(packet.source).lower(),
            int(bool(packet.is_magical)),
            int(bool(packet.crit_expanded)),
        )

    def rebalance_total(self, target_total: int) -> None:
        clamped_target = max(0, int(target_total))
        if clamped_target == 0:
            for packet in self.packets:
                packet.amount = 0
            return

        active: list[tuple[int, DamagePacket, int]] = []
        for idx, packet in enumerate(self.packets):
            amount = max(0, int(packet.amount))
            if amount <= 0:
                continue
            active.append((idx, packet, amount))
        if not active:
            return

        current_total = sum(amount for _idx, _packet, amount in active)
        if current_total <= 0:
            return
        if current_total == clamped_target:
            return

        scaled: dict[int, int] = {}
        remainder_ranking: list[tuple[int, tuple[str, str, int, int], int, int]] = []
        base_sum = 0
        for idx, packet, amount in active:
            numerator = amount * clamped_target
            base = numerator // current_total
            remainder = numerator % current_total
            scaled[idx] = base
            base_sum += base
            remainder_ranking.append(
                (remainder, self._packet_distribution_key(packet), amount, idx)
            )

        remaining_points = clamped_target - base_sum
        if remaining_points > 0:
            remainder_ranking.sort(key=lambda item: (-item[0], item[1], -item[2]))
            for _remainder, _key, _amount, idx in remainder_ranking[:remaining_points]:
                scaled[idx] = scaled.get(idx, 0) + 1

        for idx, packet in enumerate(self.packets):
            packet.amount = max(0, scaled.get(idx, 0))

    def apply_flat_reduction(self, reduction: int) -> None:
        target_total = max(0, self.raw_total - max(0, int(reduction)))
        self.rebalance_total(target_total)

    def halve_total(self) -> None:
        self.rebalance_total(self.raw_total // 2)


@dataclass(slots=True)
class ResolvedDamagePacket:
    amount: int
    applied_amount: int
    damage_type: str
    source: str
    is_magical: bool
    crit_expanded: bool


@dataclass(slots=True)
class DamageBundleResolution:
    packets: list[ResolvedDamagePacket]
    raw_total: int
    applied_total: int


def _normalize_trait_name(name: str) -> str:
    return _TRAIT_NORMALIZE_RE.sub(" ", str(name).strip().lower())


def _has_trait(actor: ActorRuntimeState, trait_name: str) -> bool:
    needle = _normalize_trait_name(trait_name)
    return any(_normalize_trait_name(key) == needle for key in actor.traits.keys())


def _has_monk_martial_arts_context(actor: ActorRuntimeState) -> bool:
    monk_level = int(actor.class_levels.get("monk", 0))
    if monk_level > 0:
        return True
    return _has_trait(actor, "martial arts") or _has_trait(actor, "flurry of blows")


def _evaluate_reaction_window_gate(
    *, reactor: ActorRuntimeState, reaction_lock_active: bool
) -> ReactionWindowResult | None:
    if not reactor.reaction_available:
        return ReactionWindowResult(allowed=False, reason="reaction_unavailable")
    if reaction_lock_active:
        return ReactionWindowResult(allowed=False, reason="reaction_lock")
    return None


def evaluate_mage_slayer_reaction_window(
    *,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
    distance_ft: float | None,
    reaction_lock_active: bool = False,
) -> ReactionWindowResult:
    gate = _evaluate_reaction_window_gate(
        reactor=reactor,
        reaction_lock_active=reaction_lock_active,
    )
    if gate is not None:
        return gate
    if trigger_actor is None or trigger_action is None:
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_payload")
    if trigger_actor.team == reactor.team:
        return ReactionWindowResult(allowed=False, reason="non_hostile_trigger")
    if "spell" not in {str(tag).strip().lower() for tag in trigger_action.tags}:
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_action")
    if distance_ft is None or float(distance_ft) > 5.0 + 1e-9:
        return ReactionWindowResult(allowed=False, reason="out_of_range")
    return ReactionWindowResult(allowed=True, reason=None)


def evaluate_sentinel_reaction_window(
    *,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
    distance_ft: float | None,
    reaction_lock_active: bool = False,
) -> ReactionWindowResult:
    gate = _evaluate_reaction_window_gate(
        reactor=reactor,
        reaction_lock_active=reaction_lock_active,
    )
    if gate is not None:
        return gate
    if trigger_actor is None or trigger_target is None or trigger_action is None:
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_payload")
    if trigger_action.action_type != "attack":
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_action")
    if trigger_actor.team == reactor.team:
        return ReactionWindowResult(allowed=False, reason="non_hostile_trigger")
    if trigger_target.actor_id == reactor.actor_id or trigger_target.team != reactor.team:
        return ReactionWindowResult(allowed=False, reason="invalid_target_window")
    if distance_ft is None or float(distance_ft) > 5.0 + 1e-9:
        return ReactionWindowResult(allowed=False, reason="out_of_range")
    return ReactionWindowResult(allowed=True, reason=None)


def evaluate_sentinel_opportunity_window(
    *,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState | None,
    trigger_distance_ft: float | None,
    reach_ft: float,
    mover_disengaged: bool,
    forced_movement: bool,
    reaction_lock_active: bool = False,
) -> ReactionWindowResult:
    gate = _evaluate_reaction_window_gate(
        reactor=reactor,
        reaction_lock_active=reaction_lock_active,
    )
    if gate is not None:
        return gate
    if trigger_actor is None:
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_payload")
    if trigger_actor.team == reactor.team:
        return ReactionWindowResult(allowed=False, reason="non_hostile_trigger")
    if forced_movement:
        return ReactionWindowResult(allowed=False, reason="forced_movement")
    if trigger_distance_ft is None:
        return ReactionWindowResult(allowed=False, reason="out_of_reach")
    if float(trigger_distance_ft) > max(0.0, float(reach_ft)) + 1e-9:
        return ReactionWindowResult(allowed=False, reason="out_of_reach")
    if mover_disengaged:
        # Sentinel explicitly bypasses Disengage for opportunity attack triggers.
        return ReactionWindowResult(allowed=True, reason=None)
    return ReactionWindowResult(allowed=True, reason=None)


def _is_spell_action(action: ActionDefinition) -> bool:
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    if "spell" in normalized_tags:
        return True
    if _normalize_trait_name(action.action_type) == "spell":
        return True
    return action.spell is not None


def _is_one_action_spell(action: ActionDefinition) -> bool:
    if _normalize_trait_name(action.action_cost) != "action":
        return False
    if action.spell is None:
        return True
    raw_casting_time = action.spell.casting_time
    if raw_casting_time is None or not str(raw_casting_time).strip():
        return True
    return _normalize_trait_name(str(raw_casting_time)) in {"1 action", "action"}


def _war_caster_targets_single_trigger(action: ActionDefinition) -> bool:
    target_mode = _normalize_trait_name(action.target_mode)
    if target_mode not in {"single enemy", "single target"}:
        return False
    if action.include_self:
        return False
    if action.max_targets is None:
        return True
    try:
        return int(action.max_targets) == 1
    except (TypeError, ValueError):
        return False


def evaluate_war_caster_opportunity_window(
    *,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState | None,
    trigger_distance_ft: float | None,
    reach_ft: float,
    mover_disengaged: bool,
    forced_movement: bool,
    reaction_spell: ActionDefinition | None,
    reaction_lock_active: bool = False,
) -> ReactionWindowResult:
    gate = _evaluate_reaction_window_gate(
        reactor=reactor,
        reaction_lock_active=reaction_lock_active,
    )
    if gate is not None:
        return gate
    if not _has_trait(reactor, "war caster"):
        return ReactionWindowResult(allowed=False, reason="missing_trait")
    if trigger_actor is None or reaction_spell is None:
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_payload")
    if trigger_actor.team == reactor.team:
        return ReactionWindowResult(allowed=False, reason="non_hostile_trigger")
    if forced_movement:
        return ReactionWindowResult(allowed=False, reason="forced_movement")
    if mover_disengaged:
        return ReactionWindowResult(allowed=False, reason="no_opportunity_trigger")
    if trigger_distance_ft is None:
        return ReactionWindowResult(allowed=False, reason="out_of_reach")
    if float(trigger_distance_ft) > max(0.0, float(reach_ft)) + 1e-9:
        return ReactionWindowResult(allowed=False, reason="out_of_reach")
    if not _is_spell_action(reaction_spell):
        return ReactionWindowResult(allowed=False, reason="invalid_trigger_action")
    if not _is_one_action_spell(reaction_spell):
        return ReactionWindowResult(allowed=False, reason="invalid_casting_time")
    if not _war_caster_targets_single_trigger(reaction_spell):
        return ReactionWindowResult(allowed=False, reason="illegal_spell_target")
    return ReactionWindowResult(allowed=True, reason=None)


def sentinel_speed_reduction_applies_on_hit(*, hit: bool, opportunity_attack: bool) -> bool:
    return bool(hit and opportunity_attack)


def monk_bonus_action_legal(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    if action.action_cost != "bonus":
        return True
    if not _has_monk_martial_arts_context(actor):
        return True

    action_key = str(action.name).strip().lower()
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    is_monk_bonus_action = action_key in {"martial_arts_bonus", "flurry_of_blows"} or bool(
        {"martial_arts", "flurry_of_blows"}.intersection(normalized_tags)
    )
    if not is_monk_bonus_action:
        return True

    return bool(actor.took_attack_action_this_turn)


def ranger_vanish_bonus_action_legal(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    if action.action_cost != "bonus":
        return True

    action_key = str(action.name).strip().lower()
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    is_vanish_action = action_key == "vanish_hide" or "vanish" in normalized_tags
    if not is_vanish_action:
        return True

    return _has_trait(actor, "vanish")


def druid_wild_shape_action_legal(actor: ActorRuntimeState, action: ActionDefinition) -> bool:
    action_key = str(action.name).strip().lower()
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    is_wild_shape_revert = (
        action_key in {"wild_shape_revert", "revert_wild_shape"}
        or "wild_shape_revert" in normalized_tags
    )
    is_wild_shape = (action_key == "wild_shape" or "wild_shape" in normalized_tags) and (
        not is_wild_shape_revert
    )

    if not is_wild_shape and not is_wild_shape_revert:
        return True

    if is_wild_shape_revert:
        return "wild_shaped" in actor.conditions

    if not _has_trait(actor, "wild shape"):
        return False

    if action.action_cost == "reaction":
        return "readied_response" in normalized_tags

    if action.action_cost == "bonus":
        return _has_trait(actor, "combat wild shape")

    return action.action_cost in {"action", "none"}


def _is_same_turn_for_actor(actor: ActorRuntimeState, turn_token: str | None) -> bool:
    if turn_token is None:
        return True
    text = str(turn_token)
    if ":" in text:
        token_actor_id = text.split(":", 1)[1]
        return token_actor_id == actor.actor_id
    return text == actor.actor_id


def _shield_master_active(actor: ActorRuntimeState) -> bool:
    if actor.dead or actor.hp <= 0:
        return False
    if actor.conditions.intersection(_SHIELD_MASTER_INCAPACITATING_CONDITIONS):
        return False
    return True


def _action_weapon_properties(action: ActionDefinition) -> set[str]:
    return {str(prop).strip().lower() for prop in action.weapon_properties if str(prop).strip()}


def _action_is_ranged_weapon_attack(action: ActionDefinition) -> bool:
    properties = _action_weapon_properties(action)
    if properties.intersection({"ammunition", "ranged"}):
        return True
    for range_value in (action.range_long_ft, action.range_normal_ft, action.range_ft):
        if range_value is None:
            continue
        try:
            if int(range_value) > 5:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _normalize_damage_type(value: str) -> str:
    normalized = str(value).strip().lower()
    if not normalized:
        return ""
    for canonical in _CANONICAL_DAMAGE_TYPES:
        if re.search(rf"\b{canonical}\b", normalized):
            return canonical
    return normalized


def _rage_benefits_active(actor: ActorRuntimeState) -> bool:
    if "raging" not in actor.conditions:
        return False
    if actor.dead or actor.hp <= 0:
        return False
    return not bool(actor.conditions.intersection(_RAGE_BLOCKING_CONDITIONS))


def _remove_rage_state(actor: ActorRuntimeState) -> None:
    if "raging" not in actor.conditions:
        return
    _remove_condition_everywhere(actor, "raging")
    actor.rage_sustained_since_last_turn = False


def _sync_rage_state(actor: ActorRuntimeState) -> None:
    if not _rage_benefits_active(actor):
        _remove_rage_state(actor)


def rage_damage_bonus_for_level(level: int) -> int:
    bounded_level = max(1, int(level))
    if bounded_level < 9:
        return 2
    if bounded_level < 16:
        return 3
    return 4


def rage_damage_bonus_for_action(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    using_strength: bool | None = None,
) -> int:
    if not _rage_benefits_active(actor):
        return 0
    if action.action_type != "attack":
        return 0
    if _action_is_ranged_weapon_attack(action):
        return 0
    uses_strength = using_strength
    if uses_strength is None:
        properties = _action_weapon_properties(action)
        uses_strength = not ("finesse" in properties and actor.dex_mod > actor.str_mod)
    if not uses_strength:
        return 0
    return rage_damage_bonus_for_level(actor.level)


def rage_resistance_applies(*, actor: ActorRuntimeState, damage_type: str) -> bool:
    if not _rage_benefits_active(actor):
        return False
    return _normalize_damage_type(damage_type) in _RAGE_RESISTANCE_DAMAGE_TYPES


def rage_activation_legality(actor: ActorRuntimeState) -> tuple[bool, str | None]:
    if not _has_trait(actor, "rage"):
        return False, "missing_trait"
    if "raging" in actor.conditions:
        return False, "already_raging"
    if actor.dead or actor.hp <= 0:
        return False, "unconscious_or_dead"
    if actor.conditions.intersection(_RAGE_BLOCKING_CONDITIONS):
        return False, "incapacitated"
    if int(actor.resources.get("rage", 0)) <= 0:
        return False, "no_uses_remaining"
    return True, None


def activate_rage(actor: ActorRuntimeState) -> tuple[bool, str | None]:
    legal, reason = rage_activation_legality(actor)
    if not legal:
        return False, reason
    actor.resources["rage"] = int(actor.resources.get("rage", 0)) - 1
    actor.update_manual_conditions({"raging"})
    actor.rage_sustained_since_last_turn = bool(actor.took_attack_action_this_turn)
    return True, None


def _toggle_action_legality_reason(action: ActionDefinition) -> str | None:
    if action.action_type != "attack":
        return "non_attack_action"
    if action.to_hit is None:
        return "missing_to_hit"
    return None


def _inactive_power_attack_state(reason: str) -> PowerAttackToggleState:
    return PowerAttackToggleState(
        active=False,
        to_hit_modifier=0,
        damage_bonus=0,
        reason=reason,
    )


def great_weapon_master_toggle_state(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    enabled: bool,
) -> PowerAttackToggleState:
    if not enabled:
        return _inactive_power_attack_state("toggle_disabled")
    if not _has_trait(actor, "great weapon master"):
        return _inactive_power_attack_state("missing_trait")
    legality_reason = _toggle_action_legality_reason(action)
    if legality_reason is not None:
        return _inactive_power_attack_state(legality_reason)
    properties = _action_weapon_properties(action)
    if "heavy" not in properties:
        return _inactive_power_attack_state("weapon_not_heavy")
    if _action_is_ranged_weapon_attack(action):
        return _inactive_power_attack_state("weapon_not_melee")
    return PowerAttackToggleState(active=True, to_hit_modifier=-5, damage_bonus=10, reason=None)


def sharpshooter_toggle_state(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    enabled: bool,
) -> PowerAttackToggleState:
    if not enabled:
        return _inactive_power_attack_state("toggle_disabled")
    if not _has_trait(actor, "sharpshooter"):
        return _inactive_power_attack_state("missing_trait")
    legality_reason = _toggle_action_legality_reason(action)
    if legality_reason is not None:
        return _inactive_power_attack_state(legality_reason)
    if not _action_is_ranged_weapon_attack(action):
        return _inactive_power_attack_state("weapon_not_ranged")
    return PowerAttackToggleState(active=True, to_hit_modifier=-5, damage_bonus=10, reason=None)


def _shield_bonus_from_equipped_items(actor: ActorRuntimeState) -> int:
    bonus = 0
    for item in actor.inventory.items.values():
        if item.equipped_slot is None:
            continue
        if item.equipped_slot != "shield":
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            armor_type = _normalize_trait_name(str(metadata.get("armor_type", "")))
            if armor_type != "shield" and not bool(metadata.get("is_shield")):
                continue
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        raw_bonus = metadata.get("ac_bonus", 2)
        try:
            parsed = int(raw_bonus)
        except (TypeError, ValueError):
            parsed = 2
        bonus = max(bonus, parsed if parsed > 0 else 2)
    return bonus


def shield_master_save_bonus(
    actor: ActorRuntimeState,
    *,
    save_ability: str,
    effect_target_ids: list[str],
) -> int:
    if _normalize_trait_name(save_ability) != "dex":
        return 0
    if not _has_trait(actor, "shield master"):
        return 0
    if not actor.inventory.has_equipped_shield():
        return 0
    if not _shield_master_active(actor):
        return 0

    targeted_ids = {
        str(actor_id).strip() for actor_id in effect_target_ids if str(actor_id).strip()
    }
    if targeted_ids != {actor.actor_id}:
        return 0
    return _shield_bonus_from_equipped_items(actor)


def shield_master_bonus_shove_legality(
    actor: ActorRuntimeState,
    *,
    turn_token: str | None = None,
) -> tuple[bool, str | None]:
    if not _has_trait(actor, "shield master"):
        return False, "missing_trait"
    if not actor.inventory.has_equipped_shield():
        return False, "missing_shield"
    if not _shield_master_active(actor):
        return False, "incapacitated"
    if not _is_same_turn_for_actor(actor, turn_token):
        return False, "off_turn"
    if not actor.bonus_available:
        return False, "bonus_unavailable"
    if not actor.took_attack_action_this_turn:
        return False, "attack_action_not_taken"
    return True, None


def consume_shield_master_bonus_shove(
    actor: ActorRuntimeState,
    *,
    turn_token: str | None = None,
) -> tuple[bool, str | None]:
    legal, reason = shield_master_bonus_shove_legality(actor, turn_token=turn_token)
    if not legal:
        return False, reason
    actor.bonus_available = False
    return True, None


def shield_master_reaction_negation_legality(
    actor: ActorRuntimeState,
    *,
    save_ability: str,
    half_on_save: bool,
    save_succeeded: bool,
) -> tuple[bool, str | None]:
    if _normalize_trait_name(save_ability) != "dex":
        return False, "non_dex_save"
    if not half_on_save:
        return False, "no_half_on_save"
    if not save_succeeded:
        return False, "save_failed"
    if not _has_trait(actor, "shield master"):
        return False, "missing_trait"
    if not actor.inventory.has_equipped_shield():
        return False, "missing_shield"
    if not _shield_master_active(actor):
        return False, "incapacitated"
    if not actor.reaction_available:
        return False, "reaction_unavailable"
    return True, None


def consume_shield_master_reaction_no_damage(
    actor: ActorRuntimeState,
    *,
    save_ability: str,
    half_on_save: bool,
    save_succeeded: bool,
) -> tuple[bool, str | None]:
    legal, reason = shield_master_reaction_negation_legality(
        actor,
        save_ability=save_ability,
        half_on_save=half_on_save,
        save_succeeded=save_succeeded,
    )
    if not legal:
        return False, reason
    actor.reaction_available = False
    return True, None


def _remove_condition_everywhere(target: ActorRuntimeState, condition: str) -> None:
    # Local import avoids module-level circular dependency.
    from dnd_sim.engine import _remove_condition

    _remove_condition(target, condition)


def roll_dice(rng: random.Random, sides: int, count: int = 1) -> int:
    return sum(rng.randint(1, sides) for _ in range(count))


def parse_damage_expression(expr: str) -> tuple[int, int, int]:
    value = expr.strip().replace(" ", "")
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return 0, 0, int(value)

    match = _DAMAGE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid damage expression: {expr}")

    n_dice = int(match.group(1) or 0)
    dice_size = int(match.group(2) or 0)
    flat = int(match.group(3) or 0)
    return n_dice, dice_size, flat


def attack_roll(
    rng: random.Random,
    to_hit: int,
    target_ac: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> AttackRollResult:
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        natural_roll = max(rng.randint(1, 20), rng.randint(1, 20))
    elif disadvantage:
        natural_roll = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        natural_roll = rng.randint(1, 20)

    crit = natural_roll == 20
    total = natural_roll + to_hit
    hit = crit or (natural_roll != 1 and total >= target_ac)
    return AttackRollResult(hit=hit, crit=crit, natural_roll=natural_roll, total=total)


def _spend_luck_point_if_available(
    actor: ActorRuntimeState,
    *,
    resources_spent: dict[str, dict[str, int]],
) -> bool:
    if not _has_trait(actor, "lucky"):
        return False
    current_points = int(actor.resources.get("luck_points", 0))
    if current_points <= 0:
        return False
    actor.resources["luck_points"] = current_points - 1
    actor_spend = resources_spent.setdefault(actor.actor_id, {})
    actor_spend["luck_points"] = actor_spend.get("luck_points", 0) + 1
    return True


def _attack_roll_from_natural(
    *,
    natural_roll: int,
    to_hit_modifier: int,
    target_ac: int,
) -> AttackRollResult:
    crit = natural_roll == 20
    total = natural_roll + to_hit_modifier
    hit = crit or (natural_roll != 1 and total >= target_ac)
    return AttackRollResult(hit=hit, crit=crit, natural_roll=natural_roll, total=total)


def apply_lucky_attacker_reroll(
    *,
    rng: random.Random,
    attacker: ActorRuntimeState,
    roll: AttackRollResult,
    to_hit_modifier: int,
    target_ac: int,
    resources_spent: dict[str, dict[str, int]],
) -> AttackRollResult:
    """Applies Lucky to a failed attack roll made by the actor."""
    if roll.hit:
        return roll
    if not _spend_luck_point_if_available(attacker, resources_spent=resources_spent):
        return roll

    lucky_natural = rng.randint(1, 20)
    chosen_natural = max(int(roll.natural_roll), lucky_natural)
    return _attack_roll_from_natural(
        natural_roll=chosen_natural,
        to_hit_modifier=to_hit_modifier,
        target_ac=target_ac,
    )


def apply_lucky_defender_reroll(
    *,
    rng: random.Random,
    defender: ActorRuntimeState,
    roll: AttackRollResult,
    to_hit_modifier: int,
    target_ac: int,
    resources_spent: dict[str, dict[str, int]],
) -> AttackRollResult:
    """Applies Lucky to an incoming attack roll against the actor."""
    if not roll.hit:
        return roll
    if not _spend_luck_point_if_available(defender, resources_spent=resources_spent):
        return roll

    lucky_natural = rng.randint(1, 20)
    chosen_natural = min(int(roll.natural_roll), lucky_natural)
    return _attack_roll_from_natural(
        natural_roll=chosen_natural,
        to_hit_modifier=to_hit_modifier,
        target_ac=target_ac,
    )


def apply_lucky_save_reroll(
    *,
    rng: random.Random,
    target: ActorRuntimeState,
    save_roll: int,
    save_mod: int,
    dc: int,
    resources_spent: dict[str, dict[str, int]],
) -> int:
    """Applies Lucky to a failed saving throw roll and returns the chosen d20 roll."""
    if int(save_roll) + int(save_mod) >= int(dc):
        return int(save_roll)
    if not _spend_luck_point_if_available(target, resources_spent=resources_spent):
        return int(save_roll)
    lucky_roll = rng.randint(1, 20)
    return max(int(save_roll), lucky_roll)


def run_contested_check(
    rng: random.Random,
    attacker_mod: int,
    defender_mods: list[int],
) -> bool:
    """Evaluates a contested check. Ties go to the defender."""
    attacker_roll = rng.randint(1, 20) + attacker_mod
    defender_mod = max(defender_mods) if defender_mods else 0
    defender_roll = rng.randint(1, 20) + defender_mod
    return attacker_roll > defender_roll


def roll_damage(
    rng: random.Random,
    expr: str,
    *,
    crit: bool = False,
    empowered_rerolls: int = 0,
    source: ActorRuntimeState | None = None,
    damage_type: str = "",
) -> int:
    n_dice, dice_size, flat = parse_damage_expression(expr)
    total = flat
    if n_dice and dice_size:
        rolls = [rng.randint(1, dice_size) for _ in range(n_dice * (2 if crit else 1))]
        if empowered_rerolls > 0:
            rolls.sort()
            for i in range(min(empowered_rerolls, len(rolls))):
                if rolls[i] <= dice_size // 2:
                    rolls[i] = rng.randint(1, dice_size)

        if source and damage_type:
            floor = 1
            for trait_data in source.traits.values():
                for mechanic in trait_data.get("mechanics", []):
                    if mechanic.get("effect_type") == "damage_roll_floor":
                        req_type = mechanic.get("damage_type", "").lower()
                        if req_type == damage_type.lower() or req_type == "any_elemental":
                            floor = max(floor, mechanic.get("floor", 1))
            if floor > 1:
                rolls = [max(r, floor) for r in rolls]

        total += sum(rolls)
    return max(total, 0)


def _damage_expr_has_dice(expr: str) -> bool:
    try:
        n_dice, dice_size, _flat = parse_damage_expression(expr)
    except ValueError:
        return False
    return n_dice > 0 and dice_size > 0


def roll_damage_packet(
    rng: random.Random,
    expr: str,
    *,
    damage_type: str,
    packet_source: str,
    crit: bool = False,
    empowered_rerolls: int = 0,
    source: ActorRuntimeState | None = None,
    is_magical: bool = False,
) -> DamagePacket:
    rolled = roll_damage(
        rng,
        expr,
        crit=crit,
        empowered_rerolls=empowered_rerolls,
        source=source,
        damage_type=damage_type,
    )
    return DamagePacket(
        amount=rolled,
        damage_type=str(damage_type).lower(),
        source=str(packet_source),
        is_magical=bool(is_magical),
        crit_expanded=bool(crit and _damage_expr_has_dice(expr)),
    )


def half_damage(value: int) -> int:
    return value // 2


def concentration_check_dc(damage: int) -> int:
    return max(10, damage // 2)


def apply_damage_type_modifiers(
    damage: int,
    damage_type: str,
    *,
    resistances: set[str],
    immunities: set[str],
    vulnerabilities: set[str],
) -> int:
    dtype = _normalize_damage_type(damage_type)
    normalized_resistances = {_normalize_damage_type(value) for value in resistances}
    normalized_immunities = {_normalize_damage_type(value) for value in immunities}
    normalized_vulnerabilities = {_normalize_damage_type(value) for value in vulnerabilities}
    if dtype in normalized_immunities or "all" in normalized_immunities:
        return 0

    adjusted = damage
    is_resistant = dtype in normalized_resistances or "all" in normalized_resistances
    is_vulnerable = dtype in normalized_vulnerabilities or "all" in normalized_vulnerabilities
    if is_resistant and is_vulnerable:
        pass  # cancel each other per RAW
    elif is_resistant:
        adjusted = half_damage(adjusted)
    elif is_vulnerable:
        adjusted *= 2
    return max(adjusted, 0)


def _resolve_damage_packet(
    packet: DamagePacket,
    *,
    target: ActorRuntimeState,
    source: ActorRuntimeState | None = None,
) -> ResolvedDamagePacket:
    damage_type = _normalize_damage_type(packet.damage_type)
    adjusted = max(0, int(packet.amount))

    for trait_data in target.traits.values():
        for mechanic in trait_data.get("mechanics", []):
            if mechanic.get("effect_type") != "reduce_damage_taken":
                continue
            configured = mechanic.get("damage_types", [])
            if not isinstance(configured, (list, tuple, set)):
                configured = [configured]
            normalized_types = {_normalize_damage_type(value) for value in configured}
            if damage_type not in normalized_types:
                continue
            cond = str(mechanic.get("condition", "")).lower()
            if cond == "nonmagical" and packet.is_magical:
                continue
            amt = int(mechanic.get("amount", 0))
            adjusted = max(0, adjusted - amt)

    effective_resistances = {_normalize_damage_type(value) for value in target.damage_resistances}
    if rage_resistance_applies(actor=target, damage_type=damage_type):
        effective_resistances.update(_RAGE_RESISTANCE_DAMAGE_TYPES)

    if source:
        for trait_data in source.traits.values():
            for mechanic in trait_data.get("mechanics", []):
                if mechanic.get("effect_type") != "ignore_resistance":
                    continue
                bypass_type = _normalize_damage_type(str(mechanic.get("damage_type", "")))
                if bypass_type in {damage_type, "any_elemental"}:
                    effective_resistances.discard(damage_type)

    adjusted = apply_damage_type_modifiers(
        adjusted,
        damage_type,
        resistances=effective_resistances,
        immunities={_normalize_damage_type(value) for value in target.damage_immunities},
        vulnerabilities={_normalize_damage_type(value) for value in target.damage_vulnerabilities},
    )
    return ResolvedDamagePacket(
        amount=max(0, int(packet.amount)),
        applied_amount=adjusted,
        damage_type=damage_type,
        source=str(packet.source),
        is_magical=bool(packet.is_magical),
        crit_expanded=bool(packet.crit_expanded),
    )


def resolve_damage_bundle(
    target: ActorRuntimeState,
    bundle: DamageBundle,
    *,
    source: ActorRuntimeState | None = None,
) -> DamageBundleResolution:
    resolved_packets = [
        _resolve_damage_packet(packet, target=target, source=source)
        for packet in bundle.packets
        if int(packet.amount) > 0
    ]
    return DamageBundleResolution(
        packets=resolved_packets,
        raw_total=sum(packet.amount for packet in resolved_packets),
        applied_total=sum(packet.applied_amount for packet in resolved_packets),
    )


def apply_damage_bundle(
    target: ActorRuntimeState,
    bundle: DamageBundle,
    *,
    is_critical: bool = False,
    source: ActorRuntimeState | None = None,
) -> DamageBundleResolution:
    _sync_rage_state(target)
    resolution = resolve_damage_bundle(target, bundle, source=source)
    adjusted = resolution.applied_total
    if adjusted > 0 and _rage_benefits_active(target):
        target.rage_sustained_since_last_turn = True

    def _end_rage_if_active() -> None:
        _remove_rage_state(target)

    remaining = adjusted
    if target.temp_hp > 0 and remaining > 0:
        consumed = min(target.temp_hp, remaining)
        target.temp_hp -= consumed
        remaining -= consumed

    if bool(getattr(target, "wild_shape_active", False)) and remaining > 0:
        current_form_hp = max(0, int(target.hp))
        if remaining < current_form_hp:
            target.hp = current_form_hp - remaining
            return resolution

        overflow = max(0, remaining - current_form_hp)
        target.hp = 0
        _remove_condition_everywhere(target, "wild_shaped")

        if overflow > 0:
            overflow_damage_type = (
                resolution.packets[0].damage_type if resolution.packets else "bludgeoning"
            )
            apply_damage(
                target,
                overflow,
                overflow_damage_type,
                is_critical=is_critical,
                source=source,
            )
        return resolution

    def _mark_dead() -> None:
        target.dead = True
        target.stable = False
        target.death_failures = max(3, target.death_failures)
        target.update_manual_conditions({"dead", "unconscious", "incapacitated"})
        _end_rage_if_active()

    if target.hp <= 0 and not target.dead:
        if remaining >= target.max_hp:
            _mark_dead()
            return resolution
        if remaining > 0:
            if target.stable:
                target.stable = False
                target.death_successes = 0
            # Failed death save from taking damage while at 0.
            target.death_failures += 2 if is_critical else 1
            if target.death_failures >= 3:
                _mark_dead()
        return resolution

    hp_before = target.hp
    if remaining > 0:
        target.hp -= remaining

    if target.hp <= 0 and not target.dead:
        overflow = max(0, remaining - max(0, hp_before))
        target.hp = 0
        downed_conditions = {"unconscious", "incapacitated"}
        if "prone" not in target.condition_immunities and "all" not in target.condition_immunities:
            downed_conditions.add("prone")
        target.update_manual_conditions(downed_conditions)
        _end_rage_if_active()
        if not target.was_downed:
            target.downed_count += 1
            target.was_downed = True
        if overflow >= target.max_hp:
            _mark_dead()

    if adjusted > 0 and "turned" in target.conditions:
        for condition in ("turned", "frightened"):
            _remove_condition_everywhere(target, condition)
        if target.hp > 0:
            _remove_condition_everywhere(target, "incapacitated")
    return resolution


def apply_damage(
    target: ActorRuntimeState,
    amount: int,
    damage_type: str,
    *,
    is_critical: bool = False,
    is_magical: bool = False,
    source: ActorRuntimeState | None = None,
) -> int:
    packet = DamagePacket(
        amount=max(0, int(amount)),
        damage_type=str(damage_type).lower(),
        source="direct",
        is_magical=is_magical,
        crit_expanded=False,
    )
    bundle = DamageBundle(packets=[packet])
    resolution = apply_damage_bundle(
        target,
        bundle,
        is_critical=is_critical,
        source=source,
    )
    return resolution.applied_total


def run_concentration_check(
    rng: random.Random,
    target: ActorRuntimeState,
    damage_taken: int,
    source: ActorRuntimeState | None = None,
) -> bool:
    if not target.concentrating:
        return True
    if "raging" in target.conditions:
        return False

    dc = concentration_check_dc(damage_taken)
    advantage = _has_trait(target, "war caster")
    disadvantage = bool(source and _has_trait(source, "mage slayer"))

    if advantage and not disadvantage:
        roll = max(rng.randint(1, 20), rng.randint(1, 20))
    elif disadvantage and not advantage:
        roll = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        roll = rng.randint(1, 20)

    save_mod = target.save_mods.get("con", target.con_mod)
    success = (roll + save_mod) >= dc
    if (
        not success
        and _has_trait(target, "mind sharpener")
        and target.resources.get("mind_sharpener_charges", 0) > 0
    ):
        target.resources["mind_sharpener_charges"] -= 1
        success = True
    if not success:
        target.concentrating = False
    return success


def resolve_death_save(rng: random.Random, target: ActorRuntimeState) -> DeathSaveResult:
    if target.hp > 0 or target.stable or target.dead:
        return DeathSaveResult(False, target.dead, False)

    roll = rng.randint(1, 20)
    if roll == 1:
        target.death_failures += 2
    elif roll == 20:
        target.hp = 1
        target.death_successes = 0
        target.death_failures = 0
        target.stable = False
        _remove_condition_everywhere(target, "unconscious")
        _remove_condition_everywhere(target, "incapacitated")
        return DeathSaveResult(False, False, True)
    elif roll >= 10:
        target.death_successes += 1
    else:
        target.death_failures += 1

    became_stable = False
    became_dead = False
    if target.death_successes >= 3:
        target.stable = True
        became_stable = True
    if target.death_failures >= 3:
        target.dead = True
        target.update_manual_conditions({"dead", "unconscious", "incapacitated"})
        became_dead = True

    return DeathSaveResult(became_stable, became_dead, False)
