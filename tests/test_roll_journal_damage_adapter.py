from __future__ import annotations

import random

import pytest

from dnd_sim.models import ActorRuntimeState
from dnd_sim.roll_journal import (
    BoundRollJournalRecorder,
    DamageRollFact,
    EngineRollJournalRecorder,
    RollAudienceIntent,
    RollRecordContext,
    decode_roll_journal,
    encode_roll_journal,
)
from dnd_sim.rules_2014 import roll_damage


class _ScriptedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)
        self.calls = 0

    def randint(self, low: int, high: int) -> int:
        assert low == 1
        assert 2 <= high <= 100
        self.calls += 1
        return self.values.pop(0)


def _bound_damage_recorder(
    *, turn_token: str = "2:fighter", damage_type: str = "slashing"
) -> tuple[EngineRollJournalRecorder, BoundRollJournalRecorder]:
    recorder = EngineRollJournalRecorder.empty(turn_token)
    bound = recorder.bind(
        RollRecordContext(
            source_actor_id="fighter",
            target_actor_id="goblin",
            action_id="action:longsword",
            purpose=f"base_{damage_type or 'untyped'}_damage_roll",
            audience=RollAudienceIntent(visibility="public", actor_ids=()),
        )
    )
    return recorder, bound


def _source_with_damage_floor(*, floor: int, damage_type: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id="fighter",
        team="party",
        name="Fighter",
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=16,
        initiative_mod=0,
        str_mod=3,
        dex_mod=1,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={},
        actions=[],
        traits={
            "Elemental Adept": {
                "mechanics": [
                    {
                        "effect_type": "damage_roll_floor",
                        "damage_type": damage_type,
                        "floor": floor,
                    }
                ]
            }
        },
    )


@pytest.mark.parametrize(
    "expr,crit,empowered_rerolls",
    [
        ("2d8+3", False, 0),
        ("2d8-20", False, 0),
        ("1d6+2", True, 0),
        ("3d10+4", False, 2),
        ("5", False, 0),
    ],
)
def test_recording_damage_preserves_result_rng_state_and_draw_order(
    expr: str,
    crit: bool,
    empowered_rerolls: int,
) -> None:
    for seed in range(40):
        plain_rng = random.Random(seed)
        recorded_rng = random.Random(seed)
        recorder, bound = _bound_damage_recorder(turn_token=f"turn:{seed}")

        plain = roll_damage(
            plain_rng,
            expr,
            crit=crit,
            empowered_rerolls=empowered_rerolls,
            damage_type="slashing",
        )
        recorded = roll_damage(
            recorded_rng,
            expr,
            crit=crit,
            empowered_rerolls=empowered_rerolls,
            damage_type="slashing",
            journal_recorder=bound,
        )

        assert recorded == plain
        assert recorded_rng.getstate() == plain_rng.getstate()
        assert len(recorder.journal.records) == 1


def test_damage_boundary_retains_initial_and_empowered_reroll_faces() -> None:
    rng = _ScriptedRng([2, 7, 6])
    recorder, bound = _bound_damage_recorder()

    result = roll_damage(
        rng,
        "2d8+3",
        empowered_rerolls=1,
        damage_type="slashing",
        journal_recorder=bound,
    )

    assert result == 16
    assert rng.calls == 3
    [record] = recorder.journal.records
    fact = record.fact
    assert isinstance(fact, DamageRollFact)
    assert fact.expression == "2d8+3"
    assert fact.damage_type == "slashing"
    assert fact.flat_modifier == 3
    assert [face.value for face in fact.faces] == [2, 7, 6]
    assert [face.status for face in fact.faces] == ["rerolled", "kept", "kept"]
    assert fact.faces[0].replacement_generation_index == 3
    assert fact.rolled_total == 16
    assert fact.raw_damage == 16
    assert fact.applied_damage is None
    assert fact.adjustments == ()


def test_damage_boundary_retains_floor_and_minimum_zero_as_raw_adjustments() -> None:
    source = _source_with_damage_floor(floor=3, damage_type="fire")
    recorder, bound = _bound_damage_recorder(damage_type="fire")

    floored = roll_damage(
        _ScriptedRng([1, 2]),
        "2d6-5",
        source=source,
        damage_type="fire",
        journal_recorder=bound,
    )
    clamped = roll_damage(
        _ScriptedRng([2]),
        "1d4-10",
        damage_type="fire",
        journal_recorder=bound,
    )

    assert (floored, clamped) == (1, 0)
    floor_fact = recorder.journal.records[0].fact
    clamp_fact = recorder.journal.records[1].fact
    assert isinstance(floor_fact, DamageRollFact)
    assert floor_fact.rolled_total == -2
    assert floor_fact.raw_damage == 1
    assert [(item.kind, item.amount, item.source_id) for item in floor_fact.adjustments] == [
        ("floor", 3, "trait:elemental adept:damage-floor:3")
    ]
    assert isinstance(clamp_fact, DamageRollFact)
    assert clamp_fact.rolled_total == -8
    assert clamp_fact.raw_damage == 0
    assert [(item.kind, item.amount, item.source_id) for item in clamp_fact.adjustments] == [
        ("floor", 8, "rule:minimum-damage:0")
    ]


def test_recording_damage_floor_preserves_fixed_seed_result_and_rng_state() -> None:
    source = _source_with_damage_floor(floor=3, damage_type="fire")
    for seed in range(40):
        plain_rng = random.Random(seed)
        recorded_rng = random.Random(seed)
        recorder, bound = _bound_damage_recorder(turn_token=f"floor:{seed}", damage_type="fire")

        plain = roll_damage(
            plain_rng,
            "4d6-3",
            empowered_rerolls=2,
            source=source,
            damage_type="fire",
        )
        recorded = roll_damage(
            recorded_rng,
            "4d6-3",
            empowered_rerolls=2,
            source=source,
            damage_type="fire",
            journal_recorder=bound,
        )

        assert recorded == plain
        assert recorded_rng.getstate() == plain_rng.getstate()
        assert recorder.journal.records[0].fact.raw_damage == recorded


def test_untyped_static_damage_is_explicit_and_codec_replayable() -> None:
    recorder, bound = _bound_damage_recorder(damage_type="")

    result = roll_damage(
        _ScriptedRng([]),
        " 5 ",
        journal_recorder=bound,
    )
    restored = decode_roll_journal(encode_roll_journal(recorder.journal))

    assert result == 5
    fact = restored.records[0].fact
    assert isinstance(fact, DamageRollFact)
    assert fact.expression == "5"
    assert fact.damage_type is None
    assert fact.faces == ()
    assert fact.flat_modifier == 5
    assert fact.rolled_total == 5
    assert fact.raw_damage == 5
    assert fact.applied_damage is None


def test_invalid_damage_recorder_is_rejected_before_parsing_or_rng() -> None:
    rng = _ScriptedRng([4])

    with pytest.raises(TypeError, match="BoundRollJournalRecorder"):
        roll_damage(
            rng,
            "1d6",
            journal_recorder=object(),  # type: ignore[arg-type]
        )

    assert rng.calls == 0
