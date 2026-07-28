from __future__ import annotations

import json
import random

import pytest
from pydantic import ValidationError

from dnd_sim.roll_journal import (
    ROLL_JOURNAL_SCHEMA_VERSION,
    AuthoritativeRollRecord,
    D20Resolution,
    D20RollFact,
    DamageAdjustment,
    DamageRollFact,
    DieFace,
    RollAudienceIntent,
    RollJournal,
    RollRecordDraft,
    SavingThrowFact,
    decode_roll_journal,
    deterministic_roll_record_id,
    encode_roll_journal,
)


def _public() -> RollAudienceIntent:
    return RollAudienceIntent(visibility="public", actor_ids=())


def _d20_roll(
    *,
    values: tuple[int, ...] = (7, 16),
    mode: str = "advantage",
    kept_generation_index: int = 2,
    flat_modifier: int = 5,
) -> D20Resolution:
    faces = tuple(
        DieFace(
            generation_index=index,
            sides=20,
            value=value,
            status="kept" if index == kept_generation_index else "discarded",
            replacement_generation_index=None,
        )
        for index, value in enumerate(values, start=1)
    )
    kept_value = values[kept_generation_index - 1]
    return D20Resolution(
        expression="2d20kh1+5",
        mode=mode,
        faces=faces,
        candidate_generation_indices=tuple(range(1, len(values) + 1)),
        kept_generation_index=kept_generation_index,
        flat_modifier=flat_modifier,
        total=kept_value + flat_modifier,
    )


def _attack_draft() -> RollRecordDraft:
    return RollRecordDraft(
        source_actor_id="fighter",
        target_actor_id="goblin",
        action_id="action:longsword",
        purpose="attack",
        audience=_public(),
        fact=D20RollFact(
            kind="d20",
            roll=_d20_roll(),
            threshold=15,
            outcome="hit",
            critical=False,
        ),
    )


def _save_draft() -> RollRecordDraft:
    return RollRecordDraft(
        source_actor_id="goblin",
        target_actor_id="wizard",
        action_id="spell:fireball",
        purpose="saving_throw",
        audience=RollAudienceIntent(visibility="actors", actor_ids=("goblin", "wizard")),
        fact=SavingThrowFact(
            kind="saving_throw",
            ability="dexterity",
            roll=_d20_roll(
                values=(12,),
                mode="normal",
                kept_generation_index=1,
                flat_modifier=2,
            ),
            dc=15,
            succeeded=False,
        ),
    )


def _damage_draft() -> RollRecordDraft:
    return RollRecordDraft(
        source_actor_id="fighter",
        target_actor_id="goblin",
        action_id="action:longsword",
        purpose="damage",
        audience=_public(),
        fact=DamageRollFact(
            kind="damage",
            expression="2d8+3",
            damage_type="slashing",
            faces=(
                DieFace(
                    generation_index=1,
                    sides=8,
                    value=2,
                    status="rerolled",
                    replacement_generation_index=3,
                ),
                DieFace(
                    generation_index=2,
                    sides=8,
                    value=7,
                    status="kept",
                    replacement_generation_index=None,
                ),
                DieFace(
                    generation_index=3,
                    sides=8,
                    value=6,
                    status="kept",
                    replacement_generation_index=None,
                ),
            ),
            flat_modifier=3,
            rolled_total=16,
            raw_damage=16,
            applied_damage=8,
            critical=False,
            adjustments=(
                DamageAdjustment(
                    stage="applied",
                    kind="resistance",
                    amount=-8,
                    source_id="trait:slashing-resistance",
                ),
            ),
        ),
    )


def _unapplied_damage_draft() -> RollRecordDraft:
    return RollRecordDraft(
        source_actor_id="fighter",
        target_actor_id="goblin",
        action_id="action:longsword",
        purpose="base_damage_roll",
        audience=_public(),
        fact=DamageRollFact(
            kind="damage",
            expression="1d8+3",
            damage_type="slashing",
            faces=(
                DieFace(
                    generation_index=1,
                    sides=8,
                    value=6,
                    status="kept",
                    replacement_generation_index=None,
                ),
            ),
            flat_modifier=3,
            rolled_total=9,
            raw_damage=9,
            applied_damage=None,
            critical=False,
            adjustments=(),
        ),
    )


def test_immutable_journal_appends_deterministic_ordered_records_without_rng_draws() -> None:
    rng = random.Random(41020)
    rng_state = rng.getstate()
    empty = RollJournal.empty("turn:round-2:initiative-14")

    with_attack = empty.append(_attack_draft())
    complete = with_attack.append(_damage_draft()).append(_save_draft())

    assert rng.getstate() == rng_state
    assert empty.records == ()
    assert [record.sequence for record in complete.records] == [1, 2, 3]
    assert [record.fact.kind for record in complete.records] == [
        "d20",
        "damage",
        "saving_throw",
    ]
    assert [record.record_id for record in complete.records] == [
        deterministic_roll_record_id("turn:round-2:initiative-14", sequence)
        for sequence in (1, 2, 3)
    ]
    assert complete.records_after(1) == complete.records[1:]

    with pytest.raises(ValidationError):
        complete.records[0].sequence = 9  # type: ignore[misc]


def test_structured_facts_retain_candidates_replacements_outcomes_and_damage_stages() -> None:
    journal = (
        RollJournal.empty("turn-1")
        .append(_attack_draft())
        .append(_damage_draft())
        .append(_save_draft())
    )

    attack = journal.records[0].fact
    assert isinstance(attack, D20RollFact)
    assert [face.value for face in attack.roll.faces] == [7, 16]
    assert attack.roll.candidate_generation_indices == (1, 2)
    assert attack.roll.kept_generation_index == 2
    assert attack.total == 21
    assert attack.outcome == "hit"

    damage = journal.records[1].fact
    assert isinstance(damage, DamageRollFact)
    assert damage.faces[0].replacement_generation_index == 3
    assert damage.rolled_total == 16
    assert damage.raw_damage == 16
    assert damage.applied_damage == 8
    assert damage.adjustments[0].kind == "resistance"

    save = journal.records[2].fact
    assert isinstance(save, SavingThrowFact)
    assert save.ability == "dexterity"
    assert save.roll.total == 14
    assert save.dc == 15
    assert save.succeeded is False


def test_codec_is_canonical_byte_stable_and_round_trips_discriminated_facts() -> None:
    journal = (
        RollJournal.empty("turn-1")
        .append(_attack_draft())
        .append(_damage_draft())
        .append(_save_draft())
    )

    encoded = encode_roll_journal(journal)
    restored = decode_roll_journal(encoded)

    assert restored == journal
    assert encode_roll_journal(restored) == encoded
    assert encoded == json.dumps(
        json.loads(encoded),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert encoded.startswith('{"records":[')
    assert f'"schema_version":"{ROLL_JOURNAL_SCHEMA_VERSION}"' in encoded


def test_damage_fact_can_explicitly_retain_an_unapplied_rng_boundary() -> None:
    journal = RollJournal.empty("turn-1").append(_unapplied_damage_draft())

    restored = decode_roll_journal(encode_roll_journal(journal))

    fact = restored.records[0].fact
    assert isinstance(fact, DamageRollFact)
    assert fact.rolled_total == 9
    assert fact.raw_damage == 9
    assert fact.applied_damage is None
    assert '"applied_damage":null' in encode_roll_journal(restored)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload.pop("schema_version"), "schema_version"),
        (
            lambda payload: payload.__setitem__("schema_version", "engine.roll_journal.v0"),
            "literal",
        ),
        (lambda payload: payload.__setitem__("unexpected", True), "extra"),
        (lambda payload: payload["records"][0].pop("audience"), "audience"),
        (lambda payload: payload["records"][0].__setitem__("sequence", 2), "sequence"),
        (lambda payload: payload["records"][0].__setitem__("record_id", "forged"), "record_id"),
    ],
)
def test_codec_rejects_partial_incompatible_or_noncanonical_journals(mutate, match: str) -> None:
    payload = json.loads(encode_roll_journal(RollJournal.empty("turn-1").append(_attack_draft())))
    mutate(payload)

    with pytest.raises((ValueError, ValidationError), match=match):
        decode_roll_journal(json.dumps(payload))


def test_codec_rejects_ambiguous_duplicate_json_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON object key 'records'"):
        decode_roll_journal(
            '{"schema_version":"engine.roll_journal.v1",'
            '"turn_token":"turn-1","records":[],"records":[]}'
        )


@pytest.mark.parametrize(
    "factory,match",
    [
        (
            lambda: RollAudienceIntent(visibility="actors", actor_ids=("wizard", "fighter")),
            "sorted",
        ),
        (
            lambda: RollAudienceIntent(visibility="gm_only", actor_ids=("fighter",)),
            "must be empty",
        ),
        (
            lambda: _d20_roll(values=(18, 4), mode="advantage", kept_generation_index=2),
            "highest candidate",
        ),
        (
            lambda: D20Resolution(
                expression="1d20+5",
                mode="normal",
                faces=(
                    DieFace(
                        generation_index=1,
                        sides=20,
                        value=12,
                        status="kept",
                        replacement_generation_index=None,
                    ),
                ),
                candidate_generation_indices=(1,),
                kept_generation_index=1,
                flat_modifier=5,
                total=99,
            ),
            "total",
        ),
        (
            lambda: DieFace(
                generation_index=1,
                sides=6,
                value=7,
                status="kept",
                replacement_generation_index=None,
            ),
            "sides",
        ),
        (
            lambda: DamageRollFact(
                kind="damage",
                expression="1d8",
                damage_type="fire",
                faces=(
                    DieFace(
                        generation_index=1,
                        sides=8,
                        value=8,
                        status="kept",
                        replacement_generation_index=None,
                    ),
                ),
                flat_modifier=0,
                rolled_total=8,
                raw_damage=8,
                applied_damage=7,
                critical=False,
                adjustments=(),
            ),
            "applied_damage",
        ),
        (
            lambda: DamageRollFact(
                kind="damage",
                expression="8",
                damage_type=None,
                faces=(),
                flat_modifier=8,
                rolled_total=8,
                raw_damage=8,
                applied_damage=None,
                critical=False,
                adjustments=(
                    DamageAdjustment(
                        stage="applied",
                        kind="resistance",
                        amount=-4,
                        source_id="trait:resistance",
                    ),
                ),
            ),
            "unapplied damage",
        ),
    ],
)
def test_contracts_reject_roll_facts_that_cannot_explain_the_result(factory, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        factory()


def test_record_constructor_rejects_noncontiguous_sequence_even_with_matching_id() -> None:
    draft = _attack_draft()
    record = AuthoritativeRollRecord(
        schema_version="engine.roll_record.v1",
        record_id=deterministic_roll_record_id("turn-1", 2),
        turn_token="turn-1",
        sequence=2,
        source_actor_id=draft.source_actor_id,
        target_actor_id=draft.target_actor_id,
        action_id=draft.action_id,
        purpose=draft.purpose,
        audience=draft.audience,
        fact=draft.fact,
    )

    with pytest.raises(ValidationError, match="contiguous"):
        RollJournal(
            schema_version=ROLL_JOURNAL_SCHEMA_VERSION,
            turn_token="turn-1",
            records=(record,),
        )
