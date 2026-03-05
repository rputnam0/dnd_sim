from __future__ import annotations

import random
from typing import Any

from dnd_sim.engine import (
    SimulationArtifacts,
    _action_available,
    _actor_state_snapshot,
    _build_actor_from_character,
    _build_actor_from_enemy,
    _build_actor_views,
    _build_battlefield_obstacles,
    _build_construct_companions,
    _build_initiative_order_with_scores,
    _build_round_metadata,
    _can_act,
    _controller_id_for_actor,
    _dispatch_combat_event,
    _enemies_defeated,
    _execute_action,
    _execute_declared_turn_or_error,
    _flatten_trial,
    _force_end_concentration_if_needed,
    _mark_action_cost_used,
    _metric,
    _owner_is_incapacitated,
    _party_defeated,
    _process_hazard_start_turn_triggers,
    _raise_turn_declaration_error,
    _refresh_legendary_actions_for_turn,
    _reorder_initiative_for_construct_companions,
    _resolve_action_selection,
    _resolve_next_encounter_index,
    _resolve_targets_for_action,
    _roll_recharge_for_actor,
    _run_exploration_leg,
    _run_lair_actions,
    _run_legendary_actions,
    _sync_initiative_order,
    _tick_conditions_for_actor,
    _tick_hazards_for_actor_turn,
    _trigger_readied_actions,
    long_rest,
    resolve_death_save,
    short_rest,
)
from dnd_sim.io import EncounterConfig, LoadedScenario
from dnd_sim.models import ActorRuntimeState, SimulationSummary, SummaryMetric, TrialResult
from dnd_sim.strategy_api import TurnDeclaration


def run_simulation(
    scenario: LoadedScenario,
    character_db: dict[str, dict[str, Any]],
    traits_db: dict[str, dict[str, Any]],
    strategy_registry: dict[str, Any],
    *,
    trials: int,
    seed: int,
    run_id: str,
) -> SimulationArtifacts:
    if trials <= 0:
        raise ValueError("trials must be >= 1")

    rng = random.Random(seed)
    trial_results: list[TrialResult] = []

    assumption_overrides = scenario.config.assumption_overrides
    party_default_strategy = assumption_overrides.get("party_strategy", "optimal_expected_damage")
    enemy_default_strategy = assumption_overrides.get("enemy_strategy", "optimal_expected_damage")
    actor_strategy_overrides = assumption_overrides.get("actor_strategy", {})
    tracked_resource_names: dict[str, set[str]] = {}
    battlefield = (
        scenario.config.battlefield if isinstance(scenario.config.battlefield, dict) else {}
    )
    exploration = (
        scenario.config.exploration if isinstance(scenario.config.exploration, dict) else {}
    )
    exploration_legs = exploration.get("legs") if isinstance(exploration.get("legs"), list) else []
    light_level = str(battlefield.get("light_level", "bright")).lower()
    battlefield_obstacles = _build_battlefield_obstacles(battlefield.get("obstacles", []))

    encounter_plan = list(scenario.config.encounters)
    if not encounter_plan:
        encounter_plan = [EncounterConfig(enemies=list(scenario.config.enemies))]

    termination_rules = (
        scenario.config.termination_rules
        if isinstance(scenario.config.termination_rules, dict)
        else {}
    )
    party_defeat_rule = termination_rules.get("party_defeat", "all_unconscious_or_dead")
    enemy_defeat_rule = termination_rules.get("enemy_defeat", "all_dead")
    max_rounds = int(termination_rules.get("max_rounds", 20))
    max_encounter_steps = int(
        termination_rules.get("max_encounter_steps", max(1, len(encounter_plan) * 3))
    )
    if max_rounds <= 0:
        raise ValueError("termination_rules.max_rounds must be >= 1")
    if max_encounter_steps <= 0:
        raise ValueError("termination_rules.max_encounter_steps must be >= 1")

    short_rest_healing = int(scenario.config.resource_policy.get("short_rest_healing", 0))

    for trial_idx in range(trials):
        actors: dict[str, ActorRuntimeState] = {}
        damage_taken: dict[str, int] = {}
        damage_dealt: dict[str, int] = {}
        resources_spent: dict[str, dict[str, int]] = {}
        threat_scores: dict[str, int] = {}
        downed_counts: dict[str, int] = {}
        death_counts: dict[str, int] = {}
        remaining_hp: dict[str, int] = {}
        active_hazards: list[dict[str, Any]] = []
        trial_rule_trace: list[dict[str, Any]] = []
        trial_telemetry: list[dict[str, Any]] = []
        encounter_outcomes: list[dict[str, Any]] = []
        state_snapshots: list[dict[str, Any]] = []

        for character_id in scenario.config.party:
            if character_id not in character_db:
                raise ValueError(f"Character ID missing from DB: {character_id}")
            actor = _build_actor_from_character(character_db[character_id], traits_db)
            actors[actor.actor_id] = actor
            damage_taken[actor.actor_id] = 0
            damage_dealt[actor.actor_id] = 0
            resources_spent[actor.actor_id] = {}
            threat_scores[actor.actor_id] = 0
            downed_counts[actor.actor_id] = 0
            death_counts[actor.actor_id] = 0

            for companion in _build_construct_companions(actor):
                if companion.actor_id in actors:
                    continue
                actors[companion.actor_id] = companion
                damage_taken[companion.actor_id] = 0
                damage_dealt[companion.actor_id] = 0
                resources_spent[companion.actor_id] = {}
                threat_scores[companion.actor_id] = 0
                downed_counts[companion.actor_id] = 0
                death_counts[companion.actor_id] = 0

        total_rounds = 0
        overall_winner = "draw"
        encounter_idx: int | None = 0
        encounter_step = 0

        while encounter_idx is not None and encounter_idx < len(encounter_plan):
            if encounter_step >= max_encounter_steps:
                raise ValueError(
                    "Encounter branching exceeded termination_rules.max_encounter_steps"
                )

            step_index = encounter_step
            encounter_step += 1
            encounter = encounter_plan[encounter_idx]
            encounter_enemy_ids = list(encounter.enemies)

            for aid in list(actors.keys()):
                if actors[aid].team != "party":
                    downed_counts[aid] = actors[aid].downed_count
                    death_counts[aid] = int(actors[aid].dead)
                    remaining_hp[aid] = actors[aid].hp
                    del actors[aid]

            enemy_counts: dict[str, int] = {}
            for enemy_id in encounter_enemy_ids:
                count = enemy_counts.get(enemy_id, 0) + 1
                enemy_counts[enemy_id] = count
                unique_enemy_id = (
                    f"{enemy_id}_e{step_index}_{count}"
                    if (count > 1 or len(encounter_plan) > 1)
                    else enemy_id
                )

                actor = _build_actor_from_enemy(scenario.enemies[enemy_id], traits_db)
                actor.actor_id = unique_enemy_id
                actor.position = (0.0, 30.0, 0.0)
                actors[actor.actor_id] = actor

                damage_taken[actor.actor_id] = 0
                damage_dealt[actor.actor_id] = 0
                resources_spent[actor.actor_id] = {}
                threat_scores[actor.actor_id] = 0
                downed_counts[actor.actor_id] = 0
                death_counts[actor.actor_id] = 0

            if trial_idx == 0 and step_index == 0:
                tracked_resource_names = {
                    actor_id: set(actor.resources.keys()) for actor_id, actor in actors.items()
                }

            initiative_order, initiative_scores = _build_initiative_order_with_scores(
                rng, actors, scenario.config.initiative_mode
            )
            initiative_order = _reorder_initiative_for_construct_companions(
                initiative_order, actors
            )
            rounds = 0

            while rounds < max_rounds:
                rounds += 1
                for actor in actors.values():
                    actor.lair_action_used_this_round = False
                    if hasattr(actor, "commanded_this_round"):
                        actor.commanded_this_round = False

                metadata = _build_round_metadata(
                    actors=actors,
                    threat_scores=threat_scores,
                    burst_round_threshold=int(
                        scenario.config.resource_policy.get("burst_round_threshold", 3)
                    ),
                    active_hazards=active_hazards,
                    light_level=light_level,
                    strategy_overrides=assumption_overrides,
                )
                state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                for strategy in strategy_registry.values():
                    strategy.on_round_start(state_view)

                initiative_order = _sync_initiative_order(initiative_order, actors)
                initiative_order = _reorder_initiative_for_construct_companions(
                    initiative_order, actors
                )
                lair_actions_resolved = False

                def _resolve_turn_end(actor: ActorRuntimeState, turn_token: str) -> None:
                    _dispatch_combat_event(
                        rng=rng,
                        event="turn_end",
                        trigger_actor=actor,
                        trigger_target=actor,
                        trigger_action=None,
                        actors=actors,
                        round_number=rounds,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=trial_rule_trace,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )
                    _run_legendary_actions(
                        rng=rng,
                        trigger_actor=actor,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                        telemetry=trial_telemetry,
                        round_number=rounds,
                        turn_token=turn_token,
                    )

                for actor_id in initiative_order:
                    if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                        actors, enemy_defeat_rule
                    ):
                        break

                    if not lair_actions_resolved:
                        actor_initiative = initiative_scores.get(actor_id)
                        if actor_initiative is None:
                            actor_state = actors.get(actor_id)
                            actor_initiative = (
                                actor_state.initiative_mod if actor_state is not None else -999
                            )
                        if actor_initiative < 20:
                            _run_lair_actions(
                                rng=rng,
                                actors=actors,
                                damage_dealt=damage_dealt,
                                damage_taken=damage_taken,
                                threat_scores=threat_scores,
                                resources_spent=resources_spent,
                                active_hazards=active_hazards,
                                obstacles=battlefield_obstacles,
                                light_level=light_level,
                                telemetry=trial_telemetry,
                                round_number=rounds,
                            )
                            lair_actions_resolved = True
                            if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                                actors, enemy_defeat_rule
                            ):
                                break

                    if actor_id not in actors:
                        continue
                    actor = actors[actor_id]
                    _refresh_legendary_actions_for_turn(actor)
                    actor.movement_remaining = float(actor.speed_ft)
                    actor.took_attack_action_this_turn = False
                    actor.bonus_action_spell_restriction_active = False
                    actor.non_action_cantrip_spell_cast_this_turn = False
                    _roll_recharge_for_actor(rng, actor)
                    _tick_conditions_for_actor(rng, actor)
                    _tick_hazards_for_actor_turn(
                        active_hazards=active_hazards,
                        actor=actor,
                        actors=actors,
                        boundary="turn_start",
                    )
                    _force_end_concentration_if_needed(
                        actor, actors=actors, active_hazards=active_hazards
                    )
                    if "grappled" in actor.conditions:
                        actor.movement_remaining = 0.0
                    actor.bonus_available = True
                    actor.reaction_available = True
                    actor.sneak_attack_used_this_turn = False
                    actor.colossus_slayer_used_this_turn = False
                    actor.horde_breaker_used_this_turn = False
                    actor.gwm_bonus_trigger_available = False

                    if actor.dead:
                        continue

                    if actor.hp <= 0:
                        resolve_death_save(rng, actor)
                        _resolve_turn_end(actor, f"{rounds}:{actor.actor_id}")
                        continue

                    _process_hazard_start_turn_triggers(
                        rng=rng,
                        actor=actor,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                    )
                    if actor.dead or actor.hp <= 0:
                        continue

                    if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                        actors, enemy_defeat_rule
                    ):
                        break
                    turn_token = f"{rounds}:{actor.actor_id}"
                    _dispatch_combat_event(
                        rng=rng,
                        event="turn_start",
                        trigger_actor=actor,
                        trigger_target=actor,
                        trigger_action=None,
                        actors=actors,
                        round_number=rounds,
                        turn_token=turn_token,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        rule_trace=trial_rule_trace,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                    _trigger_readied_actions(
                        rng=rng,
                        trigger_actor=actor,
                        round_number=rounds,
                        turn_token=turn_token,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                    )

                    if actor.dead or actor.hp <= 0:
                        _resolve_turn_end(actor, turn_token)
                        continue
                    if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                        actors, enemy_defeat_rule
                    ):
                        break
                    if not _can_act(actor):
                        _resolve_turn_end(actor, turn_token)
                        continue

                    controller_id = _controller_id_for_actor(actor)
                    controller = actors.get(controller_id) if controller_id else None
                    should_force_dodge = (
                        bool(getattr(actor, "requires_command", False))
                        and not bool(getattr(actor, "commanded_this_round", False))
                        and not _owner_is_incapacitated(controller)
                    )
                    if should_force_dodge:
                        action = _resolve_action_selection(actor, "dodge")
                        if _action_available(actor, action, turn_token=turn_token):
                            resolved_targets = _resolve_targets_for_action(
                                rng=rng,
                                actor=actor,
                                action=action,
                                actors=actors,
                                requested=[],
                                obstacles=battlefield_obstacles,
                            )
                            if resolved_targets:
                                actor.per_action_uses[action.name] = (
                                    actor.per_action_uses.get(action.name, 0) + 1
                                )
                                _mark_action_cost_used(actor, action)
                                _execute_action(
                                    rng=rng,
                                    actor=actor,
                                    action=action,
                                    targets=resolved_targets,
                                    actors=actors,
                                    damage_dealt=damage_dealt,
                                    damage_taken=damage_taken,
                                    threat_scores=threat_scores,
                                    resources_spent=resources_spent,
                                    active_hazards=active_hazards,
                                    obstacles=battlefield_obstacles,
                                    light_level=light_level,
                                    telemetry=trial_telemetry,
                                    strategy_name="forced_dodge",
                                )
                        if hasattr(actor, "commanded_this_round"):
                            actor.commanded_this_round = False
                        _resolve_turn_end(actor, turn_token)
                        continue

                    strategy_name = actor_strategy_overrides.get(actor.actor_id)
                    if strategy_name is None:
                        strategy_name = (
                            party_default_strategy
                            if actor.team == "party"
                            else enemy_default_strategy
                        )
                    strategy = strategy_registry.get(strategy_name)
                    if strategy is None:
                        raise ValueError(
                            f"No strategy registered for actor {actor.actor_id}: {strategy_name}"
                        )

                    metadata = _build_round_metadata(
                        actors=actors,
                        threat_scores=threat_scores,
                        burst_round_threshold=int(
                            scenario.config.resource_policy.get("burst_round_threshold", 3)
                        ),
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                        strategy_overrides=assumption_overrides,
                    )
                    state_view = _build_actor_views(actors, initiative_order, rounds, metadata)
                    actor_view = state_view.actors[actor.actor_id]
                    turn_declaration = strategy.declare_turn(actor_view, state_view)
                    if turn_declaration is None:
                        trial_telemetry.append(
                            {
                                "telemetry_type": "decision",
                                "round": rounds,
                                "strategy": strategy_name,
                                "actor_id": actor.actor_id,
                                "team": actor.team,
                                "intent_action": None,
                                "resolved_action": None,
                                "fallback_reason": "declare_turn_none",
                                "requested_targets": [],
                                "resolved_targets": [],
                                "rationale": {},
                                "extra_resource_request": {},
                                "resource_cost": {},
                            }
                        )
                        _resolve_turn_end(actor, turn_token)
                        continue
                    if not isinstance(turn_declaration, TurnDeclaration):
                        _raise_turn_declaration_error(
                            actor=actor,
                            code="invalid_turn_declaration_type",
                            field="turn_declaration",
                            message="declare_turn(...) must return TurnDeclaration or None.",
                            details={"actual_type": type(turn_declaration).__name__},
                        )
                    _execute_declared_turn_or_error(
                        rng=rng,
                        actor=actor,
                        declaration=turn_declaration,
                        strategy_name=strategy_name,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        telemetry=trial_telemetry,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                        round_number=rounds,
                        turn_token=turn_token,
                        rule_trace=trial_rule_trace,
                    )
                    _resolve_turn_end(actor, turn_token)

                if (
                    not lair_actions_resolved
                    and not _party_defeated(actors, party_defeat_rule)
                    and not _enemies_defeated(actors, enemy_defeat_rule)
                ):
                    _run_lair_actions(
                        rng=rng,
                        actors=actors,
                        damage_dealt=damage_dealt,
                        damage_taken=damage_taken,
                        threat_scores=threat_scores,
                        resources_spent=resources_spent,
                        active_hazards=active_hazards,
                        obstacles=battlefield_obstacles,
                        light_level=light_level,
                        telemetry=trial_telemetry,
                        round_number=rounds,
                    )

                if _party_defeated(actors, party_defeat_rule) or _enemies_defeated(
                    actors, enemy_defeat_rule
                ):
                    break

            total_rounds += rounds

            party_is_defeated = _party_defeated(actors, party_defeat_rule)
            enemies_are_defeated = _enemies_defeated(actors, enemy_defeat_rule)
            if party_is_defeated:
                encounter_winner = "enemy"
                encounter_outcome = "party_defeat"
            elif enemies_are_defeated:
                encounter_winner = "party"
                encounter_outcome = "enemy_defeat"
            else:
                party_hp = sum(a.hp for a in actors.values() if a.team == "party" and not a.dead)
                enemy_hp = sum(a.hp for a in actors.values() if a.team != "party" and not a.dead)
                encounter_winner = "party" if party_hp >= enemy_hp else "enemy"
                encounter_outcome = encounter_winner

            next_encounter_idx, branch_key = _resolve_next_encounter_index(
                encounter=encounter,
                encounter_outcome=encounter_outcome,
                encounter_winner=encounter_winner,
                default_next=encounter_idx + 1,
                encounter_count=len(encounter_plan),
            )

            continue_campaign = next_encounter_idx is not None
            if party_is_defeated:
                overall_winner = "enemy"
                continue_campaign = False
                next_encounter_idx = None
            elif encounter_winner == "enemy" and branch_key is None:
                overall_winner = "enemy"
                continue_campaign = False
                next_encounter_idx = None

            if continue_campaign:
                for actor in actors.values():
                    if actor.team != "party" or actor.dead:
                        continue
                    if encounter.long_rest_after:
                        long_rest(actor)
                    elif encounter.short_rest_after:
                        short_rest(actor, healing=short_rest_healing)

                if step_index < len(exploration_legs):
                    _run_exploration_leg(
                        rng=rng,
                        actors=actors,
                        damage_taken=damage_taken,
                        resources_spent=resources_spent,
                        leg_config=exploration_legs[step_index],
                    )

            checkpoint_id = encounter.checkpoint or f"encounter_{step_index}_end"
            party_snapshot = {
                actor_id: _actor_state_snapshot(actor)
                for actor_id, actor in sorted(actors.items())
                if actor.team == "party"
            }
            enemy_snapshot = {
                actor_id: _actor_state_snapshot(actor)
                for actor_id, actor in sorted(actors.items())
                if actor.team != "party"
            }
            state_snapshots.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "encounter_index": encounter_idx,
                    "encounter_step": step_index,
                    "outcome": encounter_outcome,
                    "winner": encounter_winner,
                    "next_encounter_index": next_encounter_idx,
                    "party": party_snapshot,
                    "enemies": enemy_snapshot,
                }
            )
            encounter_outcomes.append(
                {
                    "encounter_index": encounter_idx,
                    "encounter_step": step_index,
                    "outcome": encounter_outcome,
                    "winner": encounter_winner,
                    "branch_key": branch_key,
                    "next_encounter_index": next_encounter_idx,
                }
            )

            if not continue_campaign:
                if overall_winner == "draw":
                    overall_winner = encounter_winner
                break

            encounter_idx = next_encounter_idx

        if overall_winner == "draw":
            if _party_defeated(actors, party_defeat_rule):
                overall_winner = "enemy"
            elif _enemies_defeated(actors, enemy_defeat_rule):
                overall_winner = "party"

        for aid, actor in actors.items():
            downed_counts[aid] = actor.downed_count
            death_counts[aid] = int(actor.dead)
            remaining_hp[aid] = actor.hp

        trial = TrialResult(
            trial_index=trial_idx,
            rounds=total_rounds,
            winner=overall_winner,
            damage_taken=dict(damage_taken),
            damage_dealt=dict(damage_dealt),
            resources_spent=resources_spent,
            downed_counts=downed_counts,
            death_counts=death_counts,
            remaining_hp=remaining_hp,
            telemetry=trial_telemetry,
            encounter_outcomes=encounter_outcomes,
            state_snapshots=state_snapshots,
        )
        trial_results.append(trial)

    trial_rows = [_flatten_trial(trial) for trial in trial_results]

    party_wins = sum(1 for trial in trial_results if trial.winner == "party")
    enemy_wins = sum(1 for trial in trial_results if trial.winner == "enemy")

    actor_ids = sorted(trial_results[0].damage_taken.keys()) if trial_results else []

    per_actor_damage_taken = {
        actor_id: _metric([trial.damage_taken.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_damage_dealt = {
        actor_id: _metric([trial.damage_dealt.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }

    resources_all: dict[str, dict[str, list[float]]] = {actor_id: {} for actor_id in actor_ids}
    for trial in trial_results:
        for actor_id in actor_ids:
            for resource_name in tracked_resource_names.get(actor_id, set()):
                resources_all[actor_id].setdefault(resource_name, [])
            for resource_name, amount in trial.resources_spent.get(actor_id, {}).items():
                resources_all[actor_id].setdefault(resource_name, []).append(float(amount))
            for resource_name in resources_all[actor_id]:
                if resource_name not in trial.resources_spent.get(actor_id, {}):
                    resources_all[actor_id][resource_name].append(0.0)

    per_actor_resources_spent: dict[str, dict[str, SummaryMetric]] = {}
    for actor_id, resource_map in resources_all.items():
        per_actor_resources_spent[actor_id] = {
            resource_name: _metric(values) for resource_name, values in resource_map.items()
        }

    per_actor_downed = {
        actor_id: _metric([trial.downed_counts.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_deaths = {
        actor_id: _metric([trial.death_counts.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_remaining_hp = {
        actor_id: _metric([trial.remaining_hp.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }

    summary = SimulationSummary(
        run_id=run_id,
        scenario_id=scenario.config.scenario_id,
        trials=trials,
        party_win_rate=party_wins / trials,
        enemy_win_rate=enemy_wins / trials,
        rounds=_metric([trial.rounds for trial in trial_results]),
        per_actor_damage_taken=per_actor_damage_taken,
        per_actor_damage_dealt=per_actor_damage_dealt,
        per_actor_resources_spent=per_actor_resources_spent,
        per_actor_downed=per_actor_downed,
        per_actor_deaths=per_actor_deaths,
        per_actor_remaining_hp=per_actor_remaining_hp,
    )

    return SimulationArtifacts(
        trial_results=trial_results,
        trial_rows=trial_rows,
        summary=summary,
    )
