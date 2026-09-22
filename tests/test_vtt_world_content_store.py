from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.world_content_contracts import (
    MAX_ACTIVE_ACTORS,
    MAX_ACTIVE_ITEMS,
    ActorInventoryItem,
    Dnd5eAbilityScores,
    Dnd5eActionInput,
    Dnd5eActorSheet,
    Dnd5eItemData,
    Dnd5eMovementSpeeds,
    Dnd5eSenses,
    DocumentPermissions,
    DocumentProvenance,
    WorldActorDocument,
    WorldContentArchiveCommand,
    WorldContentCreateCommand,
    WorldContentUpdateCommand,
    WorldItemDocument,
    document_digest,
    parse_world_content_command,
    parse_world_document,
)
from dnd_sim.vtt.world_content_store import (
    SQLiteWorldContentStore,
    WorldContentArchivedError,
    WorldContentCommandConflictError,
    WorldContentCorruptionError,
    WorldContentDocumentConflictError,
    WorldContentDocumentRevisionError,
    WorldContentLimitError,
    WorldContentNameConflictError,
    WorldContentNotFoundError,
    WorldContentReferencedError,
    WorldContentRevisionConflictError,
    _entry_hash,
)


def _permissions(
    *,
    audience: str = "table",
    control: str = "assigned_participants",
    assigned: tuple[str, ...] = ("player-1",),
) -> DocumentPermissions:
    return DocumentPermissions(
        audience=audience,
        control=control,
        assigned_participant_ids=assigned,
    )


def _item(
    item_id: str = "item-sword-1",
    *,
    table_id: str = "table-one",
    name: str = "Iron Sword",
    document_revision: int = 1,
    description: str | None = "A balanced martial blade.",
    tags: tuple[str, ...] = ("martial", "weapon"),
    permissions: DocumentPermissions | None = None,
) -> WorldItemDocument:
    return WorldItemDocument(
        item_id=item_id,
        table_id=table_id,
        document_revision=document_revision,
        name=name,
        folder_id="equipment",
        tags=tags,
        permissions=permissions or _permissions(),
        provenance=DocumentProvenance(
            source_digest="sha256:" + "1" * 64,
            source_record_digest="sha256:" + "2" * 64,
        ),
        data=Dnd5eItemData(
            item_type="weapon",
            description=description,
            equip_slots=("main_hand",),
            value_cp=1_500,
            weight_lb=3.0,
            action=Dnd5eActionInput(
                name="Slash",
                action_type="attack",
                to_hit=5,
                damage="1d8+3",
                damage_type="slashing",
                reach_ft=5,
            ),
        ),
    )


def _actor(
    actor_id: str = "actor-hero-1",
    *,
    table_id: str = "table-one",
    name: str = "Aster Vale",
    document_revision: int = 1,
    inventory: tuple[ActorInventoryItem, ...] = (),
    permissions: DocumentPermissions | None = None,
    tags: tuple[str, ...] = ("hero", "player character"),
) -> WorldActorDocument:
    return WorldActorDocument(
        actor_id=actor_id,
        table_id=table_id,
        document_revision=document_revision,
        name=name,
        folder_id="party",
        tags=tags,
        permissions=permissions or _permissions(),
        sheet=Dnd5eActorSheet(
            actor_kind="player_character",
            size="medium",
            level=4,
            max_hit_points=27,
            armor_class=16,
            speed_ft=30,
            initiative_modifier=3,
            movement_speeds=Dnd5eMovementSpeeds(walk=30, climb=15),
            senses=Dnd5eSenses(darkvision_ft=60, passive_perception=12),
            ability_scores=Dnd5eAbilityScores(
                strength=10,
                dexterity=16,
                constitution=14,
                intelligence=12,
                wisdom=11,
                charisma=8,
            ),
            class_levels={"fighter": 4},
            save_modifiers={"strength": 5, "constitution": 4},
            skill_modifiers={"athletics": 5, "perception": 2},
            resource_maxima={"second_wind": 1},
            proficiencies=("light armor", "martial weapons"),
            languages=("common", "elvish"),
            traits=("second wind",),
            known_spells=(),
            actions=(
                Dnd5eActionInput(
                    name="Shove",
                    action_type="utility",
                    target_mode="single_enemy",
                ),
            ),
        ),
        inventory=inventory,
        gm_notes="A reusable preparation record, never live encounter state.",
    )


def _create(
    document: WorldActorDocument | WorldItemDocument,
    *,
    command_id: str,
    expected_revision: int,
) -> WorldContentCreateCommand:
    return WorldContentCreateCommand(
        command_id=command_id,
        expected_revision=expected_revision,
        document=document,
    )


def _store() -> SQLiteWorldContentStore:
    return SQLiteWorldContentStore(sqlite3.connect(":memory:"))


def test_document_contracts_are_strict_frozen_and_versioned() -> None:
    item = _item()

    assert item.schema_version == "vtt.world_item_document.v1"
    assert item.document_kind == "item"
    assert item.document_revision == 1
    with pytest.raises(ValidationError):
        item.name = "Changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        WorldItemDocument.model_validate({**item.model_dump(), "unknown": True})

    encoded = _create(item, command_id="create-item", expected_revision=0).model_dump(mode="json")
    assert parse_world_content_command(encoded) == _create(
        item,
        command_id="create-item",
        expected_revision=0,
    )


def test_world_content_foundation_has_no_runtime_or_external_io_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = (
        (root / "src/dnd_sim/vtt/world_content_contracts.py").read_text(encoding="utf-8"),
        (root / "src/dnd_sim/vtt/world_content_store.py").read_text(encoding="utf-8"),
    )
    forbidden = (
        "engine_runtime",
        "http_api",
        "importlib",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "eval(",
        "exec(",
        "model_construct(",
    )
    for source in sources:
        for fragment in forbidden:
            assert fragment not in source


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("name", "<script>bad()</script>", "markup"),
        ("name", "https://bad.example/item", "URL"),
        ("name", "Bearer abcdefghijklmnop", "credential"),
        ("description", "javascript:alert(1)", "executable URI"),
        ("description", "eyJabcde.abcdef.abcdefgh", "credential"),
        ("description", "password=correct-horse-battery", "credential"),
        ("description", "body { color: red; }", "CSS"),
    ],
)
def test_documents_reject_markup_urls_and_credential_material(
    field: str,
    value: str,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        if field == "name":
            _item(name=value)
        else:
            _item(description=value)


@pytest.mark.parametrize(
    "value",
    [
        "data:application/xhtml+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",
        "data:image/svg%2Bxml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",
        "d\na\tt\ra:text/html;base64,PHNjcmlwdD4=",
        "ｄａｔａ：ｔｅｘｔ／ｈｔｍｌ，PHNjcmlwdD4=",
        "java\nscript:alert(1)",
        "vb\tscript:msgbox(1)",
        "java\u200bscript:alert(1)",
        "ｊａｖａｓｃｒｉｐｔ：alert(1)",
        "ｈｔｔｐｓ：／／evil.example/path",
        "https:%2f%2fevil.example/path",
        "https:%252f%252fevil.example/path",
        "https:%5c%5cevil.example/path",
        "jav%61script:alert(1)",
        r"https:\\evil.example\\payload",
        r"\\evil.example\share",
        r"C:\Users\secret\payload",
        "-----BEGIN PRIVATE KEY-----\nQUJDREVGR0g=\n-----END PRIVATE KEY-----",
        "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAIOSFODNN7EXAMPLE",
        "safe\u202eevil",
        "body/**/{color:red}",
        "&lt;script&gt;alert(1)&lt;/script&gt;",
        "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;",
    ],
)
def test_canonical_security_scan_rejects_obfuscated_active_or_secret_text(
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        _item(description=value)


@pytest.mark.parametrize(
    "key",
    ["api_token", "private_key", "access_key", "auth", "session_id"],
)
def test_canonical_security_scan_rejects_sensitive_nested_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="credential-like key"):
        Dnd5eActorSheet.model_validate(
            {
                **_actor().sheet.model_dump(mode="python"),
                "resource_maxima": {key: 1},
            }
        )


@pytest.mark.parametrize(
    "value",
    [
        "Basic attack training.",
        "Authentication is handled outside this record.",
        "Data gathered by the sage.",
        "A secret door with no stored key.",
        "Use a backslash \\ as a rune.",
        "A 50% chance to find the hidden path.",
    ],
)
def test_canonical_security_scan_allows_ordinary_vtt_text(value: str) -> None:
    assert _item(description=value).data.description == value


def test_all_nested_text_is_inert() -> None:
    with pytest.raises(ValidationError, match="credential material"):
        Dnd5eActionInput(
            name="Bearer abcdefghijklmnop",
            action_type="utility",
        )
    with pytest.raises(ValidationError, match="HTML or SVG markup"):
        _item(description="<style>body { display: none }</style>")
    with pytest.raises(ValidationError, match="executable URI"):
        _item(description="data:text/html,active")
    with pytest.raises(ValidationError, match="unsupported Unicode scalar"):
        _item(description="invalid-surrogate-\ud800")


def test_total_encoded_document_size_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dnd_sim.vtt.world_content_contracts as contracts

    monkeypatch.setattr(contracts, "MAX_DOCUMENT_JSON_BYTES", 256)
    with pytest.raises(ValidationError, match="document must encode to at most 256 bytes"):
        _item()


def test_metadata_and_permission_collections_require_canonical_order() -> None:
    with pytest.raises(ValidationError, match="tags must use canonical sorted order"):
        _item(tags=("weapon", "martial"))
    with pytest.raises(ValidationError, match="tags must contain unique values"):
        _item(tags=("weapon", "weapon"))
    with pytest.raises(ValidationError, match="assigned_participant_ids"):
        _permissions(assigned=("player-2", "player-1"))

    policy = _permissions(audience="assigned_participants")
    assert policy.can_view(principal_id="player-1", principal_role="player")
    assert policy.can_control(principal_id="player-1", principal_role="player")
    assert not policy.can_view(principal_id="player-2", principal_role="player")
    assert not policy.can_view(principal_id=None, principal_role="spectator")
    assert policy.can_view(principal_id=None, principal_role="gm")


def test_actor_sheet_accepts_static_engine_inputs_and_rejects_runtime_state() -> None:
    actor = _actor()

    assert actor.sheet.max_hit_points == 27
    assert actor.sheet.class_levels == {"fighter": 4}
    assert actor.sheet.movement_speeds.climb == 15
    assert actor.sheet.senses.darkvision_ft == 60
    with pytest.raises(ValidationError, match="current_hp"):
        Dnd5eActorSheet.model_validate(
            {
                **actor.sheet.model_dump(mode="python"),
                "current_hp": 9,
            }
        )
    with pytest.raises(ValidationError, match="level must equal total class levels"):
        Dnd5eActorSheet.model_validate({**actor.sheet.model_dump(mode="python"), "level": 3})
    with pytest.raises(ValidationError, match="current_resources"):
        Dnd5eActorSheet.model_validate(
            {
                **actor.sheet.model_dump(mode="python"),
                "current_resources": {"second_wind": 0},
            }
        )
    with pytest.raises(ValidationError, match="class levels must total at most 20"):
        Dnd5eActorSheet.model_validate(
            {
                **actor.sheet.model_dump(mode="python"),
                "class_levels": {"fighter": 20, "wizard": 1},
            }
        )


def test_document_graph_is_deeply_immutable_and_detached_from_inputs() -> None:
    payload = _actor().sheet.model_dump(mode="python")
    external_class_levels = {"fighter": 4}
    external_resources = {"second_wind": 1}
    payload["class_levels"] = external_class_levels
    payload["resource_maxima"] = external_resources
    sheet = Dnd5eActorSheet.model_validate(payload)
    actor = _actor().model_copy(update={"sheet": sheet})
    actor = WorldActorDocument.model_validate(actor.model_dump(mode="python"))
    digest_before = document_digest(actor)

    external_class_levels["fighter"] = 19
    external_resources["second_wind"] = 0
    assert actor.sheet.class_levels == {"fighter": 4}
    assert actor.sheet.resource_maxima == {"second_wind": 1}
    for mapping in (
        actor.sheet.class_levels,
        actor.sheet.save_modifiers,
        actor.sheet.skill_modifiers,
        actor.sheet.resource_maxima,
    ):
        with pytest.raises(TypeError):
            mapping["mutation"] = 1  # type: ignore[index]

    assert document_digest(actor) == digest_before
    decoded = parse_world_document(actor.model_dump_json())
    assert decoded == actor
    assert document_digest(decoded) == digest_before
    with pytest.raises(TypeError):
        decoded.sheet.class_levels["fighter"] = 19  # type: ignore[index]


def test_digest_and_store_revalidate_model_copy_bypasses() -> None:
    invalid = _item().model_copy(update={"name": "https://evil.example/item"})
    with pytest.raises(ValidationError):
        document_digest(invalid)

    valid_command = _create(_item(), command_id="create-item", expected_revision=0)
    invalid_command = valid_command.model_copy(update={"document": invalid})
    store = _store()
    with pytest.raises(ValidationError):
        store.execute(invalid_command)
    assert store.revision() == 0


def test_actor_inventory_references_are_bounded_sorted_unique_and_static() -> None:
    first = ActorInventoryItem(item_id="item-a", quantity=2, equipped=False)
    second = ActorInventoryItem(item_id="item-b", quantity=1, equipped=True, attuned=True)
    actor = _actor(inventory=(first, second))

    assert actor.inventory[1].equipped is True
    assert actor.inventory[1].attuned is True
    with pytest.raises(ValidationError, match="inventory must use canonical item order"):
        _actor(inventory=(second, first))
    with pytest.raises(ValidationError, match="inventory must reference unique item IDs"):
        _actor(inventory=(first, first))
    with pytest.raises(ValidationError, match="current_charges"):
        ActorInventoryItem.model_validate(
            {
                "item_id": "item-a",
                "quantity": 1,
                "equipped": False,
                "current_charges": 1,
            }
        )


def test_create_snapshot_and_table_scope_are_deterministic() -> None:
    store = _store()
    item_b = _item("item-b", name="Zither", tags=("instrument",))
    item_a = _item("item-a", name="Arrows", tags=("ammunition",))
    other = _item(
        "item-other",
        table_id="table-two",
        name="Other World Item",
        tags=("other",),
    )

    store.execute(_create(item_b, command_id="create-b", expected_revision=0))
    store.execute(_create(item_a, command_id="create-a", expected_revision=1))
    store.execute(_create(other, command_id="create-other", expected_revision=2))

    view = store.snapshot("table-one")
    assert view.revision == 3
    assert tuple(entry.document_id for entry in view.documents) == ("item-a", "item-b")
    assert store.snapshot("table-two").documents[0].document_id == "item-other"
    assert store.snapshot("table-missing").documents == ()


def test_actor_creation_requires_active_same_table_item_references() -> None:
    store = _store()
    actor = _actor(
        inventory=(ActorInventoryItem(item_id="item-sword-1", quantity=1, equipped=True),)
    )

    with pytest.raises(WorldContentReferencedError, match="missing active item"):
        store.execute(_create(actor, command_id="create-actor", expected_revision=0))

    store.execute(_create(_item(), command_id="create-item", expected_revision=0))
    result = store.execute(_create(actor, command_id="create-actor", expected_revision=1))
    assert result.receipt.revision == 2

    wrong_table_actor = _actor(
        "actor-other",
        table_id="table-two",
        inventory=(ActorInventoryItem(item_id="item-sword-1", quantity=1, equipped=False),),
    )
    with pytest.raises(WorldContentReferencedError, match="missing active item"):
        store.execute(
            _create(wrong_table_actor, command_id="create-other-actor", expected_revision=2)
        )

    invalid_attunement = _actor(
        "actor-attuned",
        name="Attuned Hero",
        inventory=(
            ActorInventoryItem(
                item_id="item-sword-1",
                quantity=1,
                equipped=True,
                attuned=True,
            ),
        ),
        tags=("hero",),
    )
    with pytest.raises(WorldContentReferencedError, match="does not require attunement"):
        store.execute(
            _create(
                invalid_attunement,
                command_id="invalid-attunement",
                expected_revision=2,
            )
        )


def test_ids_are_permanent_and_active_names_are_unique_by_table_and_kind() -> None:
    store = _store()
    store.execute(_create(_item(), command_id="create-item", expected_revision=0))

    with pytest.raises(WorldContentNameConflictError):
        store.execute(
            _create(
                _item("item-two", name="Ｉｒｏｎ Ｓｗｏｒｄ"),
                command_id="duplicate-name",
                expected_revision=1,
            )
        )

    # A same-named actor is a different document kind, and another table is isolated.
    store.execute(
        _create(
            _actor(name="Iron Sword", tags=("hero",)),
            command_id="same-name-actor",
            expected_revision=1,
        )
    )
    store.execute(
        _create(
            _item(
                "item-other",
                table_id="table-two",
                name="iron sword",
                tags=("weapon",),
            ),
            command_id="same-name-other-table",
            expected_revision=2,
        )
    )
    store.execute(
        WorldContentArchiveCommand(
            command_id="archive-item",
            expected_revision=3,
            table_id="table-one",
            document_kind="item",
            document_id="item-sword-1",
        )
    )
    with pytest.raises(WorldContentDocumentConflictError, match="permanently used"):
        store.execute(
            _create(
                _item(name="A New Sword"),
                command_id="reuse-id",
                expected_revision=4,
            )
        )


def test_update_uses_document_and_store_revisions_with_exact_idempotency() -> None:
    store = _store()
    original = _item()
    created = _create(original, command_id="create-item", expected_revision=0)
    first = store.execute(created)
    replay = store.execute(created)
    assert replay.replayed is True
    assert replay.receipt == first.receipt

    updated = _item(name="Tempered Sword", document_revision=2)
    command = WorldContentUpdateCommand(
        command_id="update-item",
        expected_revision=1,
        document=updated,
    )
    result = store.execute(command)
    assert result.receipt.revision == 2
    assert store.snapshot("table-one").document("item", "item-sword-1") == updated

    replay_update = store.execute(command)
    assert replay_update.replayed is True
    with pytest.raises(WorldContentCommandConflictError):
        store.execute(command.model_copy(update={"expected_revision": 2}))
    with pytest.raises(WorldContentRevisionConflictError) as caught:
        store.execute(
            _create(
                _item("item-second", name="Shield", tags=("armor",)),
                command_id="stale",
                expected_revision=1,
            )
        )
    assert caught.value.current_revision == 2


def test_update_rejects_identity_changes_stale_document_revision_and_noop() -> None:
    store = _store()
    store.execute(_create(_item(), command_id="create-item", expected_revision=0))

    with pytest.raises(WorldContentDocumentRevisionError, match="expected document revision 2"):
        store.execute(
            WorldContentUpdateCommand(
                command_id="stale-doc",
                expected_revision=1,
                document=_item(name="Changed", document_revision=1),
            )
        )
    with pytest.raises(WorldContentNotFoundError):
        store.execute(
            WorldContentUpdateCommand(
                command_id="wrong-id",
                expected_revision=1,
                document=_item("item-missing", name="Changed", document_revision=2),
            )
        )

    identical_except_revision = original = _item(document_revision=1)
    with pytest.raises(WorldContentDocumentConflictError, match="change document content"):
        store.execute(
            WorldContentUpdateCommand(
                command_id="noop",
                expected_revision=1,
                document=identical_except_revision.model_copy(update={"document_revision": 2}),
            )
        )
    assert original.document_revision == 1


def test_archiving_referenced_items_is_blocked_until_actor_is_archived() -> None:
    store = _store()
    store.execute(_create(_item(), command_id="create-item", expected_revision=0))
    actor = _actor(
        inventory=(ActorInventoryItem(item_id="item-sword-1", quantity=1, equipped=True),)
    )
    store.execute(_create(actor, command_id="create-actor", expected_revision=1))

    archive_item = WorldContentArchiveCommand(
        command_id="archive-item",
        expected_revision=2,
        table_id="table-one",
        document_kind="item",
        document_id="item-sword-1",
    )
    with pytest.raises(WorldContentReferencedError, match="actor-hero-1"):
        store.execute(archive_item)

    store.execute(
        WorldContentArchiveCommand(
            command_id="archive-actor",
            expected_revision=2,
            table_id="table-one",
            document_kind="actor",
            document_id="actor-hero-1",
        )
    )
    store.execute(archive_item.model_copy(update={"expected_revision": 3}))
    assert not store.snapshot("table-one").active_documents
    with pytest.raises(WorldContentArchivedError):
        store.execute(
            WorldContentUpdateCommand(
                command_id="update-archived",
                expected_revision=4,
                document=_item(document_revision=2, name="Nope"),
            )
        )


def test_transaction_rolls_back_all_document_mutations() -> None:
    store = _store()

    with pytest.raises(WorldContentNameConflictError):
        with store.transaction() as transaction:
            transaction.execute(_create(_item(), command_id="first", expected_revision=0))
            transaction.execute(
                _create(
                    _item("item-two", name="iron sword"),
                    command_id="second",
                    expected_revision=1,
                )
            )

    assert store.snapshot("table-one").revision == 0
    assert store.snapshot("table-one").documents == ()


def test_transaction_rolls_back_after_base_exception() -> None:
    class AbortTransaction(BaseException):
        pass

    store = _store()
    with pytest.raises(AbortTransaction):
        with store.transaction() as transaction:
            transaction.execute(_create(_item(), command_id="first", expected_revision=0))
            raise AbortTransaction

    assert store.snapshot("table-one").revision == 0
    assert store.snapshot("table-one").documents == ()


def test_search_filters_permissions_before_matching_and_projects_only_safe_metadata() -> None:
    store = _store()
    secret = _item(
        "item-secret",
        name="GM Relic",
        description="The quiet passphrase is amber-lantern.",
        tags=("relic",),
        permissions=_permissions(audience="gm_only", control="gm_only", assigned=()),
    )
    public = _item(
        "item-public",
        name="Traveler Pack",
        description="This description mentions amber-lantern too.",
        tags=("adventuring gear", "pack"),
    )
    assigned = _actor(
        permissions=_permissions(audience="assigned_participants"),
        tags=("hero", "scout"),
    )
    for revision, (command_id, document) in enumerate(
        (("secret", secret), ("public", public), ("actor", assigned))
    ):
        store.execute(_create(document, command_id=command_id, expected_revision=revision))

    # Descriptions and engine data are deliberately not part of searchable text.
    assert (
        store.search(
            table_id="table-one",
            query="amber-lantern",
            principal_id="player-1",
            principal_role="player",
        )
        == ()
    )
    player_hits = store.search(
        table_id="table-one",
        query="scout",
        principal_id="player-1",
        principal_role="player",
    )
    assert len(player_hits) == 1
    assert player_hits[0].document_id == "actor-hero-1"
    assert set(type(player_hits[0]).model_fields) == {
        "schema_version",
        "table_id",
        "document_kind",
        "document_id",
        "name",
        "folder_id",
        "tags",
        "can_control",
    }
    assert (
        store.search(
            table_id="table-one",
            query="GM Relic",
            principal_id="player-1",
            principal_role="player",
        )
        == ()
    )
    assert (
        store.search(
            table_id="table-one",
            query="relic",
            principal_id=None,
            principal_role="gm",
        )[0].document_id
        == "item-secret"
    )


def test_projection_matrix_hides_authority_and_relationships_by_role() -> None:
    store = _store()
    linked = _item(
        "item-linked",
        name="Assigned Blade",
        tags=("weapon",),
        permissions=_permissions(audience="gm_only", control="gm_only", assigned=()),
    )
    players = _item(
        "item-players",
        name="Player Handbook Note",
        tags=("players",),
        permissions=_permissions(audience="players", control="gm_only", assigned=()),
    )
    public = _item(
        "item-public",
        name="Public Rules Card",
        tags=("public",),
        permissions=_permissions(audience="table", control="gm_only", assigned=()),
    )
    secret = _item(
        "item-secret",
        name="GM Secret",
        tags=("secret",),
        permissions=_permissions(audience="gm_only", control="gm_only", assigned=()),
    )
    assigned_actor = _actor(
        inventory=(ActorInventoryItem(item_id="item-linked", quantity=1, equipped=True),),
        permissions=_permissions(audience="assigned_participants"),
    )
    public_actor = _actor(
        "actor-public",
        name="Town Crier",
        inventory=(ActorInventoryItem(item_id="item-secret", quantity=1, equipped=False),),
        permissions=_permissions(audience="table", control="gm_only", assigned=()),
        tags=("public",),
    )
    documents = (linked, players, public, secret, assigned_actor, public_actor)
    for revision, document in enumerate(documents):
        store.execute(
            _create(
                document,
                command_id=f"create-{revision}",
                expected_revision=revision,
            )
        )

    gm = store.project(table_id="table-one", principal_id="gm-1", principal_role="gm")
    assert len(gm.documents) == 6
    assert all("permissions" not in entry.document.model_dump() for entry in gm.documents)
    assert all("provenance" not in entry.document.model_dump() for entry in gm.documents)

    assigned = store.project(
        table_id="table-one",
        principal_id="player-1",
        principal_role="player",
    )
    assigned_keys = {(entry.document_kind, entry.document_id) for entry in assigned.documents}
    assert assigned_keys == {
        ("actor", "actor-hero-1"),
        ("actor", "actor-public"),
        ("item", "item-linked"),
        ("item", "item-players"),
        ("item", "item-public"),
    }
    assigned_actor_projection = next(
        entry.document for entry in assigned.documents if entry.document_id == "actor-hero-1"
    )
    assert [row.item_id for row in assigned_actor_projection.inventory] == ["item-linked"]

    unrelated = store.project(
        table_id="table-one",
        principal_id="player-2",
        principal_role="player",
    )
    assert {(entry.document_kind, entry.document_id) for entry in unrelated.documents} == {
        ("actor", "actor-public"),
        ("item", "item-players"),
        ("item", "item-public"),
    }

    spectator = store.project(
        table_id="table-one",
        principal_id=None,
        principal_role="spectator",
    )
    assert {(entry.document_kind, entry.document_id) for entry in spectator.documents} == {
        ("actor", "actor-public"),
        ("item", "item-public"),
    }
    public_actor_projection = next(
        entry.document for entry in spectator.documents if entry.document_id == "actor-public"
    )
    assert public_actor_projection.inventory == ()
    assert (
        store.search(
            table_id="table-one",
            query="secret",
            principal_id=None,
            principal_role="spectator",
        )
        == ()
    )


def test_active_actor_and_item_limits_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dnd_sim.vtt.world_content_store as store_module

    assert MAX_ACTIVE_ACTORS == 1_000
    assert MAX_ACTIVE_ITEMS == 10_000
    monkeypatch.setattr(store_module, "MAX_ACTIVE_ACTORS", 1)
    monkeypatch.setattr(store_module, "MAX_ACTIVE_ITEMS", 1)
    store = _store()
    store.execute(_create(_item(), command_id="item-one", expected_revision=0))
    store.execute(_create(_actor(), command_id="actor-one", expected_revision=1))

    with pytest.raises(WorldContentLimitError, match="active item limit"):
        store.execute(
            _create(
                _item("item-two", name="Shield", tags=("armor",)),
                command_id="item-two",
                expected_revision=2,
            )
        )
    with pytest.raises(WorldContentLimitError, match="active actor limit"):
        store.execute(
            _create(
                _actor("actor-two", name="Bryn", tags=("hero",)),
                command_id="actor-two",
                expected_revision=2,
            )
        )


def test_restart_replays_canonical_history_and_receipts(tmp_path) -> None:
    path = tmp_path / "world-content.sqlite3"
    connection = sqlite3.connect(path)
    store = SQLiteWorldContentStore(connection)
    create = _create(_item(), command_id="create-item", expected_revision=0)
    receipt = store.execute(create).receipt
    connection.close()

    reopened_connection = sqlite3.connect(path)
    reopened = SQLiteWorldContentStore(reopened_connection)
    assert reopened.snapshot("table-one").document("item", "item-sword-1") == _item()
    assert reopened.receipts_after(0) == (receipt,)
    assert reopened.execute(create).replayed is True
    reopened_connection.close()


@pytest.mark.parametrize(
    "sql,params",
    [
        (
            "UPDATE _vtt_world_content_events SET command_json = ? WHERE revision = 1",
            ("{}",),
        ),
        (
            "UPDATE _vtt_world_content_events SET receipt_json = ? WHERE revision = 1",
            ("{}",),
        ),
        (
            "UPDATE _vtt_world_content_events SET entry_hash = ? WHERE revision = 1",
            ("f" * 64,),
        ),
        (
            "UPDATE _vtt_world_content_head SET head_hash = ? WHERE singleton = 1",
            ("e" * 64,),
        ),
    ],
)
def test_tampering_is_detected_on_every_read(sql: str, params: tuple[str, ...]) -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteWorldContentStore(connection)
    store.execute(_create(_item(), command_id="create-item", expected_revision=0))
    connection.execute(sql, params)
    connection.commit()

    with pytest.raises(WorldContentCorruptionError):
        store.snapshot("table-one")


def test_removed_and_reordered_history_are_detected() -> None:
    for mutate in ("remove", "reorder"):
        connection = sqlite3.connect(":memory:")
        store = SQLiteWorldContentStore(connection)
        store.execute(_create(_item(), command_id="first", expected_revision=0))
        store.execute(
            _create(
                _item("item-two", name="Shield", tags=("armor",)),
                command_id="second",
                expected_revision=1,
            )
        )
        if mutate == "remove":
            connection.execute("DELETE FROM _vtt_world_content_events WHERE revision = 1")
        else:
            connection.execute("UPDATE _vtt_world_content_events SET revision = revision + 10")
            connection.execute(
                "UPDATE _vtt_world_content_events SET revision = 2 " "WHERE revision = 11"
            )
            connection.execute(
                "UPDATE _vtt_world_content_events SET revision = 1 " "WHERE revision = 12"
            )
        connection.commit()

        with pytest.raises(WorldContentCorruptionError):
            store.snapshot("table-one")


@pytest.mark.parametrize("tampered_field", ["command_json", "receipt_json"])
def test_semantic_tamper_is_detected_even_after_hashes_are_recomputed(
    tampered_field: str,
) -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteWorldContentStore(connection)
    store.execute(_create(_item(), command_id="create-item", expected_revision=0))
    command_json, receipt_json, previous_hash = connection.execute(
        "SELECT command_json, receipt_json, previous_hash "
        "FROM _vtt_world_content_events WHERE revision = 1"
    ).fetchone()
    if tampered_field == "command_json":
        payload = json.loads(command_json)
        payload["document"]["name"] = "Tampered Command Name"
        command_json = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        payload = json.loads(receipt_json)
        payload["event"]["document"]["name"] = "Tampered Receipt Name"
        receipt_json = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    rewritten_hash = _entry_hash(
        revision=1,
        command_json=command_json,
        receipt_json=receipt_json,
        previous_hash=previous_hash,
    )
    connection.execute(
        "UPDATE _vtt_world_content_events "
        "SET command_json = ?, receipt_json = ?, entry_hash = ? "
        "WHERE revision = 1",
        (command_json, receipt_json, rewritten_hash),
    )
    connection.execute(
        "UPDATE _vtt_world_content_head SET head_hash = ? WHERE singleton = 1",
        (rewritten_hash,),
    )
    connection.commit()

    with pytest.raises(WorldContentCorruptionError):
        store.snapshot("table-one")
