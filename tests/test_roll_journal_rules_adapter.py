from __future__ import annotations

import random

import pytest

from dnd_sim.roll_journal import (
    BoundRollJournalRecorder,
    D20RollFact,
    EngineRollJournalRecorder,
    RollAudienceIntent,
    RollJournal,
    RollRecordContext,
    decode_roll_journal,
    encode_roll_journal,
)
from dnd_sim.rules_2014 import attack_roll


class _ScriptedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)
        self.calls = 0

    def randint(self, low: int, high: int) -> int:
        assert (low, high) == (1, 20)
        self.calls += 1
        return self.values.pop(0)


def _bound_attack_recorder(
    *, turn_token: str = "2:fighter"
) -> tuple[EngineRollJournalRecorder, BoundRollJournalRecorder]:
    recorder = EngineRollJournalRecorder.empty(turn_token)
    bound = recorder.bind(
        RollRecordContext(
            source_actor_id="fighter",
            target_actor_id="goblin",
            action_id="action:longsword",
            purpose="base_attack_roll",
            audience=RollAudienceIntent(visibility="public", actor_ids=()),
        )
    )
    return recorder, bound


@pytest.mark.parametrize(
    "advantage,disadvantage",
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_recording_attack_roll_preserves_result_rng_state_and_draw_count(
    advantage: bool,
    disadvantage: bool,
) -> None:
    for seed in range(40):
        plain_rng = random.Random(seed)
        recorded_rng = random.Random(seed)
        recorder, bound = _bound_attack_recorder(turn_token=f"turn:{seed}")

        plain = attack_roll(
            plain_rng,
            to_hit=5,
            target_ac=15,
            advantage=advantage,
            disadvantage=disadvantage,
        )
        recorded = attack_roll(
            recorded_rng,
            to_hit=5,
            target_ac=15,
            advantage=advantage,
            disadvantage=disadvantage,
            journal_recorder=bound,
        )

        assert recorded == plain
        assert recorded_rng.getstate() == plain_rng.getstate()
        assert len(recorder.journal.records) == 1


@pytest.mark.parametrize(
    "values,advantage,disadvantage,mode,kept,expression,statuses,calls",
    [
        ([11], False, False, "normal", 1, "1d20+5", ["kept"], 1),
        (
            [7, 16],
            True,
            False,
            "advantage",
            2,
            "2d20kh1+5",
            ["discarded", "kept"],
            2,
        ),
        (
            [17, 4],
            False,
            True,
            "disadvantage",
            2,
            "2d20kl1+5",
            ["discarded", "kept"],
            2,
        ),
        ([14, 14], True, False, "advantage", 1, "2d20kh1+5", ["kept", "discarded"], 2),
        ([12], True, True, "normal", 1, "1d20+5", ["kept"], 1),
    ],
)
def test_attack_boundary_retains_generated_faces_and_selection_semantics(
    values: list[int],
    advantage: bool,
    disadvantage: bool,
    mode: str,
    kept: int,
    expression: str,
    statuses: list[str],
    calls: int,
) -> None:
    rng = _ScriptedRng(values)
    recorder, bound = _bound_attack_recorder()

    result = attack_roll(
        rng,
        to_hit=5,
        target_ac=15,
        advantage=advantage,
        disadvantage=disadvantage,
        journal_recorder=bound,
    )

    assert rng.calls == calls
    [record] = recorder.journal.records
    assert record.source_actor_id == "fighter"
    assert record.target_actor_id == "goblin"
    assert record.action_id == "action:longsword"
    assert record.purpose == "base_attack_roll"
    fact = record.fact
    assert isinstance(fact, D20RollFact)
    assert fact.roll.mode == mode
    assert fact.roll.expression == expression
    assert [face.value for face in fact.roll.faces] == values[:calls]
    assert [face.status for face in fact.roll.faces] == statuses
    assert fact.roll.kept_generation_index == kept
    assert fact.roll.total == result.total
    assert fact.threshold == 15
    assert fact.outcome == ("hit" if result.hit else "miss")
    assert fact.critical is result.crit


def test_recorder_resumes_a_replayed_journal_at_the_next_deterministic_sequence() -> None:
    recorder, bound = _bound_attack_recorder()
    attack_roll(
        _ScriptedRng([8]),
        to_hit=5,
        target_ac=15,
        journal_recorder=bound,
    )
    restored = decode_roll_journal(encode_roll_journal(recorder.journal))
    resumed = EngineRollJournalRecorder(restored)
    resumed_bound = resumed.bind(
        RollRecordContext(
            source_actor_id="fighter",
            target_actor_id="goblin-2",
            action_id="action:longsword",
            purpose="base_attack_roll",
            audience=RollAudienceIntent(
                visibility="actors",
                actor_ids=("fighter", "goblin-2"),
            ),
        )
    )

    attack_roll(
        _ScriptedRng([20]),
        to_hit=-1,
        target_ac=30,
        journal_recorder=resumed_bound,
    )

    assert [record.sequence for record in resumed.journal.records] == [1, 2]
    assert resumed.journal.records[0] == restored.records[0]
    assert resumed.journal.records[1].fact.critical is True
    assert decode_roll_journal(encode_roll_journal(resumed.journal)) == resumed.journal
    assert recorder.journal == restored


def test_recorder_requires_the_same_engine_journal_contract_it_retains() -> None:
    with pytest.raises(TypeError, match="RollJournal"):
        EngineRollJournalRecorder(object())  # type: ignore[arg-type]

    empty = RollJournal.empty("turn-1")
    recorder = EngineRollJournalRecorder(empty)
    with pytest.raises(TypeError, match="RollRecordContext"):
        recorder.bind(object())  # type: ignore[arg-type]
