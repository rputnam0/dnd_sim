from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from dnd_sim import engine_runtime as engine_module
from dnd_sim.engine_runtime import (
    _build_actor_from_enemy,
    _execute_action,
    _roll_recharge_for_actor,
    _spell_pipeline_adapters,
)
from dnd_sim.io_models import EnemyConfig
from dnd_sim.models import ActionDefinition, ActorRuntimeState, SpellComponents, SpellDefinition
from dnd_sim.reaction_runtime import ReactionDecisionValidationError
from dnd_sim.rules_2014 import ActionDeclaredEvent, CombatTimingEngine
from dnd_sim.spatial import AABB
from dnd_sim.spell_reaction_runtime import (
    build_counterspell_candidates_for_action,
    spell_action_identity,
)
from dnd_sim.spell_runtime import (
    CounterspellChainState,
    run_spell_declaration_pipeline_outcome,
)
from dnd_sim.strategy_api import ReactionDecision, ReactionWindowView


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        if not self.values:
            raise AssertionError("unexpected RNG consumption")
        value = self.values.pop(0)
        assert low <= value <= high
        return value


def _actor(
    actor_id: str,
    *,
    team: str,
    position: tuple[float, float, float],
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
        position=position,
    )


def _counterspell(
    *,
    name: str = "Counterspell",
    range_ft: int | None = None,
    tags: list[str] | None = None,
    resource_cost: dict[str, int] | None = None,
    max_uses: int | None = None,
    recharge: str | None = None,
    spell_level: int | None = None,
    spellcasting_ability: str | None = "cha",
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="utility",
        action_cost="reaction",
        target_mode="single_creature",
        range_ft=range_ft,
        resource_cost=dict(resource_cost or {}),
        max_uses=max_uses,
        recharge=recharge,
        spellcasting_ability=spellcasting_ability,
        spell=(
            SpellDefinition(name="Counterspell", level=spell_level)
            if spell_level is not None
            else None
        ),
        tags=list(tags or ["spell", "counterspell"]),
    )


def _incoming_spell(*, level: int = 5, tags: list[str] | None = None) -> ActionDefinition:
    return ActionDefinition(
        name="Arcane Seal",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        resource_cost={f"spell_slot_{level}": 1},
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "arcane_sealed",
                "target": "target",
            }
        ],
        tags=list(tags or ["spell", "component:verbal", "component:somatic"]),
    )


def _cast(
    *,
    caster: ActorRuntimeState,
    recipient: ActorRuntimeState,
    reactors: list[ActorRuntimeState],
    action: ActionDefinition | None = None,
    provider: Callable[[ReactionWindowView], ReactionDecision] | None = None,
    rng: _SequenceRng | None = None,
    telemetry: list[dict] | None = None,
    obstacles: list[AABB] | None = None,
    active_hazards: list[dict[str, object]] | None = None,
    timing_engine: CombatTimingEngine | None = None,
) -> tuple[dict[str, dict[str, int]], list[dict]]:
    actors = {actor.actor_id: actor for actor in (caster, recipient, *reactors)}
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    telemetry_rows = telemetry if telemetry is not None else []
    active_rng = rng if rng is not None else _SequenceRng([])

    _execute_action(
        rng=active_rng,
        actor=caster,
        action=action or _incoming_spell(),
        targets=[recipient],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards or [],
        obstacles=obstacles,
        round_number=4,
        turn_token=f"4:{caster.actor_id}",
        telemetry=telemetry_rows,
        reaction_decision_provider=provider,
        timing_engine=timing_engine,
    )
    assert active_rng.values == []
    return resources_spent, telemetry_rows


def _fixture(*, reactor_id: str = "reactor", reactor_team: str = "enemy") -> tuple[
    ActorRuntimeState,
    ActorRuntimeState,
    ActorRuntimeState,
]:
    caster = _actor("caster", team="party", position=(0.0, 0.0, 0.0))
    recipient = _actor("recipient", team="party", position=(0.0, 10.0, 0.0))
    reactor = _actor(reactor_id, team=reactor_team, position=(30.0, 0.0, 0.0))
    reactor.actions = [_counterspell()]
    reactor.resources = {"spell_slot_3": 1}
    return caster, recipient, reactor


def _nested_counterspell_fixture(
    counter_count: int,
) -> tuple[ActorRuntimeState, ActorRuntimeState, list[ActorRuntimeState]]:
    if counter_count not in {1, 2, 3}:
        raise ValueError("counter_count must be 1, 2, or 3")
    caster = _actor("caster", team="party", position=(0.0, 0.0, 0.0))
    recipient = _actor("recipient", team="party", position=(0.0, 10.0, 0.0))
    first = _actor("b_first", team="enemy", position=(30.0, 0.0, 0.0))
    first.actions = [_counterspell()]
    first.resources = {"spell_slot_3": 1}
    reactors = [first]
    if counter_count >= 2:
        caster.actions = [_counterspell()]
        caster.resources = {"spell_slot_3": 1}
    if counter_count >= 3:
        third = _actor("z_third", team="enemy", position=(35.0, 0.0, 0.0))
        third.actions = [_counterspell()]
        third.resources = {"spell_slot_3": 1}
        reactors.append(third)
    return caster, recipient, reactors


def _use_first_reaction_option(window: ReactionWindowView) -> ReactionDecision:
    option = window.options[0]
    slot_level = option.legal_spell_slot_levels[0] if option.legal_spell_slot_levels else None
    return ReactionDecision(
        window_id=window.window_id,
        choice="use",
        option_id=option.option_id,
        spell_slot_level=slot_level,
    )


def test_counterspell_provider_can_pass_without_mutating_reactor() -> None:
    caster, recipient, reactor = _fixture()
    windows: list[ReactionWindowView] = []
    telemetry: list[dict] = []

    def pass_counterspell(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=pass_counterspell,
        telemetry=telemetry,
    )

    assert "arcane_sealed" in recipient.conditions
    assert len(windows) == 1
    assert windows[0].trigger.kind == "counterspell"
    assert windows[0].trigger.source_actor_id == caster.actor_id
    assert windows[0].trigger.action_name == "Arcane Seal"
    assert windows[0].trigger.spell_level == 5
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True
    assert reactor.per_action_uses == {}
    assert resources_spent[reactor.actor_id] == {}
    assert [
        row["telemetry_type"]
        for row in telemetry
        if str(row["telemetry_type"]).startswith("reaction_")
    ] == [
        "reaction_window_opened",
        "reaction_decision",
        "reaction_window_closed",
    ]
    closed = next(row for row in telemetry if row.get("telemetry_type") == "reaction_window_closed")
    assert closed["status"] == "passed"


def test_counterspell_use_binds_explicit_pact_slot_payment() -> None:
    caster, recipient, reactor = _fixture()
    reactor.resources = {"spell_slot_5": 1, "warlock_spell_slot_5": 1}
    reactor.actions[0].recharge = "5-6"
    reactor.recharge_ready["Counterspell"] = True
    telemetry: list[dict] = []

    def use_pact_slot(window: ReactionWindowView) -> ReactionDecision:
        option = next(
            candidate
            for candidate in window.options
            if candidate.resource_cost == (("warlock_spell_slot_5", 1),)
        )
        assert option.fixed_target_ids == (caster.actor_id,)
        assert option.legal_spell_slot_levels == (5,)
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=5,
        )

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=use_pact_slot,
        telemetry=telemetry,
    )

    assert "arcane_sealed" not in recipient.conditions
    assert reactor.resources == {"spell_slot_5": 1, "warlock_spell_slot_5": 0}
    assert reactor.reaction_available is False
    assert reactor.per_action_uses == {"Counterspell": 1}
    assert reactor.recharge_ready == {"Counterspell": False}
    assert resources_spent[reactor.actor_id] == {"warlock_spell_slot_5": 1}
    assert telemetry[1]["choice"] == "use"
    assert telemetry[1]["spell_slot_level"] == 5
    assert telemetry[1]["resource_spend"] == {}
    closed = next(row for row in telemetry if row.get("telemetry_type") == "reaction_window_closed")
    assert closed["status"] == "resolved"
    assert closed["reason"] == "countered"


@pytest.mark.parametrize("invalid_kind", ["choice", "stale", "unknown_option", "slot"])
def test_invalid_counterspell_decision_is_atomic(invalid_kind: str) -> None:
    caster, recipient, reactor = _fixture()
    reactor.resources["spell_slot_5"] = 1
    reactor.actions[0].max_uses = 2
    reactor.actions[0].recharge = "5-6"
    reactor.recharge_ready[reactor.actions[0].name] = True
    telemetry: list[dict] = []

    def invalid_decision(window: ReactionWindowView) -> ReactionDecision:
        option = window.options[0]
        if invalid_kind == "choice":
            return ReactionDecision(window_id=window.window_id, choice="wait")  # type: ignore[arg-type]
        if invalid_kind == "stale":
            return ReactionDecision(
                window_id=f"{window.window_id}:stale",
                choice="use",
                option_id=option.option_id,
                spell_slot_level=3,
            )
        if invalid_kind == "unknown_option":
            return ReactionDecision(
                window_id=window.window_id,
                choice="use",
                option_id=f"{option.option_id}:unknown",
                spell_slot_level=3,
            )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=5,
        )

    with pytest.raises(ReactionDecisionValidationError):
        _cast(
            caster=caster,
            recipient=recipient,
            reactors=[reactor],
            action=_incoming_spell(level=3),
            provider=invalid_decision,
            telemetry=telemetry,
        )

    assert reactor.resources == {"spell_slot_3": 1, "spell_slot_5": 1}
    assert reactor.reaction_available is True
    assert reactor.per_action_uses == {}
    assert reactor.recharge_ready == {"Counterspell": True}
    assert telemetry[-1]["telemetry_type"] == "reaction_window_closed"
    assert telemetry[-1]["status"] == "rejected"


def test_counterspell_revalidates_live_payment_before_mutation() -> None:
    caster, recipient, reactor = _fixture()

    def spend_slot_during_decision(window: ReactionWindowView) -> ReactionDecision:
        option = window.options[0]
        reactor.resources["spell_slot_3"] = 0
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=3,
        )

    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=spend_slot_during_decision,
    )

    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources["spell_slot_3"] == 0
    assert reactor.reaction_available is True
    assert reactor.per_action_uses == {}
    assert resources_spent[reactor.actor_id] == {}
    assert any(
        row.get("telemetry_type") == "reaction_window_closed"
        and row.get("status") == "unavailable"
        and row.get("reason") == "state_changed"
        for row in telemetry
    )


@pytest.mark.parametrize("first_result", ["pass", "failed_counter"])
def test_later_counterspeller_can_act_after_pass_or_failed_counter(first_result: str) -> None:
    caster, recipient, first = _fixture(reactor_id="a_first")
    second = _actor("b_second", team="enemy", position=(35.0, 0.0, 0.0))
    second.actions = [_counterspell()]
    second.resources = {"spell_slot_5": 1}
    first.cha_mod = -5
    windows: list[ReactionWindowView] = []

    def decide(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        if window.chain_depth > 1:
            return ReactionDecision(window_id=window.window_id, choice="pass")
        if window.reactor_id == first.actor_id and first_result == "pass":
            return ReactionDecision(window_id=window.window_id, choice="pass")
        option = window.options[0]
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=option.legal_spell_slot_levels[0],
        )

    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[first, second],
        provider=decide,
        rng=_SequenceRng([1] if first_result == "failed_counter" else []),
    )

    assert [window.reactor_id for window in windows if window.chain_depth == 1] == [
        "a_first",
        "b_second",
    ]
    assert [window.reactor_id for window in windows if window.chain_depth == 2] == [
        "a_first" if first_result == "pass" else "b_second"
    ]
    assert "arcane_sealed" not in recipient.conditions
    assert second.resources["spell_slot_5"] == 0
    assert resources_spent[second.actor_id] == {"spell_slot_5": 1}
    if first_result == "pass":
        assert first.resources["spell_slot_3"] == 1
        assert first.reaction_available is True
    else:
        assert first.resources["spell_slot_3"] == 0
        assert first.reaction_available is False
        assert any(
            row.get("reason") == "counter_failed" and row.get("reactor_id") == first.actor_id
            for row in telemetry
        )


def test_counterspell_window_ids_are_deterministic_unique_and_payment_bound() -> None:
    def capture_sequence() -> list[ReactionWindowView]:
        caster, recipient, reactor = _fixture()
        reactor.resources = {"spell_slot_5": 1, "warlock_spell_slot_5": 1}
        windows: list[ReactionWindowView] = []

        def capture(window: ReactionWindowView) -> ReactionDecision:
            windows.append(window)
            return ReactionDecision(window_id=window.window_id, choice="pass")

        for _ in range(2):
            _cast(caster=caster, recipient=recipient, reactors=[reactor], provider=capture)
        assert len(windows) == 2
        return windows

    first_sequence = capture_sequence()
    repeated_sequence = capture_sequence()
    first = first_sequence[0]

    assert [window.window_id for window in first_sequence] == [
        window.window_id for window in repeated_sequence
    ]
    assert first_sequence[0].window_id != first_sequence[1].window_id
    assert first.window_id.startswith("rw1_")
    assert [option.option_id for option in first.options] == [
        option.option_id for option in repeated_sequence[0].options
    ]
    assert {option.option_id for option in first_sequence[0].options}.isdisjoint(
        option.option_id for option in first_sequence[1].options
    )
    assert len({option.option_id for option in first.options}) == 2
    assert {option.resource_cost for option in first.options} == {
        (("spell_slot_5", 1),),
        (("warlock_spell_slot_5", 1),),
    }
    assert all(option.option_id.startswith("ro1_") for option in first.options)


def test_default_counterspell_uses_legacy_optimal_slot_choice() -> None:
    caster, recipient, reactor = _fixture()
    reactor.resources = {"spell_slot_3": 1, "spell_slot_5": 1}

    resources_spent, _ = _cast(caster=caster, recipient=recipient, reactors=[reactor])

    assert "arcane_sealed" not in recipient.conditions
    assert reactor.resources == {"spell_slot_3": 1, "spell_slot_5": 0}
    assert resources_spent[reactor.actor_id] == {"spell_slot_5": 1}


def test_same_team_counterspeller_gets_window_but_default_passes() -> None:
    caster, recipient, reactor = _fixture(reactor_team="party")
    windows: list[ReactionWindowView] = []

    def pass_and_capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(caster=caster, recipient=recipient, reactors=[reactor], provider=pass_and_capture)

    assert [window.reactor_id for window in windows] == [reactor.actor_id]
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True

    caster, recipient, reactor = _fixture(reactor_team="party")
    _cast(caster=caster, recipient=recipient, reactors=[reactor])
    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True


@pytest.mark.parametrize(
    ("incoming_tags", "expected_windows"),
    [
        (["spell", "metamagic:subtle", "component:verbal", "component:somatic"], 0),
        (["spell", "metamagic:subtle"], 0),
        (["spell"], 1),
        (
            [
                "spell",
                "metamagic:subtle",
                "component:verbal",
                "component:somatic",
                "component:material",
            ],
            1,
        ),
    ],
)
def test_subtle_spell_observability_depends_on_material_component(
    incoming_tags: list[str], expected_windows: int
) -> None:
    caster, recipient, reactor = _fixture()
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3, tags=incoming_tags),
        provider=capture,
    )

    assert len(windows) == expected_windows


@pytest.mark.parametrize(
    "blocked_by", ["range", "fallback_range", "cover", "components", "blinded"]
)
def test_counterspell_window_requires_range_cover_visibility_and_components(
    blocked_by: str,
) -> None:
    caster, recipient, reactor = _fixture()
    obstacles: list[AABB] = []
    if blocked_by == "range":
        reactor.position = (40.0, 0.0, 0.0)
        reactor.actions = [_counterspell(range_ft=30)]
    elif blocked_by == "fallback_range":
        reactor.position = (65.0, 0.0, 0.0)
    elif blocked_by == "cover":
        obstacles = [
            AABB(
                min_pos=(14.0, -1.0, -1.0),
                max_pos=(16.0, 1.0, 1.0),
                cover_level="TOTAL",
            )
        ]
    elif blocked_by == "components":
        counterspell = _counterspell(spell_level=3)
        assert counterspell.spell is not None
        counterspell.spell.components = SpellComponents(somatic=True, raw="S")
        reactor.actions = [counterspell]
        reactor.resources["free_hands"] = 0
    else:
        reactor.conditions.add("blinded")
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture,
        obstacles=obstacles,
    )

    assert windows == []
    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True


@pytest.mark.parametrize(
    ("conditions", "free_hands", "has_war_caster", "explicit_tags", "expected_windows"),
    [
        ({"silenced"}, 1, False, None, 1),
        (set(), 0, False, None, 0),
        (set(), 0, True, None, 1),
        ({"silenced"}, 1, True, ["spell", "counterspell", "component:verbal"], 0),
    ],
    ids=[
        "somatic-only-works-while-silenced",
        "somatic-only-needs-free-hand",
        "war-caster-restores-somatic-casting",
        "war-caster-does-not-bypass-verbal-silence",
    ],
)
def test_counterspell_component_legality_uses_spell_metadata_when_tags_are_absent(
    conditions: set[str],
    free_hands: int,
    has_war_caster: bool,
    explicit_tags: list[str] | None,
    expected_windows: int,
) -> None:
    caster, recipient, reactor = _fixture()
    counterspell = _counterspell(
        spell_level=3,
        tags=explicit_tags or ["spell", "counterspell"],
    )
    assert counterspell.spell is not None
    counterspell.spell.components = SpellComponents(somatic=True, raw="S")
    reactor.actions = [counterspell]
    reactor.conditions.update(conditions)
    reactor.resources["free_hands"] = free_hands
    if has_war_caster:
        reactor.traits["war caster"] = {}
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(caster=caster, recipient=recipient, reactors=[reactor], provider=capture)

    assert len(windows) == expected_windows


def test_persistent_wall_zone_blocks_counterspell_line_of_effect() -> None:
    caster, recipient, reactor = _fixture()
    windows: list[ReactionWindowView] = []
    wall_zone = {
        "type": "wall",
        "zone_instance_id": "wall:counterspell",
        "min_pos": (14.0, -5.0, -5.0),
        "max_pos": (16.0, 5.0, 5.0),
        "blocks_line_of_effect": True,
    }

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=capture,
        active_hazards=[wall_zone],
    )

    assert windows == []
    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True


def test_counterspell_without_declared_range_uses_sixty_foot_fallback() -> None:
    caster, recipient, reactor = _fixture()
    reactor.position = (55.0, 0.0, 0.0)
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(caster=caster, recipient=recipient, reactors=[reactor], provider=capture)

    assert len(windows) == 1


def test_counterspell_option_and_commit_preserve_full_exact_cost_and_slot_amount() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            resource_cost={"spell_slot_3": 2, "arcane_focus_charge": 1},
            spell_level=3,
        )
    ]
    reactor.resources = {
        "spell_slot_3": 1,
        "spell_slot_4": 2,
        "arcane_focus_charge": 1,
    }

    def choose_exact_payment(window: ReactionWindowView) -> ReactionDecision:
        assert len(window.options) == 1
        option = window.options[0]
        assert option.resource_cost == (
            ("arcane_focus_charge", 1),
            ("spell_slot_4", 2),
        )
        assert option.effective_spell_level == 4
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=4,
        )

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=4),
        provider=choose_exact_payment,
    )

    assert "arcane_sealed" not in recipient.conditions
    assert reactor.resources == {
        "spell_slot_3": 1,
        "spell_slot_4": 0,
        "arcane_focus_charge": 0,
    }
    assert resources_spent[reactor.actor_id] == {
        "arcane_focus_charge": 1,
        "spell_slot_4": 2,
    }


def test_counterspell_declared_level_three_pact_action_can_use_standard_level_three_slot() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            resource_cost={"warlock_spell_slot_5": 1},
            spell_level=3,
        )
    ]
    reactor.resources = {"spell_slot_3": 1, "warlock_spell_slot_5": 1}
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        standard = next(
            option for option in window.options if option.resource_cost == (("spell_slot_3", 1),)
        )
        assert standard.effective_spell_level == 3
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=standard.option_id,
            spell_slot_level=3,
        )

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture,
    )

    assert len(windows) == 1
    assert {option.resource_cost for option in windows[0].options} == {
        (("spell_slot_3", 1),),
        (("warlock_spell_slot_5", 1),),
    }
    assert reactor.resources == {"spell_slot_3": 0, "warlock_spell_slot_5": 1}
    assert resources_spent[reactor.actor_id] == {"spell_slot_3": 1}


@pytest.mark.parametrize(
    ("action", "resources", "expected_cost", "expected_level"),
    [
        (
            _counterspell(resource_cost={"spell_slot_4": 1}, spell_level=3),
            {"spell_slot_3": 1, "spell_slot_4": 1},
            (("spell_slot_4", 1),),
            4,
        ),
        (
            _counterspell(
                resource_cost={"spell_slot_3": 1},
                spell_level=3,
                tags=["spell", "counterspell", "upcast_level:5"],
            ),
            {"spell_slot_3": 1, "spell_slot_5": 1},
            (("spell_slot_5", 1),),
            5,
        ),
        (
            _counterspell(resource_cost={"warlock_spell_slot_5": 1}),
            {"spell_slot_3": 1, "warlock_spell_slot_5": 1},
            (("warlock_spell_slot_5", 1),),
            5,
        ),
    ],
)
def test_counterspell_candidate_honors_declared_and_upcast_minimum_levels(
    action: ActionDefinition,
    resources: dict[str, int],
    expected_cost: tuple[tuple[str, int], ...],
    expected_level: int,
) -> None:
    reactor = _actor("reactor", team="enemy", position=(0.0, 0.0, 0.0))
    reactor.resources = resources

    candidates = build_counterspell_candidates_for_action(
        reactor=reactor,
        action=action,
        action_index=0,
    )

    assert [candidate.resource_cost for candidate in candidates] == [expected_cost]
    assert candidates[0].effective_spell_level == expected_level


def test_innate_counterspell_is_slotless_tracks_uses_and_defaults_without_crashing() -> None:
    caster, recipient, _ = _fixture()
    reactor = _build_actor_from_enemy(
        EnemyConfig.model_validate(
            {
                "identity": {
                    "enemy_id": "innate_mage",
                    "name": "Innate Mage",
                    "team": "enemy",
                },
                "stat_block": {"max_hp": 30, "ac": 12},
                "actions": [],
                "innate_spellcasting": [
                    {
                        "spell": "Counterspell",
                        "max_uses": 1,
                        "spellcasting_ability": "wis",
                    }
                ],
            }
        )
    )
    reactor.position = (30.0, 0.0, 0.0)
    windows: list[ReactionWindowView] = []

    def capture_and_default(window: ReactionWindowView) -> ReactionDecision:
        from dnd_sim.reaction_runtime import default_reaction_decision

        windows.append(window)
        return default_reaction_decision(window)

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_and_default,
    )

    assert len(windows) == 1
    assert len(windows[0].options) == 1
    option = windows[0].options[0]
    assert option.resource_cost == ()
    assert option.legal_spell_slot_levels == ()
    assert option.effective_spell_level == 3
    assert reactor.actions[0].spellcasting_ability == "wis"
    assert resources_spent[reactor.actor_id] == {}
    assert reactor.resources == {}
    assert reactor.per_action_uses == {"Counterspell": 1}
    assert reactor.reaction_available is False
    assert "arcane_sealed" not in recipient.conditions

    reactor.reaction_available = True
    followup_windows: list[ReactionWindowView] = []

    def capture_followup(window: ReactionWindowView) -> ReactionDecision:
        followup_windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_followup,
    )
    assert followup_windows == []
    assert "arcane_sealed" in recipient.conditions


def test_counterspell_window_skips_unavailable_variant_and_keeps_later_legal_action() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            name="Counterspell (Spent Focus)",
            tags=["spell", "spell_id:counterspell", "spell_level:3"],
            resource_cost={"spell_slot_3": 1, "spent_focus": 1},
        ),
        _counterspell(
            name="Counterspell (Prepared)",
            tags=["spell", "spell_id:counterspell", "spell_level:3"],
            resource_cost={"spell_slot_3": 1},
        ),
    ]
    reactor.resources = {"spell_slot_3": 1, "spent_focus": 0}
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        assert [option.action_name for option in window.options] == ["Counterspell (Prepared)"]
        option = window.options[0]
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=3,
        )

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture,
    )

    assert len(windows) == 1
    assert reactor.resources == {"spell_slot_3": 0, "spent_focus": 0}
    assert reactor.per_action_uses == {"Counterspell (Prepared)": 1}


def test_counterspell_window_binds_same_name_variants_and_commits_exact_selection() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            resource_cost={"spell_slot_3": 1, "red_focus": 1},
            spell_level=3,
        ),
        _counterspell(
            resource_cost={"spell_slot_3": 1, "blue_focus": 1},
            spell_level=3,
        ),
    ]
    reactor.resources = {"spell_slot_3": 2, "red_focus": 1, "blue_focus": 1}
    captured_ids: list[str] = []

    def choose_blue(window: ReactionWindowView) -> ReactionDecision:
        assert len(window.options) == 2
        captured_ids.extend(option.option_id for option in window.options)
        blue = next(
            option for option in window.options if ("blue_focus", 1) in option.resource_cost
        )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=blue.option_id,
            spell_slot_level=3,
        )

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=choose_blue,
    )

    assert len(set(captured_ids)) == 2
    assert reactor.resources == {"spell_slot_3": 1, "red_focus": 1, "blue_focus": 0}
    assert resources_spent[reactor.actor_id] == {"blue_focus": 1, "spell_slot_3": 1}


def test_counterspell_exact_fixed_cost_is_revalidated_atomically() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            resource_cost={"spell_slot_3": 1, "focus_charge": 1},
            spell_level=3,
        )
    ]
    reactor.resources = {"spell_slot_3": 1, "focus_charge": 1}

    def exhaust_focus(window: ReactionWindowView) -> ReactionDecision:
        option = window.options[0]
        reactor.resources["focus_charge"] = 0
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=3,
        )

    resources_spent, _ = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=exhaust_focus,
    )

    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources == {"spell_slot_3": 1, "focus_charge": 0}
    assert resources_spent[reactor.actor_id] == {}
    assert reactor.reaction_available is True
    assert reactor.per_action_uses == {}


def test_same_name_counterspell_variants_have_independent_max_uses() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            max_uses=1,
            spell_level=3,
            tags=["spell", "counterspell", "innate_spellcasting"],
        ),
        _counterspell(
            max_uses=1,
            spell_level=4,
            tags=["spell", "counterspell", "innate_spellcasting"],
        ),
    ]
    reactor.resources = {}

    def use_level_three(window: ReactionWindowView) -> ReactionDecision:
        option = next(
            candidate for candidate in window.options if candidate.effective_spell_level == 3
        )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
        )

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=use_level_three,
    )

    reactor.reaction_available = True
    remaining_levels: list[int] = []

    def capture_remaining(window: ReactionWindowView) -> ReactionDecision:
        remaining_levels.extend(int(option.effective_spell_level or 0) for option in window.options)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_remaining,
    )

    assert remaining_levels == [4]
    assert "Counterspell" not in reactor.per_action_uses
    assert sorted(reactor.per_action_uses.values()) == [1]


def test_same_name_counterspell_recharge_variants_roll_independently() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            recharge="6",
            spell_level=3,
            tags=["spell", "counterspell", "innate_spellcasting"],
        ),
        _counterspell(
            recharge="6",
            spell_level=4,
            tags=["spell", "counterspell", "innate_spellcasting"],
        ),
    ]
    reactor.resources = {}

    def use_level_three(window: ReactionWindowView) -> ReactionDecision:
        option = next(
            candidate for candidate in window.options if candidate.effective_spell_level == 3
        )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
        )

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=use_level_three,
    )

    reactor.reaction_available = True
    failed_roll = _SequenceRng([5])
    _roll_recharge_for_actor(failed_roll, reactor)
    assert failed_roll.values == []
    after_failed_roll: list[int] = []

    def capture_after_failed_roll(window: ReactionWindowView) -> ReactionDecision:
        after_failed_roll.extend(
            int(option.effective_spell_level or 0) for option in window.options
        )
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_after_failed_roll,
    )
    assert after_failed_roll == [4]

    successful_roll = _SequenceRng([6])
    _roll_recharge_for_actor(successful_roll, reactor)
    assert successful_roll.values == []
    after_successful_roll: list[int] = []

    def capture_after_successful_roll(window: ReactionWindowView) -> ReactionDecision:
        after_successful_roll.extend(
            int(option.effective_spell_level or 0) for option in window.options
        )
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_after_successful_roll,
    )
    assert after_successful_roll == [3, 4]


def test_same_name_counterspell_variants_share_limits_only_with_explicit_state_key() -> None:
    caster, recipient, reactor = _fixture()
    shared_tags = [
        "spell",
        "counterspell",
        "innate_spellcasting",
        "action_state_key:shared_counterspell",
    ]
    reactor.actions = [
        _counterspell(max_uses=1, spell_level=3, tags=shared_tags),
        _counterspell(max_uses=1, spell_level=4, tags=shared_tags),
    ]
    reactor.resources = {}

    def use_level_three(window: ReactionWindowView) -> ReactionDecision:
        option = next(
            candidate for candidate in window.options if candidate.effective_spell_level == 3
        )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
        )

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=use_level_three,
    )

    reactor.reaction_available = True
    followup_windows: list[ReactionWindowView] = []

    def capture_followup(window: ReactionWindowView) -> ReactionDecision:
        followup_windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
        provider=capture_followup,
    )

    assert followup_windows == []
    assert reactor.per_action_uses == {"action_state:shared_counterspell": 1}


def test_counterspell_automatic_resolution_emits_correlated_payment_envelope() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            resource_cost={"warlock_spell_slot_5": 1, "arcane_focus_charge": 1},
            spell_level=3,
        )
    ]
    reactor.resources = {"warlock_spell_slot_5": 1, "arcane_focus_charge": 1}
    windows: list[ReactionWindowView] = []

    def use_counterspell(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        option = window.options[0]
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=5,
        )

    _, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=use_counterspell,
    )

    lifecycle = [
        row["telemetry_type"] for row in telemetry if row.get("reaction_kind") == "counterspell"
    ]
    assert lifecycle == [
        "reaction_window_opened",
        "reaction_decision",
        "counterspell_resolution",
        "reaction_window_closed",
    ]
    assert len(windows) == 1
    window = windows[0]
    resolution = next(
        row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"
    )
    assert resolution["schema_version"] == "obs.v1"
    assert resolution["event_type"] == "counterspell_resolution"
    assert resolution["source"] == "dnd_sim.spell_reaction_runtime"
    assert resolution["reaction_chain_id"] == window.reaction_chain_id
    assert resolution["chain_depth"] == window.chain_depth == 1
    assert resolution["incoming_cast_id"] == window.incoming_cast_id
    assert resolution["parent_cast_id"] == resolution["incoming_cast_id"]
    assert resolution["incoming_cast_ordinal"] == window.incoming_cast_ordinal == 0
    assert resolution["counterspell_cast_id"].startswith("sc1_")
    assert resolution["counterspell_cast_ordinal"] == 0
    assert resolution["window_id"] == window.window_id
    assert resolution["reactor_id"] == reactor.actor_id
    assert resolution["reactor_order"] == window.reactor_order == 0
    assert resolution["source_actor_id"] == caster.actor_id
    assert resolution["target_actor_id"] == recipient.actor_id
    assert resolution["trigger_action"] == "Arcane Seal"
    assert resolution["incoming_action_identity"] == window.incoming_action_identity
    assert isinstance(resolution["counterspell_action_identity"], str)
    assert resolution["spell_level"] == 5
    assert resolution["distance_ft"] == 30.0
    assert resolution["option_id"] == window.options[0].option_id
    assert resolution["counterspell_spell_level"] == 5
    assert resolution["spellcasting_ability"] == "cha"
    assert resolution["spell_slot_level"] == 5
    assert resolution["spell_slot_resource_key"] == "warlock_spell_slot_5"
    assert resolution["resource_cost"] == {
        "arcane_focus_charge": 1,
        "warlock_spell_slot_5": 1,
    }
    assert resolution["resolution_method"] == "automatic"
    assert resolution["d20_roll"] is None
    assert resolution["check_modifier"] is None
    assert resolution["check_dc"] is None
    assert resolution["check_total"] is None
    assert resolution["outcome"] == "countered"
    assert resolution["payload"] == {key: resolution[key] for key in resolution["payload"]}
    opened = next(row for row in telemetry if row.get("telemetry_type") == "reaction_window_opened")
    assert opened["options"][0]["effective_spell_level"] == 5


def test_counterspell_check_resolution_records_roll_math_and_success() -> None:
    caster, recipient, reactor = _fixture()
    reactor.int_mod = 7
    reactor.cha_mod = 2

    _, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        rng=_SequenceRng([13]),
    )

    resolution = next(
        row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"
    )
    assert resolution["resolution_method"] == "ability_check"
    assert resolution["spellcasting_ability"] == "cha"
    assert resolution["d20_roll"] == 13
    assert resolution["check_modifier"] == 2
    assert resolution["check_dc"] == 15
    assert resolution["check_total"] == 15
    assert resolution["outcome"] == "countered"
    assert "arcane_sealed" not in recipient.conditions


def test_counterspell_check_without_casting_ability_provenance_fails_closed() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [_counterspell(spellcasting_ability=None)]

    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
    )

    assert "arcane_sealed" in recipient.conditions
    assert reactor.resources["spell_slot_3"] == 1
    assert reactor.reaction_available is True
    assert resources_spent[reactor.actor_id] == {}
    assert not any(row.get("reaction_kind") == "counterspell" for row in telemetry)


def test_spell_cast_identity_binds_full_homebrew_semantics() -> None:
    base = _incoming_spell(level=3)
    alternate_effect = replace(
        base,
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "different_homebrew_effect",
                "target": "target",
            }
        ],
    )

    assert spell_action_identity(base) != spell_action_identity(alternate_effect)


def test_failed_counterspell_resolution_continues_with_stable_chain_and_reactor_order() -> None:
    caster, recipient, first = _fixture(reactor_id="a_first")
    first.int_mod = -1
    first.wis_mod = -1
    first.cha_mod = -1
    second = _actor("b_second", team="enemy", position=(35.0, 0.0, 0.0))
    second.actions = [_counterspell()]
    second.resources = {"spell_slot_5": 1}

    _, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[first, second],
        rng=_SequenceRng([4]),
    )

    rows = [row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"]
    assert [row["outcome"] for row in rows] == ["counter_failed", "countered"]
    assert [row["reactor_id"] for row in rows] == ["a_first", "b_second"]
    assert [row["reactor_order"] for row in rows] == [0, 1]
    assert rows[0]["reaction_chain_id"] == rows[1]["reaction_chain_id"]
    assert rows[0]["incoming_cast_id"] == rows[1]["incoming_cast_id"]
    assert rows[0]["incoming_cast_ordinal"] == rows[1]["incoming_cast_ordinal"] == 0
    assert rows[0]["counterspell_cast_id"] != rows[1]["counterspell_cast_id"]
    assert rows[0]["counterspell_cast_ordinal"] == rows[1]["counterspell_cast_ordinal"] == 0
    assert rows[0]["d20_roll"] == 4
    assert rows[0]["check_modifier"] == -1
    assert rows[0]["check_dc"] == 15
    assert rows[0]["check_total"] == 3
    assert rows[1]["resolution_method"] == "automatic"

    lifecycle = [
        (row["telemetry_type"], row.get("reactor_id"))
        for row in telemetry
        if row.get("reaction_kind") == "counterspell"
    ]
    assert lifecycle == [
        ("reaction_window_opened", "a_first"),
        ("reaction_decision", "a_first"),
        ("reaction_window_opened", "b_second"),
        ("reaction_decision", "b_second"),
        ("reaction_window_closed", "b_second"),
        ("counterspell_resolution", "a_first"),
        ("reaction_window_closed", "a_first"),
        ("reaction_window_opened", "b_second"),
        ("reaction_decision", "b_second"),
        ("counterspell_resolution", "b_second"),
        ("reaction_window_closed", "b_second"),
    ]


def test_innate_counterspell_resolution_has_nullable_slot_payment_identity() -> None:
    caster, recipient, reactor = _fixture()
    reactor.actions = [
        _counterspell(
            max_uses=1,
            spell_level=3,
            tags=["spell", "counterspell", "innate_spellcasting"],
        )
    ]
    reactor.resources = {}

    _, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        action=_incoming_spell(level=3),
    )

    resolution = next(
        row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"
    )
    assert resolution["spell_slot_level"] is None
    assert resolution["spell_slot_resource_key"] is None
    assert resolution["resource_cost"] == {}
    assert resolution["counterspell_spell_level"] == 3
    assert resolution["resolution_method"] == "automatic"
    assert resolution["outcome"] == "countered"


def test_counterspell_pass_rejection_and_unavailable_paths_emit_no_resolution() -> None:
    caster, recipient, reactor = _fixture()
    _, pass_telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=lambda window: ReactionDecision(window_id=window.window_id, choice="pass"),
    )
    assert not any(row.get("telemetry_type") == "counterspell_resolution" for row in pass_telemetry)

    caster, recipient, reactor = _fixture()

    def reject(window: ReactionWindowView) -> ReactionDecision:
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id="unknown",
            spell_slot_level=3,
        )

    rejected_telemetry: list[dict] = []
    with pytest.raises(ReactionDecisionValidationError):
        _cast(
            caster=caster,
            recipient=recipient,
            reactors=[reactor],
            provider=reject,
            telemetry=rejected_telemetry,
        )
    assert not any(
        row.get("telemetry_type") == "counterspell_resolution" for row in rejected_telemetry
    )

    caster, recipient, reactor = _fixture()

    def make_unavailable(window: ReactionWindowView) -> ReactionDecision:
        reactor.resources["spell_slot_3"] = 0
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=window.options[0].option_id,
            spell_slot_level=3,
        )

    _, unavailable_telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=make_unavailable,
    )
    assert not any(
        row.get("telemetry_type") == "counterspell_resolution" for row in unavailable_telemetry
    )


def test_counterspell_cast_correlation_ids_are_deterministic_and_actor_local() -> None:
    def capture_sequence() -> list[ReactionWindowView]:
        caster, recipient, reactor = _fixture()
        windows: list[ReactionWindowView] = []

        def pass_and_capture(window: ReactionWindowView) -> ReactionDecision:
            windows.append(window)
            return ReactionDecision(window_id=window.window_id, choice="pass")

        for _ in range(2):
            _cast(
                caster=caster,
                recipient=recipient,
                reactors=[reactor],
                provider=pass_and_capture,
            )
        return windows

    first = capture_sequence()
    repeated = capture_sequence()

    assert [window.incoming_cast_id for window in first] == [
        window.incoming_cast_id for window in repeated
    ]
    assert [window.reaction_chain_id for window in first] == [
        window.reaction_chain_id for window in repeated
    ]
    assert [window.incoming_cast_ordinal for window in first] == [0, 1]
    assert first[0].incoming_cast_id != first[1].incoming_cast_id
    assert first[0].reaction_chain_id != first[1].reaction_chain_id
    assert all(str(window.incoming_cast_id).startswith("sc1_") for window in first)
    assert all(str(window.reaction_chain_id).startswith("src1_") for window in first)


def test_spell_cast_ordinals_do_not_reuse_generic_combat_event_ordinals() -> None:
    caster, recipient, reactor = _fixture()
    caster.next_combat_event_ordinal = 41
    windows: list[ReactionWindowView] = []

    def pass_and_capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[reactor],
        provider=pass_and_capture,
    )

    assert caster.next_combat_event_ordinal == 42
    assert caster.next_spell_cast_ordinal == 1
    assert windows[0].incoming_cast_ordinal == 0
    assert reactor.next_spell_cast_ordinal == 0


@pytest.mark.parametrize(
    ("counter_count", "spell_resolves"),
    [(1, False), (2, True), (3, False)],
)
def test_nested_counterspell_parity_and_declaration_order(
    counter_count: int,
    spell_resolves: bool,
) -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(counter_count)
    timing_engine = CombatTimingEngine()
    declarations: list[tuple[str, str]] = []
    timing_engine.subscribe(
        ActionDeclaredEvent,
        lambda event: declarations.append((event.attacker.actor_id, event.action.name)),
        name="capture declarations",
    )

    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=reactors,
        action=_incoming_spell(level=3),
        provider=_use_first_reaction_option,
        timing_engine=timing_engine,
    )

    expected_declarations = [("caster", "Arcane Seal"), ("b_first", "Counterspell")]
    expected_spenders = ["b_first"]
    if counter_count >= 2:
        expected_declarations.append(("caster", "Counterspell"))
        expected_spenders.append("caster")
    if counter_count >= 3:
        expected_declarations.append(("z_third", "Counterspell"))
        expected_spenders.append("z_third")
    assert declarations == expected_declarations
    assert ("arcane_sealed" in recipient.conditions) is spell_resolves
    assert [
        row["reactor_id"]
        for row in telemetry
        if row.get("telemetry_type") == "counterspell_resolution"
    ] == list(reversed(expected_spenders))
    for actor_id in expected_spenders:
        actor = (
            caster
            if actor_id == caster.actor_id
            else next(reactor for reactor in reactors if reactor.actor_id == actor_id)
        )
        assert actor.resources["spell_slot_3"] == 0
        assert actor.reaction_available is False
        assert resources_spent[actor_id] == {"spell_slot_3": 1}


def test_countered_counterspell_skips_its_higher_spell_check_and_rng() -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(2)

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=reactors,
        action=_incoming_spell(level=5),
        provider=_use_first_reaction_option,
        rng=_SequenceRng([]),
    )

    assert "arcane_sealed" in recipient.conditions


def test_cancelled_counterspell_declaration_keeps_committed_payment() -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(1)
    first = reactors[0]
    timing_engine = CombatTimingEngine()

    def cancel_counterspell(event: ActionDeclaredEvent) -> None:
        if event.action.name == "Counterspell":
            event.cancel("test cancellation")

    timing_engine.subscribe(
        ActionDeclaredEvent,
        cancel_counterspell,
        priority=100,
        name="cancel Counterspell",
    )

    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=reactors,
        action=_incoming_spell(level=3),
        provider=_use_first_reaction_option,
        timing_engine=timing_engine,
    )

    assert "arcane_sealed" in recipient.conditions
    assert first.resources["spell_slot_3"] == 0
    assert first.reaction_available is False
    assert first.per_action_uses == {"Counterspell": 1}
    assert first.next_spell_cast_ordinal == 0
    assert resources_spent[first.actor_id] == {"spell_slot_3": 1}
    assert not any(row.get("telemetry_type") == "counterspell_resolution" for row in telemetry)
    closed = next(row for row in telemetry if row.get("telemetry_type") == "reaction_window_closed")
    assert closed["status"] == "cancelled"
    assert closed["reason"] == "action_declaration_cancelled"


def test_nested_counterspell_after_action_hooks_complete_lifo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(3)
    observed: list[tuple[str, str]] = []
    original_dispatch = engine_module._dispatch_combat_event

    def capture_dispatch(**kwargs):
        if kwargs.get("event") == "after_action":
            observed.append((kwargs["trigger_actor"].actor_id, kwargs["trigger_action"].name))
        return original_dispatch(**kwargs)

    monkeypatch.setattr(engine_module, "_dispatch_combat_event", capture_dispatch)

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=reactors,
        action=_incoming_spell(level=3),
        provider=_use_first_reaction_option,
    )

    assert observed == [
        ("z_third", "Counterspell"),
        ("caster", "Counterspell"),
        ("b_first", "Counterspell"),
        ("caster", "Arcane Seal"),
    ]


def test_failed_nested_counterspell_check_allows_later_reactor_at_same_depth() -> None:
    caster = _actor("caster", team="party", position=(0.0, 0.0, 0.0))
    recipient = _actor("recipient", team="party", position=(0.0, 10.0, 0.0))
    failed_nested = _actor(
        "a_failed_nested",
        team="party",
        position=(25.0, 0.0, 0.0),
    )
    failed_nested.actions = [_counterspell()]
    failed_nested.resources = {"spell_slot_3": 1}
    failed_nested.cha_mod = -5
    later_nested = _actor(
        "b_later_nested",
        team="party",
        position=(20.0, 0.0, 0.0),
    )
    later_nested.actions = [_counterspell()]
    later_nested.resources = {"spell_slot_5": 1}
    outer_counterspeller = _actor(
        "z_outer_counterspeller",
        team="enemy",
        position=(30.0, 0.0, 0.0),
    )
    outer_counterspeller.actions = [_counterspell()]
    outer_counterspeller.resources = {"spell_slot_5": 1}
    windows: list[ReactionWindowView] = []

    def decide(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        if window.chain_depth == 1 and window.reactor_id != outer_counterspeller.actor_id:
            return ReactionDecision(window_id=window.window_id, choice="pass")
        if window.chain_depth > 2:
            return ReactionDecision(window_id=window.window_id, choice="pass")
        return _use_first_reaction_option(window)

    rng = _SequenceRng([1])
    resources_spent, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=[failed_nested, later_nested, outer_counterspeller],
        action=_incoming_spell(level=5),
        provider=decide,
        rng=rng,
    )

    assert "arcane_sealed" in recipient.conditions
    assert [window.reactor_id for window in windows if window.chain_depth == 2] == [
        "a_failed_nested",
        "b_later_nested",
    ]
    resolution_rows = [
        row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"
    ]
    assert [row["reactor_id"] for row in resolution_rows] == [
        "a_failed_nested",
        "b_later_nested",
        "z_outer_counterspeller",
    ]
    assert [row["chain_depth"] for row in resolution_rows] == [2, 2, 1]
    assert [row["outcome"] for row in resolution_rows] == [
        "counter_failed",
        "countered",
        "counterspell_countered",
    ]
    ability_checks = [row for row in resolution_rows if row["resolution_method"] == "ability_check"]
    assert len(ability_checks) == 1
    assert ability_checks[0]["d20_roll"] == 1
    assert ability_checks[0]["check_modifier"] == -5
    assert ability_checks[0]["check_total"] == -4
    assert rng.values == []
    assert failed_nested.resources["spell_slot_3"] == 0
    assert later_nested.resources["spell_slot_5"] == 0
    assert outer_counterspeller.resources["spell_slot_5"] == 0
    assert resources_spent[failed_nested.actor_id] == {"spell_slot_3": 1}
    assert resources_spent[later_nested.actor_id] == {"spell_slot_5": 1}
    assert resources_spent[outer_counterspeller.actor_id] == {"spell_slot_5": 1}


@pytest.mark.parametrize(
    ("max_depth", "max_attempts"),
    [(1, 32), (8, 1)],
    ids=["depth-bound", "attempt-bound"],
)
def test_counterspell_chain_guard_precedes_nested_window_and_payment(
    max_depth: int,
    max_attempts: int,
) -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(2)
    outer_counterspeller = reactors[0]
    actors = {actor.actor_id: actor for actor in (caster, recipient, outer_counterspeller)}
    resources_spent = {actor_id: {} for actor_id in actors}
    telemetry: list[dict] = []
    windows: list[ReactionWindowView] = []
    chain_state = CounterspellChainState(
        max_depth=max_depth,
        max_attempts=max_attempts,
    )
    rng = _SequenceRng([])

    def use_and_capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return _use_first_reaction_option(window)

    outcome = run_spell_declaration_pipeline_outcome(
        rng=rng,
        actor=caster,
        action=_incoming_spell(level=3),
        targets=[recipient],
        actors=actors,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=4,
        turn_token="4:caster",
        timing_engine=CombatTimingEngine(),
        spell_cast_request=None,
        antimagic_suppression_condition="antimagic_suppressed",
        subtle_spell=False,
        light_level="bright",
        adapters=_spell_pipeline_adapters(),
        obstacles=[],
        reaction_decision_provider=use_and_capture,
        telemetry=telemetry,
        counterspell_chain_state=chain_state,
    )

    assert outcome.status == "countered"
    assert chain_state.attempts == 1
    assert chain_state.reaction_chain_id == outcome.cast_frame.reaction_chain_id
    assert [(window.reactor_id, window.chain_depth) for window in windows] == [("b_first", 1)]
    assert [
        (row["reactor_id"], row["chain_depth"])
        for row in telemetry
        if row.get("telemetry_type") == "reaction_window_opened"
    ] == [("b_first", 1)]
    assert outer_counterspeller.resources["spell_slot_3"] == 0
    assert resources_spent[outer_counterspeller.actor_id] == {"spell_slot_3": 1}
    assert caster.resources["spell_slot_3"] == 1
    assert caster.reaction_available is True
    assert caster.per_action_uses == {}
    assert caster.next_spell_cast_ordinal == 1
    assert rng.values == []


def test_nested_counterspell_telemetry_preserves_ancestry_and_unwinds_deepest_first() -> None:
    caster, recipient, reactors = _nested_counterspell_fixture(3)
    windows: list[ReactionWindowView] = []

    def use_and_capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return _use_first_reaction_option(window)

    _, telemetry = _cast(
        caster=caster,
        recipient=recipient,
        reactors=reactors,
        action=_incoming_spell(level=3),
        provider=use_and_capture,
    )

    resolution_rows = [
        row for row in telemetry if row.get("telemetry_type") == "counterspell_resolution"
    ]
    assert [window.chain_depth for window in windows] == [1, 2, 3]
    assert [row["chain_depth"] for row in resolution_rows] == [3, 2, 1]
    assert [row["reactor_id"] for row in resolution_rows] == [
        "z_third",
        "caster",
        "b_first",
    ]
    assert [row["resolution_method"] for row in resolution_rows] == [
        "automatic",
        "interrupted",
        "automatic",
    ]
    assert [row["outcome"] for row in resolution_rows] == [
        "countered",
        "counterspell_countered",
        "countered",
    ]
    assert [row["window_id"] for row in resolution_rows] == [
        windows[2].window_id,
        windows[1].window_id,
        windows[0].window_id,
    ]
    chain_ids = {
        *(window.reaction_chain_id for window in windows),
        *(row["reaction_chain_id"] for row in resolution_rows),
    }
    assert len(chain_ids) == 1
    deepest, interrupted, outermost = resolution_rows
    assert deepest["incoming_cast_id"] == interrupted["counterspell_cast_id"]
    assert interrupted["incoming_cast_id"] == outermost["counterspell_cast_id"]
    assert deepest["parent_cast_id"] == deepest["incoming_cast_id"]
    assert interrupted["parent_cast_id"] == interrupted["incoming_cast_id"]
    assert outermost["parent_cast_id"] == outermost["incoming_cast_id"]
    assert interrupted["countered_by_cast_id"] == deepest["counterspell_cast_id"]
    assert deepest["countered_by_cast_id"] is None
    assert outermost["countered_by_cast_id"] is None


def test_lethal_mage_slayer_hook_does_not_undo_resolved_counterspell() -> None:
    caster = _actor("caster", team="party", position=(0.0, 0.0, 0.0))
    recipient = _actor("recipient", team="party", position=(0.0, 10.0, 0.0))
    counterspeller = _actor(
        "counterspeller",
        team="enemy",
        position=(30.0, 0.0, 0.0),
    )
    counterspeller.actions = [_counterspell(spell_level=3)]
    counterspeller.resources = {"spell_slot_3": 1}
    mage_slayer = _actor(
        "mage_slayer",
        team="party",
        position=(35.0, 0.0, 0.0),
    )
    mage_slayer.traits = {
        "mage_slayer": {
            "name": "Mage Slayer",
            "source_type": "feat",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "spell_cast_within_5ft",
                }
            ],
        }
    }
    mage_slayer.actions = [
        ActionDefinition(
            name="lethal_sword",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            target_mode="single_enemy",
            to_hit=100,
            damage="60",
            damage_type="slashing",
            reach_ft=5,
            range_ft=5,
        )
    ]
    windows: list[ReactionWindowView] = []
    telemetry: list[dict] = []

    def counterspell_then_mage_slayer(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        option = window.options[0]
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            spell_slot_level=(
                option.legal_spell_slot_levels[0] if option.legal_spell_slot_levels else None
            ),
        )

    _cast(
        caster=caster,
        recipient=recipient,
        reactors=[counterspeller, mage_slayer],
        action=_incoming_spell(level=3),
        provider=counterspell_then_mage_slayer,
        rng=_SequenceRng([10]),
        telemetry=telemetry,
    )

    assert "arcane_sealed" not in recipient.conditions
    assert counterspeller.hp == 0
    assert counterspeller.dead is True
    mage_slayer_windows = [
        window for window in windows if window.trigger.feature_name == "Mage Slayer"
    ]
    assert len(mage_slayer_windows) == 1
    counterspell_resolution_index = next(
        index
        for index, row in enumerate(telemetry)
        if row.get("telemetry_type") == "counterspell_resolution"
        and row.get("reactor_id") == counterspeller.actor_id
    )
    counterspell_close_index = next(
        index
        for index, row in enumerate(telemetry)
        if row.get("telemetry_type") == "reaction_window_closed"
        and row.get("reaction_kind") == "counterspell"
        and row.get("reactor_id") == counterspeller.actor_id
    )
    mage_slayer_open_indices = [
        index
        for index, row in enumerate(telemetry)
        if row.get("telemetry_type") == "reaction_window_opened"
        and row.get("feature_name") == "Mage Slayer"
    ]
    assert len(mage_slayer_open_indices) == 1
    assert counterspell_resolution_index < counterspell_close_index < mage_slayer_open_indices[0]
