"""Original, versioned content for the Lantern Below adventure."""

from dnd_sim.models import ActionDefinition, ActorRuntimeState

CONTENT_VERSION = "the-lantern-below@1.0.0"
PARTY_IDS = ("mara", "iven", "sela")
PARTY_POSITIONS = ((12.5, 17.5, 0.0), (7.5, 12.5, 0.0), (7.5, 22.5, 0.0))

LOCATIONS = {
    "landing": (
        "Lantern Landing",
        "Rain erases the horizon. Above you, the town's great beacon blinks once, then fails. "
        "Fishing boats are still at sea. Keeper Orin has barred the stair beneath the tower. "
        "Mara Vale, a harbor guard; Iven Reed, a locksmith; and Sela Ash, a wandering healer, "
        "have one tide to discover what is happening below. You control all three companions.",
    ),
    "hall": (
        "Keeper's Hall",
        "Two brass wardens stand beside a salt-stained desk. Orin holds a lantern whose flame "
        "casts a human shadow. 'The light is frightened,' he says. 'If you force your way down, "
        "you will only teach it to fear us more.' Beyond him, water trickles into an old archive.",
    ),
    "archive": (
        "Flooded Archive",
        "Tidewater laps at shelves of voyage logs. A locked supply chest bears a silver sun; "
        "fine scratches surround its latch. Beneath a fallen shelf lies the keeper's earliest "
        "account of the beacon. The sheltered stair beyond offers a brief place to breathe.",
    ),
    "stair": (
        "Sheltered Stair",
        "A dry alcove overlooks the beacon chamber. Through the stone comes a voice: "
        "'I have carried them home for a hundred years. Who will carry me?' Mara checks her "
        "blade. Iven counts the boats outside. Sela listens. You have time for one short rest.",
    ),
    "beacon": (
        "Beacon Chamber",
        "A hollow figure turns inside the lantern's shattered lens. Its attendant drags chains "
        "across the floor. The frightened spirit cannot hear you through the broken ward. "
        "Quiet the Hollow Lantern, then decide what the town owes the light that saved it.",
    ),
    "return": (
        "The Morning Tide",
        "The tide recedes from Lantern Landing. Your companions climb into the morning, "
        "carrying the consequences of the choice made beneath the tower.",
    ),
}

CHOICES = {
    "enter_hall": (
        "Enter the keeper's hall",
        "Meet Orin and discover why the beacon has gone dark.",
    ),
    "listen_orin": (
        "Listen to Orin",
        "Let the keeper explain his fear before deciding what to do.",
    ),
    "ask_beacon": ("Ask who lives in the flame", "Learn why the wardens protect this place."),
    "offer_help": (
        "Offer to mend the broken ward",
        "Promise to hear the spirit; Orin will stand aside without a fight.",
    ),
    "persuade_orin": (
        "Ask Orin to trust you immediately",
        "Sela attempts a DC 13 persuasion check (+4). Failure still leaves listening open.",
    ),
    "threaten_orin": (
        "Order the wardens aside",
        "Force the passage. Orin retreats and two brass wardens attack.",
    ),
    "enter_archive": (
        "Descend into the flooded archive",
        "Search for the keeper's account and emergency supplies.",
    ),
    "search_archive": (
        "Search the shelves and chest",
        "Iven spots a needle trap and finds the keeper's account; no roll required.",
    ),
    "read_account": (
        "Read the first keeper's account",
        "Discover the promise made to the spirit a century ago.",
    ),
    "disarm_trap": (
        "Disarm the needle trap",
        "Iven attempts DC 12 with +5. Failure springs it for 1d6 + 2 damage.",
    ),
    "pick_lock": (
        "Pick the chest lock",
        "Iven attempts DC 12 with +5. You can force it open if the check fails.",
    ),
    "force_chest": (
        "Force the supply chest open",
        "Mara opens the lock. An armed needle trap deals 1d6 + 2 damage.",
    ),
    "take_supplies": (
        "Take the silver key and supplies",
        "Collect two healing draughts and a key that weakens the final ward.",
    ),
    "enter_stair": (
        "Continue to the sheltered stair",
        "Leave the archive and prepare for the final chamber.",
    ),
    "return_archive": (
        "Return to the archive",
        "Recover anything you left behind before facing the lantern.",
    ),
    "short_rest": (
        "Take your one short rest",
        "Each living companion recovers 1d8 + 3 HP. Mara's resolve and Iven's focus return.",
    ),
    "enter_beacon": (
        "Enter the beacon chamber",
        "Face the Hollow Lantern and its attendant. Prepare healing supplies first.",
    ),
    "restore_beacon": (
        "Restore the beacon",
        "Keep the spirit bound until the boats return; promise a new, unbound light for the town.",
    ),
    "release_spirit": (
        "Release the bound spirit",
        "Honor its freedom now. The town must guide its boats with ordinary harbor fires.",
    ),
    "restart": (
        "Begin a new adventure",
        "Start again with a fresh party. This run's decisions remain in session history.",
    ),
}


def _attack(
    name: str,
    *,
    damage: str,
    to_hit: int = 6,
    ranged: bool = False,
    resource: str | None = None,
    damage_type: str | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        to_hit=to_hit,
        damage=damage,
        damage_type=damage_type or ("piercing" if ranged else "slashing"),
        reach_ft=None if ranged else 5,
        range_normal_ft=50 if ranged else None,
        range_long_ft=60 if ranged else None,
        resource_cost={resource: 1} if resource else {},
    )


def _actor(
    actor_id: str,
    name: str,
    hp: int,
    ac: int,
    actions: list[ActionDefinition],
    *,
    team: str = "party",
    resources: dict[str, int] | None = None,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=name,
        max_hp=hp,
        hp=hp,
        temp_hp=0,
        ac=ac,
        initiative_mod=2,
        str_mod=2,
        dex_mod=3,
        con_mod=2,
        int_mod=1,
        wis_mod=3,
        cha_mod=2,
        save_mods={"str": 2, "dex": 3, "con": 2, "int": 1, "wis": 3, "cha": 2},
        actions=actions,
        resources=dict(resources or {}),
        max_resources=dict(resources or {}),
        uses_death_saves=team == "party",
        level=3,
        creature_type="humanoid" if team == "party" else "construct",
    )


def create_party() -> dict[str, ActorRuntimeState]:
    """Create the bounded companion ability set supported by this adventure."""
    mara = _actor(
        "mara",
        "Mara Vale · Harbor Guard",
        32,
        16,
        [
            _attack("Guard's blade", damage="1d8+4"),
            _attack("Driving strike", damage="2d8+4", resource="resolve"),
            _attack("Harbor javelin", damage="1d6+3", ranged=True),
            ActionDefinition(
                name="Second wind",
                action_type="utility",
                action_cost="bonus",
                target_mode="self",
                resource_cost={"second_wind": 1},
                effects=[{"effect_type": "heal", "amount": "1d10+3", "target": "source"}],
            ),
        ],
        resources={"resolve": 2, "second_wind": 1},
    )
    iven = _actor(
        "iven",
        "Iven Reed · Locksmith",
        26,
        15,
        [
            _attack("Shortbow", damage="1d6+4", ranged=True),
            _attack("Focused shot", damage="2d6+4", ranged=True, resource="focus"),
        ],
        resources={"focus": 2},
    )
    sela = _actor(
        "sela",
        "Sela Ash · Lantern Healer",
        28,
        15,
        [
            _attack("Radiant spark", damage="1d6+3", ranged=True, damage_type="radiant"),
            ActionDefinition(
                name="Mending light",
                action_type="utility",
                action_cost="action",
                target_mode="single_ally",
                range_ft=40,
                resource_cost={"light": 1},
                effects=[{"effect_type": "heal", "amount": "2d6+4", "target": "target"}],
            ),
        ],
        resources={"light": 3},
    )
    party = {actor.actor_id: actor for actor in (mara, iven, sela)}
    for actor_id, position in zip(PARTY_IDS, PARTY_POSITIONS):
        party[actor_id].position = position
    return party


def create_enemies(encounter_id: str, *, silver_key: bool) -> dict[str, ActorRuntimeState]:
    if encounter_id == "wardens":
        enemies = [
            _actor(
                "warden_1",
                "Brass Warden",
                18,
                12,
                [_attack("Warden's staff", damage="1d6+2", to_hit=4)],
                team="enemy",
            ),
            _actor(
                "warden_2",
                "Brass Watcher",
                18,
                12,
                [_attack("Warden's staff", damage="1d6+2", to_hit=4)],
                team="enemy",
            ),
        ]
    elif encounter_id == "lantern":
        enemies = [
            _actor(
                "hollow_lantern",
                "The Hollow Lantern",
                52,
                12 if silver_key else 14,
                [
                    _attack(
                        "Broken light", damage="1d8+2", to_hit=4, ranged=True, damage_type="radiant"
                    )
                ],
                team="enemy",
            ),
            _actor(
                "attendant",
                "Chainbound Attendant",
                18,
                12,
                [_attack("Dragging chain", damage="1d6+1", to_hit=4)],
                team="enemy",
            ),
        ]
    else:
        raise ValueError("Unknown adventure encounter")
    for actor, position in zip(enemies, ((37.5, 17.5, 0.0), (37.5, 27.5, 0.0))):
        actor.position = position
    return {actor.actor_id: actor for actor in enemies}
