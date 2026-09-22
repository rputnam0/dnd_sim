from __future__ import annotations

from dnd_sim.roll_journal import (
    D20Adjustment,
    D20Resolution,
    D20RollFact,
    DamageAdjustment,
    DamageRollFact,
    DieFace,
    HealingRollFact,
    ModifierDieFace,
    RollAudienceIntent,
    RollJournal,
    RollRecordDraft,
)
from dnd_sim.vtt.participants import PARTICIPANT_SCHEMA_VERSION, TableParticipant
from dnd_sim.vtt.roll_cards import project_roll_card


def _participant(
    participant_id: str,
    *,
    role: str = "player",
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def _damage_record(*, applied_damage: int | None = 4, visibility: str = "public"):
    adjustments = (
        (
            DamageAdjustment(
                stage="applied",
                kind="resistance",
                amount=-4,
                source_id="secret:fiend-resistance",
            ),
        )
        if applied_damage == 4
        else ()
    )
    draft = RollRecordDraft(
        source_actor_id="hero",
        target_actor_id="hidden-fiend",
        action_id="action:Sun Blade",
        purpose="damage",
        audience=RollAudienceIntent(
            visibility=visibility,
            actor_ids=("hero",) if visibility == "actors" else (),
        ),
        fact=DamageRollFact(
            kind="damage",
            expression="1d8",
            damage_type="radiant",
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
            applied_damage=applied_damage,
            critical=False,
            adjustments=adjustments,
        ),
    )
    return RollJournal.empty("1:hero").append(draft).records[0]


def test_projects_final_card_without_engine_audience_or_adjustment_source() -> None:
    card = project_roll_card(
        _damage_record(),
        participant=_participant("owner", owned_actor_ids=("hero",)),
        hidden_actor_values=frozenset({"hidden-fiend"}),
    )

    assert card is not None
    assert card.source_actor_id == "hero"
    assert card.target_actor_id is None
    assert card.action_id == "action:Sun Blade"
    assert card.fact.applied_damage == 4
    assert card.fact.adjustments[0].kind == "resistance"
    encoded = card.model_dump_json()
    assert "secret:fiend-resistance" not in encoded
    assert "hidden-fiend" not in encoded
    assert "audience" not in encoded
    assert "turn_token" not in encoded


def test_actor_private_and_gm_only_records_are_absent_for_unauthorized_viewers() -> None:
    other = _participant("other", owned_actor_ids=("other-actor",))
    actor_private = _damage_record(visibility="actors")
    gm_only = actor_private.model_copy(
        update={"audience": RollAudienceIntent(visibility="gm_only", actor_ids=())}
    )

    assert project_roll_card(actor_private, participant=other) is None
    assert project_roll_card(gm_only, participant=other) is None
    assert (
        project_roll_card(
            gm_only,
            participant=_participant("gm", role="gm"),
        )
        is not None
    )


def test_unfinalized_damage_boundary_is_never_projected_as_a_card() -> None:
    assert (
        project_roll_card(
            _damage_record(applied_damage=None),
            participant=_participant("gm", role="gm"),
        )
        is None
    )


def test_d20_card_keeps_authoritative_candidates_and_outcome() -> None:
    record = (
        RollJournal.empty("1:hero")
        .append(
            RollRecordDraft(
                source_actor_id="hero",
                target_actor_id="fiend",
                action_id="action:Strike",
                purpose="attack",
                audience=RollAudienceIntent(visibility="public", actor_ids=()),
                fact=D20RollFact(
                    kind="d20",
                    roll=D20Resolution(
                        expression="2d20kh1+5",
                        mode="advantage",
                        faces=(
                            DieFace(
                                generation_index=1,
                                sides=20,
                                value=7,
                                status="discarded",
                                replacement_generation_index=None,
                            ),
                            DieFace(
                                generation_index=2,
                                sides=20,
                                value=18,
                                status="kept",
                                replacement_generation_index=None,
                            ),
                        ),
                        candidate_generation_indices=(1, 2),
                        kept_generation_index=2,
                        flat_modifier=5,
                        total=23,
                    ),
                    threshold=15,
                    outcome="hit",
                    critical=False,
                    adjustments=(
                        D20Adjustment(
                            stage="total",
                            kind="bardic_inspiration",
                            amount=3,
                            generated_face=ModifierDieFace(
                                generation_index=1,
                                sides=6,
                                value=3,
                            ),
                        ),
                    ),
                ),
            )
        )
        .records[0]
    )

    card = project_roll_card(record, participant=_participant("spectator", role="spectator"))

    assert card is not None
    assert card.fact.kind == "d20"
    assert [face.value for face in card.fact.faces] == [7, 18]
    assert card.fact.total == 26
    assert card.fact.outcome == "hit"
    assert card.fact.adjustments[0].generated_face.value == 3


def test_healing_card_keeps_effective_recovery_and_overheal() -> None:
    record = (
        RollJournal.empty("1:cleric")
        .append(
            RollRecordDraft(
                source_actor_id="cleric",
                target_actor_id="fighter",
                action_id="action:healing_word",
                purpose="healing",
                audience=RollAudienceIntent(visibility="public", actor_ids=()),
                fact=HealingRollFact(
                    kind="healing",
                    expression="1d4+3",
                    faces=(
                        DieFace(
                            generation_index=1,
                            sides=4,
                            value=4,
                            status="kept",
                            replacement_generation_index=None,
                        ),
                    ),
                    flat_modifier=3,
                    rolled_healing=7,
                    effective_healing=2,
                    overheal=5,
                ),
            )
        )
        .records[0]
    )

    card = project_roll_card(record, participant=_participant("spectator", role="spectator"))

    assert card is not None
    assert card.fact.kind == "healing"
    assert card.fact.rolled_healing == 7
    assert card.fact.effective_healing == 2
    assert card.fact.overheal == 5
