"""Behavioral proof for the complete Lantern Below adventure."""

from __future__ import annotations

import copy

import pytest

from dnd_sim.adventure import AdventureDriver, create_initial_state
from dnd_sim.interactive import EngineSession, EngineSessionError, SessionCommand
from dnd_sim.interactive.dnd_contracts import TurnDeclarationPayload
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.vtt.scene import SquareGridScene


def session(seed: int = 13) -> EngineSession:
    return EngineSession("lantern-test", create_initial_state(), AdventureDriver(), seed=seed)


def choose(game: EngineSession, choice_id: str) -> SessionCommand:
    command = SessionCommand(
        command_id=f"choice-{game.revision}-{choice_id}",
        session_id=game.session_id,
        expected_revision=game.revision,
        mode="commit",
        kind="adventure.choose.v1",
        version_pins=game.version_pins,
        payload={"choice_id": choice_id},
    )
    game.execute(command)
    return command


def finish_combat(game: EngineSession) -> list[SessionCommand]:
    commands = []
    for _ in range(120):
        if game.projection["phase"] != "combat":
            return commands
        state = AdventureDriver().decode_state(game.state)
        prompt = state.encounter.turn.prompt
        assert prompt.actor_id in {"mara", "iven", "sela"}
        action_name = {"mara": "Harbor javelin", "iven": "Shortbow", "sela": "Radiant spark"}[
            prompt.actor_id
        ]
        option = next(
            option
            for option in game.projection["combat"]["choices"]["actions"]
            if option["action_name"] == action_name
        )
        target = min(
            option["legal_target_ids"],
            key=lambda actor_id: game.projection["combat"]["actors"][actor_id]["hp"],
        )
        declaration = TurnDeclaration(
            action=DeclaredAction(action_name=action_name, targets=[TargetRef(actor_id=target)])
        )
        command = SessionCommand(
            command_id=f"turn-{game.revision}",
            session_id=game.session_id,
            expected_revision=game.revision,
            actor_id=prompt.actor_id,
            mode="commit",
            kind="dnd.declare_turn.v1",
            version_pins=game.version_pins,
            payload=TurnDeclarationPayload.from_domain(declaration or TurnDeclaration()).model_dump(
                mode="json"
            ),
        )
        game.execute(command)
        commands.append(command)
    pytest.fail("Combat did not terminate within its round bound")


def peaceful_archive(game: EngineSession) -> list[SessionCommand]:
    return [
        choose(game, choice)
        for choice in ("enter_hall", "listen_orin", "offer_help", "enter_archive")
    ]


def test_initial_view_has_a_scene_party_and_only_server_owned_choices() -> None:
    game = session()
    view = game.projection
    assert view["title"] == "The Lantern Below"
    assert view["phase"] == "exploration"
    assert view["location"]["id"] == "landing"
    assert [entry["id"] for entry in view["choices"]] == ["enter_hall"]
    assert len(view["party"]) == 3
    assert view["combat"] is None
    SquareGridScene.model_validate(view["scene"])


@pytest.mark.parametrize("ending", ["restore_beacon", "release_spirit"])
def test_peaceful_route_reaches_both_endings_with_persistent_choices(ending: str) -> None:
    game = session()
    peaceful_archive(game)
    choose(game, "search_archive")
    choose(game, "force_chest")
    choose(game, "take_supplies")
    choose(game, "enter_stair")
    choose(game, "short_rest")
    choose(game, "enter_beacon")
    assert game.state["party"] == {}
    assert game.projection["combat"]["active_actor_id"] in {"mara", "iven", "sela"}
    finish_combat(game)
    assert game.projection["phase"] == "exploration"
    choose(game, ending)
    assert game.projection["phase"] == "complete"
    assert game.projection["ending"]["title"]
    assert "keeper_helped" in game.state["flags"]
    assert "supplies_taken" in game.state["flags"]
    assert game.state["encounter"] is None
    assert len(game.state["party"]) == 3


def test_hostile_route_carries_health_and_resources_to_second_encounter() -> None:
    game = session()
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    finish_combat(game)
    assert game.projection["phase"] == "exploration"
    assert "wardens_defeated" in game.state["flags"]
    before = {actor["actor_id"]: actor["hp"] for actor in game.projection["party"]}
    choose(game, "enter_archive")
    choose(game, "enter_stair")
    choose(game, "enter_beacon")
    assert {actor["actor_id"]: actor["hp"] for actor in game.projection["party"]} == before
    finish_combat(game)
    assert game.projection["phase"] == "exploration"
    choose(game, "release_spirit")
    assert game.projection["phase"] == "complete"


def test_mid_combat_restore_and_full_replay_preserve_the_shared_rng() -> None:
    game = session()
    commands = peaceful_archive(game)
    commands += [choose(game, "enter_stair"), choose(game, "enter_beacon")]
    restored = EngineSession.restore(game.snapshot(), AdventureDriver())
    combat_commands = finish_combat(game)
    for command in combat_commands:
        restored.execute(command)
    assert restored.snapshot_json() == game.snapshot_json()
    replay = EngineSession.replay(
        session_id=game.session_id,
        initial_state=create_initial_state(),
        driver=AdventureDriver(),
        seed=13,
        commands=commands + combat_commands,
    )
    assert replay.snapshot_json() == game.snapshot_json()


def test_illegal_choices_duplicate_loot_and_preview_roll_back() -> None:
    game = session()
    before = game.snapshot_json()
    with pytest.raises(EngineSessionError):
        choose(game, "restore_beacon")
    assert game.snapshot_json() == before
    command = SessionCommand(
        command_id="preview",
        session_id=game.session_id,
        expected_revision=0,
        mode="preview",
        kind="adventure.choose.v1",
        version_pins=game.version_pins,
        payload={"choice_id": "enter_hall"},
    )
    with pytest.raises(EngineSessionError, match="preview"):
        game.execute(command)
    assert game.snapshot_json() == before
    peaceful_archive(game)
    choose(game, "force_chest")
    choose(game, "take_supplies")
    before = game.snapshot_json()
    with pytest.raises(EngineSessionError):
        choose(game, "take_supplies")
    assert game.snapshot_json() == before
    choose(game, "enter_stair")
    choose(game, "short_rest")
    with pytest.raises(EngineSessionError):
        choose(game, "short_rest")


def test_state_codec_rejects_unknown_fields_versions_and_duplicate_party_owners() -> None:
    driver = AdventureDriver()
    state = dict(driver.encode_state(create_initial_state()))
    assert driver.encode_state(driver.decode_state(state)) == state
    for invalid in (
        {**state, "unexpected": 1},
        {**state, "content_version": "unknown"},
        {**state, "supplies": 999},
    ):
        with pytest.raises(ValueError):
            driver.decode_state(invalid)
    game = session()
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    malformed = copy.deepcopy(game.state)
    malformed["party"] = state["party"]
    with pytest.raises(ValueError, match="party"):
        driver.decode_state(malformed)


def test_dead_scout_cannot_disarm_or_pick_a_lock() -> None:
    initial = create_initial_state()
    initial.party["iven"].hp = 0
    initial.party["iven"].dead = True
    game = EngineSession("lantern-test", initial, AdventureDriver(), seed=1)
    peaceful_archive(game)
    choose(game, "search_archive")
    assert not {"disarm_trap", "pick_lock"} & {
        choice["id"] for choice in game.projection["choices"]
    }
    with pytest.raises(EngineSessionError):
        choose(game, "disarm_trap")


def declare(
    game: EngineSession,
    action: str | None = None,
    target: str | None = None,
    *,
    actor_id: str | None = None,
    movement: list | None = None,
) -> SessionCommand:
    command = SessionCommand(
        command_id=f"manual-{game.revision}",
        session_id=game.session_id,
        expected_revision=game.revision,
        actor_id=actor_id or game.projection["combat"]["active_actor_id"],
        mode="commit",
        kind="dnd.declare_turn.v1",
        version_pins=game.version_pins,
        payload=TurnDeclarationPayload.from_domain(
            TurnDeclaration(
                movement_path=movement or [],
                action=(
                    DeclaredAction(
                        action_name=action, targets=[TargetRef(actor_id=target)] if target else []
                    )
                    if action
                    else None
                ),
            )
        ).model_dump(mode="json"),
    )
    game.execute(command)
    return command


def test_failed_persuasion_keeps_a_guaranteed_peaceful_route() -> None:
    game = session(seed=1)
    choose(game, "enter_hall")
    choose(game, "persuade_orin")
    check = next(event for event in game.events if event.kind == "adventure.check.resolved")
    assert check.payload == {
        "check": "persuasion",
        "face": 5,
        "modifier": 4,
        "dc": 13,
        "success": False,
    }
    choose(game, "listen_orin")
    choose(game, "offer_help")
    choose(game, "enter_archive")
    assert game.projection["location"]["id"] == "archive"
    assert not any(event.kind == "dnd.encounter.started" for event in game.events)


def test_failed_disarm_spends_the_trap_and_supplies_heal_only_the_chosen_companion() -> None:
    game = session(seed=1)
    peaceful_archive(game)
    choose(game, "search_archive")
    choose(game, "disarm_trap")
    assert "trap_sprung" in game.state["flags"]
    assert game.state["party"]["iven"]["hp"] == 19
    choose(game, "force_chest")
    assert game.state["party"]["mara"]["hp"] == 32
    choose(game, "take_supplies")
    choose(game, "heal_iven")
    assert game.state["party"]["iven"]["hp"] == 26
    assert game.state["supplies"] == 1
    assert "heal_iven" not in {option["id"] for option in game.projection["choices"]}
    with pytest.raises(EngineSessionError):
        choose(game, "heal_mara")


def test_failed_lock_can_be_forced_and_a_successfully_disarmed_trap_stays_safe() -> None:
    game = session(seed=5)
    peaceful_archive(game)
    choose(game, "search_archive")
    choose(game, "disarm_trap")
    assert "trap_disarmed" in game.state["flags"]
    choose(game, "force_chest")
    assert all(actor["hp"] == actor["max_hp"] for actor in game.state["party"].values())
    failed = session(seed=1)
    peaceful_archive(failed)
    choose(failed, "pick_lock")
    assert "chest_open" not in failed.state["flags"]
    assert "pick_lock" not in {option["id"] for option in failed.projection["choices"]}
    choose(failed, "force_chest")
    assert "chest_open" in failed.state["flags"]


def test_combat_healing_and_limited_attacks_use_shared_resources_and_persist() -> None:
    initial = create_initial_state()
    initial.party["mara"].hp = 15
    game = EngineSession("lantern-test", initial, AdventureDriver(), seed=13)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    declare(game)
    declare(game, "Focused shot", "warden_1")
    assert game.state["encounter"]["turn"]["actors"]["iven"]["resources"]["focus"] == 1
    declare(game, "Mending light", "mara")
    actors = game.state["encounter"]["turn"]["actors"]
    assert actors["sela"]["resources"]["light"] == 2
    assert actors["mara"]["hp"] > 15
    finish_combat(game)
    assert game.state["party"]["sela"]["resources"]["light"] == 2
    assert game.state["party"]["iven"]["resources"]["focus"] == 1
    choose(game, "enter_archive")
    choose(game, "enter_stair")
    choose(game, "short_rest")
    assert game.state["party"]["iven"]["resources"]["focus"] == 2
    assert game.state["party"]["sela"]["resources"]["light"] == 2
    choose(game, "enter_beacon")
    assert game.state["encounter"]["turn"]["actors"]["sela"]["resources"]["light"] == 2


def test_passive_party_can_lose_and_explicit_restart_preserves_session_history() -> None:
    game = session(seed=1)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    for _ in range(90):
        if game.projection["phase"] != "combat":
            break
        declare(game)
    assert game.projection["phase"] == "defeat"
    assert [item["id"] for item in game.projection["choices"]] == ["restart"]
    before_revision = game.revision
    before_events = len(game.events)
    choose(game, "restart")
    assert game.revision == before_revision + 1
    assert len(game.events) > before_events
    assert game.state["run_number"] == 2
    assert game.projection["location"]["id"] == "landing"
    assert all(actor["hp"] == actor["max_hp"] for actor in game.projection["party"])


def test_noncurrent_dead_and_enemy_actors_cannot_submit_turns_and_movement_is_bounded() -> None:
    game = session()
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    before = game.snapshot_json()
    for actor_id in ("iven", "warden_1", "missing"):
        with pytest.raises(EngineSessionError):
            declare(game, actor_id=actor_id)
    for position in ((100.0, 10.0, 0.0), (10.0, 10.0, 5.0), (-1.0, 0.0, 0.0)):
        with pytest.raises(EngineSessionError):
            declare(game, movement=[(12.5, 17.5, 0.0), position])
    assert game.snapshot_json() == before


def test_last_conscious_companion_downed_by_trap_has_an_explicit_recovery_path() -> None:
    initial = create_initial_state()
    initial.party["mara"].hp = 1
    for actor_id in ("iven", "sela"):
        initial.party[actor_id].hp = 0
        initial.party[actor_id].dead = True
    game = EngineSession("lantern-test", initial, AdventureDriver(), seed=13)
    peaceful_archive(game)
    choose(game, "force_chest")
    assert game.projection["phase"] == "defeat"
    choose(game, "restart")
    assert game.projection["phase"] == "exploration"


def test_enemy_chases_after_a_party_retreat_and_combat_journal_reports_actual_damage() -> None:
    game = session(seed=13)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    declare(game, "Harbor javelin", "warden_1", movement=[(12.5, 17.5, 0.0), (0.0, 17.5, 0.0)])
    assert any("6 piercing damage" in entry["text"] for entry in game.projection["journal"])
    declare(game, movement=[(7.5, 12.5, 0.0), (0.0, 12.5, 0.0)])
    declare(game, movement=[(7.5, 22.5, 0.0), (0.0, 22.5, 0.0)])
    actors = game.projection["combat"]["actors"]
    assert actors["warden_1"]["position"][0] < 37.5
    assert actors["warden_2"]["position"][0] < 37.5
    assert any("advances" in entry["text"] for entry in game.projection["journal"])


def test_dead_companion_is_skipped_and_cannot_submit_a_combat_turn() -> None:
    initial = create_initial_state()
    initial.party["mara"].hp = 0
    initial.party["mara"].dead = True
    game = EngineSession("lantern-test", initial, AdventureDriver(), seed=13)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    assert game.projection["combat"]["active_actor_id"] == "iven"
    before = game.snapshot_json()
    with pytest.raises(EngineSessionError):
        declare(game, "Harbor javelin", "warden_1", actor_id="mara")
    assert game.snapshot_json() == before


def test_sela_can_revive_a_downed_companion_during_combat() -> None:
    initial = create_initial_state()
    initial.party["iven"].hp = 0
    initial.party["iven"].stable = True
    initial.party["iven"].update_manual_conditions({"unconscious", "incapacitated", "prone"})
    game = EngineSession("lantern-test", initial, AdventureDriver(), seed=13)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    declare(game)
    assert game.projection["combat"]["active_actor_id"] == "sela"
    healing_choice = next(
        option
        for option in game.projection["combat"]["choices"]["actions"]
        if option["action_name"] == "Mending light"
    )
    assert "iven" in healing_choice["legal_target_ids"]
    declare(game, "Mending light", "iven")
    actor = game.projection["combat"]["actors"]["iven"]
    assert actor["hp"] > 0
    assert "unconscious" not in actor["conditions"]


def test_selas_radiant_spark_reports_radiant_damage_in_the_combat_journal() -> None:
    game = session(seed=13)
    choose(game, "enter_hall")
    choose(game, "threaten_orin")
    declare(game)
    declare(game)
    declare(game, "Radiant spark", "warden_1")
    recap = game.projection["journal"][-1]
    assert recap["id"].startswith("combat_")
    assert "Sela Ash deals 6 radiant damage to Brass Warden." in recap["text"]


@pytest.mark.parametrize(
    "update", [{"location": "archive"}, {"location": "return"}, {"flags": ["supplies_taken"]}]
)
def test_codec_rejects_impossible_story_checkpoints(update: dict) -> None:
    driver = AdventureDriver()
    payload = dict(driver.encode_state(create_initial_state()))
    payload.update(update)
    with pytest.raises(ValueError):
        driver.decode_state(payload)
