from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from dnd_sim.inventory import InventoryState

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


@dataclass(slots=True)
class RawField:
    page: int
    field: str
    value: str


@dataclass(slots=True)
class AttackProfile:
    name: str
    to_hit: int
    damage: str
    damage_type: str
    attack_profile_id: str | None = None
    weapon_id: str | None = None
    item_id: str | None = None
    weapon_properties: list[str] = field(default_factory=list)
    reach_ft: int | None = None
    range_ft: int | None = None
    range_normal_ft: int | None = None
    range_long_ft: int | None = None


@dataclass(slots=True)
class CharacterRecord:
    character_id: str
    name: str
    class_level: str
    max_hp: int
    ac: int
    speed_ft: int
    ability_scores: dict[str, int]
    save_mods: dict[str, int]
    skill_mods: dict[str, int]
    attacks: list[AttackProfile]
    resources: dict[str, Any]
    traits: list[str]
    raw_fields: list[RawField]
    source: dict[str, str]
    class_levels: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "class_level": self.class_level,
            "class_levels": self.class_levels,
            "max_hp": self.max_hp,
            "ac": self.ac,
            "speed_ft": self.speed_ft,
            "ability_scores": self.ability_scores,
            "save_mods": self.save_mods,
            "skill_mods": self.skill_mods,
            "attacks": [
                {
                    "attack_profile_id": attack.attack_profile_id,
                    "weapon_id": attack.weapon_id,
                    "item_id": attack.item_id,
                    "name": attack.name,
                    "to_hit": attack.to_hit,
                    "damage": attack.damage,
                    "damage_type": attack.damage_type,
                    "weapon_properties": list(attack.weapon_properties),
                    "reach_ft": attack.reach_ft,
                    "range_ft": attack.range_ft,
                    "range_normal_ft": attack.range_normal_ft,
                    "range_long_ft": attack.range_long_ft,
                }
                for attack in self.attacks
            ],
            "resources": self.resources,
            "traits": self.traits,
            "raw_fields": [
                {"page": raw.page, "field": raw.field, "value": raw.value}
                for raw in self.raw_fields
            ],
            "source": self.source,
        }


@dataclass(slots=True)
class SpellComponents:
    verbal: bool = False
    somatic: bool = False
    material: bool = False
    material_detail: str | None = None
    raw: str = ""


@dataclass(slots=True)
class SpellRoll:
    attack_bonus: int | None = None
    save_dc: int | None = None
    save_ability: str | None = None
    half_on_save: bool = False


@dataclass(slots=True)
class SpellScaling:
    upcast_dice_per_level: str | None = None
    upcast_healing_per_level: str | None = None
    upcast_effects: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class SpellDefinition:
    name: str
    level: int
    school: str | None = None
    casting_time: str = "1 action"
    concentration: bool = False
    duration: str | None = None
    target_mode: str = "single_enemy"
    roll: SpellRoll = field(default_factory=SpellRoll)
    scaling: SpellScaling = field(default_factory=SpellScaling)
    components: SpellComponents = field(default_factory=SpellComponents)


@dataclass(slots=True)
class SpellCastRequest:
    slot_level: int | None = None
    mode: str | None = None
    target_actor_ids: list[str] = field(default_factory=list)
    origin: tuple[float, float, float] | None = None


@dataclass(slots=True)
class ActionDefinition:
    name: str
    action_type: str  # "attack", "spell", "heal", "buff", "dodge", "dash", "disengage", "ready", "grapple", "shove", "none" = None
    to_hit: int | None = None
    damage: str | None = None
    damage_type: str = "bludgeoning"
    attack_count: int = 1
    save_dc: int | None = None
    save_ability: str | None = None
    half_on_save: bool = False
    resource_cost: dict[str, int] = field(default_factory=dict)
    recharge: str | None = None
    max_uses: int | None = None
    action_cost: str = "action"
    event_trigger: str | None = None
    trigger_duration_rounds: int | None = None
    trigger_limit_per_turn: int | None = None
    trigger_once_per_round: bool = False
    target_mode: str = "single_enemy"
    attack_profile_id: str | None = None
    weapon_id: str | None = None
    item_id: str | None = None
    weapon_properties: list[str] = field(default_factory=list)
    reach_ft: int | None = None
    range_ft: int | None = None
    range_normal_ft: int | None = None
    range_long_ft: int | None = None
    aoe_type: str | None = None
    aoe_size_ft: int | None = None
    max_targets: int | None = None
    concentration: bool = False
    include_self: bool = False
    effects: list[dict[str, Any]] = field(default_factory=list)
    mechanics: list[dict[str, Any]] = field(default_factory=list)
    spell: SpellDefinition | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConditionTracker:
    remaining_rounds: int | None = None
    save_dc: int | None = None
    save_ability: str | None = None


@dataclass(slots=True)
class EffectInstance:
    instance_id: str
    effect_id: str
    condition: str
    source_actor_id: str | None = None
    target_actor_id: str | None = None
    duration_remaining: int | None = None
    duration_boundary: str = "turn_start"
    save_dc: int | None = None
    save_ability: str | None = None
    save_to_end: bool = False
    concentration_linked: bool = False
    stack_policy: str = "independent"
    internal_tags: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ActorRuntimeState:
    actor_id: str
    team: str
    name: str
    max_hp: int
    hp: int
    temp_hp: int
    ac: int
    initiative_mod: int
    str_mod: int
    dex_mod: int
    con_mod: int
    int_mod: int
    wis_mod: int
    cha_mod: int
    save_mods: dict[str, int]
    actions: list[ActionDefinition]
    proficiencies: set[str] = field(default_factory=set)
    expertise: set[str] = field(default_factory=set)
    damage_resistances: set[str] = field(default_factory=set)
    damage_immunities: set[str] = field(default_factory=set)
    damage_vulnerabilities: set[str] = field(default_factory=set)
    condition_immunities: set[str] = field(default_factory=set)
    conditions: set[str] = field(default_factory=set)
    intrinsic_conditions: set[str] = field(default_factory=set)
    resources: dict[str, int] = field(default_factory=dict)
    max_resources: dict[str, int] = field(default_factory=dict)
    concentrating: bool = False
    concentration_dc: int = 10
    death_successes: int = 0
    death_failures: int = 0
    stable: bool = False
    dead: bool = False
    downed_count: int = 0
    was_downed: bool = False
    reaction_available: bool = True
    bonus_available: bool = True
    per_action_uses: dict[str, int] = field(default_factory=dict)
    recharge_ready: dict[str, bool] = field(default_factory=dict)
    legendary_actions_remaining: int = 0
    lair_action_used_this_round: bool = False
    traits: dict[str, dict[str, Any]] = field(default_factory=dict)
    inventory: InventoryState = field(default_factory=InventoryState)
    condition_durations: dict[str, ConditionTracker] = field(default_factory=dict)
    effect_instances: list[EffectInstance] = field(default_factory=list)
    effect_instance_seq: int = 0
    next_attack_advantage: bool = False
    next_attack_disadvantage: bool = False
    speed_ft: int = 30
    movement_remaining: float = 0.0
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    took_attack_action_this_turn: bool = False
    bonus_action_spell_restriction_active: bool = False
    non_action_cantrip_spell_cast_this_turn: bool = False
    rage_sustained_since_last_turn: bool = False
    sneak_attack_used_this_turn: bool = False
    sneak_attack_turn_token: str | None = None
    colossus_slayer_used_this_turn: bool = False
    horde_breaker_used_this_turn: bool = False
    gwm_bonus_trigger_available: bool = False
    concentrated_targets: set[str] = field(default_factory=set)
    concentration_conditions: set[str] = field(default_factory=set)
    concentration_effect_instance_ids: set[str] = field(default_factory=set)
    concentrated_spell: str | None = None
    readied_action_name: str | None = None
    readied_trigger: str | None = None
    readied_reaction_reserved: bool = False
    readied_spell_slot_level: int | None = None
    readied_spell_held: bool = False
    concentrated_spell_level: int | None = None
    active_zone_ids: set[str] = field(default_factory=set)
    class_levels: dict[str, int] = field(default_factory=dict)
    level: int = 1
    pending_smite: dict[str, Any] | None = None
    companion_owner_id: str | None = None
    requires_command: bool = False
    commanded_this_round: bool = False

    def is_active(self) -> bool:
        return not self.dead

    def is_conscious(self) -> bool:
        return self.hp > 0 and not self.dead

    def add_manual_condition(self, condition: str) -> None:
        key = str(condition).strip().lower()
        if not key:
            return
        self.intrinsic_conditions.add(key)
        self.conditions.add(key)

    def discard_manual_condition(self, condition: str) -> None:
        key = str(condition).strip().lower()
        if not key:
            return
        self.intrinsic_conditions.discard(key)
        self.conditions.discard(key)

    def update_manual_conditions(self, conditions: set[str]) -> None:
        normalized = {str(value).strip().lower() for value in conditions if str(value).strip()}
        self.intrinsic_conditions.update(normalized)
        self.conditions.update(normalized)


@dataclass(slots=True)
class TrialResult:
    trial_index: int
    rounds: int
    winner: str
    damage_taken: dict[str, int]
    damage_dealt: dict[str, int]
    resources_spent: dict[str, dict[str, int]]
    downed_counts: dict[str, int]
    death_counts: dict[str, int]
    remaining_hp: dict[str, int]
    telemetry: list[dict[str, Any]] = field(default_factory=list)
    encounter_outcomes: list[dict[str, Any]] = field(default_factory=list)
    state_snapshots: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SummaryMetric:
    mean: float
    median: float
    p10: float
    p90: float
    p95: float


@dataclass(slots=True)
class SimulationSummary:
    run_id: str
    scenario_id: str
    trials: int
    party_win_rate: float
    enemy_win_rate: float
    rounds: SummaryMetric
    per_actor_damage_taken: dict[str, SummaryMetric]
    per_actor_damage_dealt: dict[str, SummaryMetric]
    per_actor_resources_spent: dict[str, dict[str, SummaryMetric]]
    per_actor_downed: dict[str, SummaryMetric]
    per_actor_deaths: dict[str, SummaryMetric]
    per_actor_remaining_hp: dict[str, SummaryMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "trials": self.trials,
            "party_win_rate": self.party_win_rate,
            "enemy_win_rate": self.enemy_win_rate,
            "rounds": asdict(self.rounds),
            "per_actor_damage_taken": {
                actor: asdict(metric) for actor, metric in self.per_actor_damage_taken.items()
            },
            "per_actor_damage_dealt": {
                actor: asdict(metric) for actor, metric in self.per_actor_damage_dealt.items()
            },
            "per_actor_resources_spent": {
                actor: {resource: asdict(metric) for resource, metric in resources.items()}
                for actor, resources in self.per_actor_resources_spent.items()
            },
            "per_actor_downed": {
                actor: asdict(metric) for actor, metric in self.per_actor_downed.items()
            },
            "per_actor_deaths": {
                actor: asdict(metric) for actor, metric in self.per_actor_deaths.items()
            },
            "per_actor_remaining_hp": {
                actor: asdict(metric) for actor, metric in self.per_actor_remaining_hp.items()
            },
        }
