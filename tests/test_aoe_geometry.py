from __future__ import annotations

import random

from dnd_sim.engine import _resolve_targets_for_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import TargetRef


def _actor(*, actor_id: str, team: str, hp: int = 30) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=hp,
        hp=hp,
        temp_hp=0,
        ac=13,
        initiative_mod=0,
        str_mod=0,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _template_action(template: str, size_ft: int) -> ActionDefinition:
    return ActionDefinition(
        name=f"{template}_template",
        action_type="save",
        save_dc=14,
        save_ability="dex",
        target_mode="single_enemy",
        aoe_type=template,
        aoe_size_ft=size_ft,
        tags=["spell"],
    )


def _ids(targets: list[ActorRuntimeState]) -> set[str]:
    return {target.actor_id for target in targets}


def test_line_template_returns_expected_cells_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")
    inline = _actor(actor_id="inline", team="enemy")
    off_axis = _actor(actor_id="off_axis", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (10.0, 0.0, 0.0)
    inline.position = (20.0, 0.0, 0.0)
    off_axis.position = (20.0, 5.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, inline, off_axis)}
    action = _template_action("line", 20)

    resolved = _resolve_targets_for_action(
        rng=random.Random(1),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert _ids(resolved) == {"primary", "inline"}


def test_cone_template_returns_expected_cells_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")
    side = _actor(actor_id="side", team="enemy")
    wide = _actor(actor_id="wide", team="enemy")
    rear = _actor(actor_id="rear", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (10.0, 0.0, 0.0)
    side.position = (10.0, 5.0, 0.0)
    wide.position = (10.0, 10.0, 0.0)
    rear.position = (-5.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, side, wide, rear)}
    action = _template_action("cone", 20)

    resolved = _resolve_targets_for_action(
        rng=random.Random(2),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert _ids(resolved) == {"primary", "side"}


def test_sphere_template_returns_expected_cells_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")
    close = _actor(actor_id="close", team="enemy")
    edge = _actor(actor_id="edge", team="enemy")
    far = _actor(actor_id="far", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)
    close.position = (25.0, 0.0, 0.0)
    edge.position = (20.0, 10.0, 0.0)
    far.position = (35.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, close, edge, far)}
    action = _template_action("sphere", 10)

    resolved = _resolve_targets_for_action(
        rng=random.Random(3),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert _ids(resolved) == {"primary", "close", "edge"}


def test_cylinder_template_returns_expected_cells_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")
    close = _actor(actor_id="close", team="enemy")
    side = _actor(actor_id="side", team="enemy")
    far = _actor(actor_id="far", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)
    close.position = (25.0, 0.0, 0.0)
    side.position = (20.0, 10.0, 0.0)
    far.position = (35.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, close, side, far)}
    action = _template_action("cylinder", 10)

    resolved = _resolve_targets_for_action(
        rng=random.Random(4),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert _ids(resolved) == {"primary", "close", "side"}


def test_cube_template_returns_expected_cells_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")
    edge = _actor(actor_id="edge", team="enemy")
    side = _actor(actor_id="side", team="enemy")
    far = _actor(actor_id="far", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)
    edge.position = (25.0, 0.0, 0.0)
    side.position = (20.0, 5.0, 0.0)
    far.position = (30.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, edge, side, far)}
    action = _template_action("cube", 10)

    resolved = _resolve_targets_for_action(
        rng=random.Random(5),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert _ids(resolved) == {"primary", "edge", "side"}


def test_origin_blocked_invalidates_sphere_cast() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary)}
    action = _template_action("sphere", 10)
    obstacles = [AABB(min_pos=(8.0, -2.0, -2.0), max_pos=(12.0, 2.0, 2.0), cover_level="TOTAL")]

    resolved = _resolve_targets_for_action(
        rng=random.Random(6),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
        obstacles=obstacles,
    )

    assert resolved == []


def test_line_path_blocked_invalidates_line_cast() -> None:
    caster = _actor(actor_id="caster", team="party")
    primary = _actor(actor_id="primary", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary)}
    action = _template_action("line", 25)
    obstacles = [AABB(min_pos=(8.0, -1.0, -2.0), max_pos=(12.0, 1.0, 2.0), cover_level="TOTAL")]

    resolved = _resolve_targets_for_action(
        rng=random.Random(7),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
        obstacles=obstacles,
    )

    assert resolved == []
