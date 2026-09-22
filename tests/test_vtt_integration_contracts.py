from __future__ import annotations

import ast
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.integration_contracts import (
    EXTERNAL_CONTENT_ENVELOPE_SCHEMA_VERSION,
    IMPORT_PREVIEW_SCHEMA_VERSION,
    INTEGRATION_GRANT_SCHEMA_VERSION,
    INTEGRATION_MANIFEST_SCHEMA_VERSION,
    BlobManifest,
    ContentProvenance,
    ExternalContentEnvelope,
    ExternalContentRecord,
    ImportCommit,
    ImportPreview,
    ImportPreviewChange,
    IntegrationGrant,
    IntegrationManifest,
    VerifiedImportWriteSet,
    canonical_digest,
)

CAPTURED_AT = datetime(2026, 8, 12, 18, 30, tzinfo=UTC)


def manifest(**overrides: object) -> IntegrationManifest:
    values: dict[str, object] = {
        "schema_version": INTEGRATION_MANIFEST_SCHEMA_VERSION,
        "extension_id": "org.example.safe-importer",
        "publisher_id": "org.example",
        "extension_version": "1.4.2",
        "api_version_min": 1,
        "api_version_max": 2,
        "permissions": ("actors:import", "items:import"),
        "provider_ids": ("example-content",),
        "contribution_types": ("actor", "item"),
    }
    values.update(overrides)
    return IntegrationManifest(**values)


def integration_grant(
    declared_manifest: IntegrationManifest | None = None,
    **overrides: object,
) -> IntegrationGrant:
    declared_manifest = declared_manifest or manifest()
    values: dict[str, object] = {
        "schema_version": INTEGRATION_GRANT_SCHEMA_VERSION,
        "grant_id": "grant-1",
        "extension_id": "org.example.safe-importer",
        "manifest_digest": canonical_digest(declared_manifest),
        "participant_id": "gm-1",
        "table_id": "table-1",
        "permissions": ("actors:import",),
        "provider_ids": ("example-content",),
        "contribution_types": ("actor",),
        "issued_at": CAPTURED_AT,
        "expires_at": CAPTURED_AT + timedelta(hours=1),
        "revoked_at": None,
        "token_hash": "sha256:" + "a" * 64,
    }
    values.update(overrides)
    return IntegrationGrant(**values)


def provenance(**overrides: object) -> ContentProvenance:
    values: dict[str, object] = {
        "provider_record_id": "character-42",
        "captured_at": CAPTURED_AT,
        "source_revision": "rev-7",
        "source_digest": "sha256:" + "1" * 64,
        "attribution": "Example Publisher",
    }
    values.update(overrides)
    return ContentProvenance(**values)


def envelope(**overrides: object) -> ExternalContentEnvelope:
    record = ExternalContentRecord(
        record_id="actor-42",
        contribution_type="actor",
        title="Aster Vale",
        data={
            "name": "Aster Vale",
            "abilities": {"strength": 10, "wisdom": 16},
            "tags": ["cleric", "level-3"],
        },
        blob_ids=("portrait-42",),
        provenance=provenance(),
    )
    blob = BlobManifest(
        blob_id="portrait-42",
        file_name="aster-vale.webp",
        media_type="image/webp",
        byte_size=4_096,
        sha256="2" * 64,
        provenance=provenance(provider_record_id="portrait-42"),
    )
    values: dict[str, object] = {
        "schema_version": EXTERNAL_CONTENT_ENVELOPE_SCHEMA_VERSION,
        "provider_id": "example-content",
        "provider_schema_version": "characters.v3",
        "capture_id": "capture-20260812-001",
        "captured_at": CAPTURED_AT,
        "records": (record,),
        "blobs": (blob,),
    }
    values.update(overrides)
    return ExternalContentEnvelope(**values)


def preview(**overrides: object) -> ImportPreview:
    source = envelope()
    source_record = source.records[0]
    values: dict[str, object] = {
        "schema_version": IMPORT_PREVIEW_SCHEMA_VERSION,
        "preview_id": "preview-001",
        "grant_id": "grant-1",
        "extension_id": "org.example.safe-importer",
        "participant_id": "gm-1",
        "table_id": "table-1",
        "capture_id": source.capture_id,
        "envelope_digest": canonical_digest(source),
        "expected_revision": 12,
        "conflict_policy": "reject",
        "changes": (
            ImportPreviewChange(
                operation="create",
                contribution_type="actor",
                external_record_id="actor-42",
                source_record_digest=canonical_digest(source_record),
                target_id=None,
                proposed_data={
                    "name": "Aster Vale",
                    "abilities": {"strength": 10, "wisdom": 16},
                },
                summary="Create actor Aster Vale",
            ),
        ),
        "warnings": (),
    }
    values.update(overrides)
    return ImportPreview(**values)


def test_manifest_is_strict_canonical_and_uses_narrow_allowlists() -> None:
    value = manifest()

    assert value.permissions == ("actors:import", "items:import")
    assert value.model_dump(mode="json")["schema_version"] == ("vtt.integration_manifest.v1")
    value.require_api_version(1)
    value.require_api_version(2)

    with pytest.raises(ValidationError, match="sorted order"):
        manifest(permissions=("items:import", "actors:import"))
    with pytest.raises(ValidationError, match="unique"):
        manifest(provider_ids=("example-content", "example-content"))
    with pytest.raises(ValidationError):
        manifest(permissions=("network:unrestricted",))
    with pytest.raises(ValidationError, match="api_version_min"):
        manifest(api_version_min=3, api_version_max=2)
    with pytest.raises(ValidationError):
        manifest(unexpected=True)
    with pytest.raises(ValueError, match="compatibility"):
        value.require_api_version(3)
    with pytest.raises(ValueError, match="integer"):
        value.require_api_version(True)


def test_grant_contains_only_a_hash_and_must_narrow_the_manifest() -> None:
    value = IntegrationGrant(
        schema_version=INTEGRATION_GRANT_SCHEMA_VERSION,
        grant_id="grant-1",
        extension_id="org.example.safe-importer",
        manifest_digest=canonical_digest(manifest()),
        participant_id="gm-1",
        table_id="table-1",
        permissions=("actors:import",),
        provider_ids=("example-content",),
        contribution_types=("actor",),
        issued_at=CAPTURED_AT,
        expires_at=CAPTURED_AT + timedelta(hours=1),
        revoked_at=None,
        token_hash="sha256:" + "a" * 64,
    )

    value.require_manifest_scope(manifest())
    assert value.is_active(at=CAPTURED_AT + timedelta(minutes=1))
    assert "token" not in value.model_dump(mode="json")
    assert value.model_dump(mode="json")["token_hash"].startswith("sha256:")

    with pytest.raises(ValidationError):
        IntegrationGrant(
            **value.model_dump(),
            token="plaintext-secret",
        )
    with pytest.raises(ValueError, match="outside the manifest"):
        value.model_copy(update={"permissions": ("scenes:import",)}).require_manifest_scope(
            manifest()
        )
    assert not value.model_copy(update={"revoked_at": CAPTURED_AT}).is_active(
        at=CAPTURED_AT + timedelta(minutes=1)
    )
    with pytest.raises(ValidationError, match="maximum lifetime"):
        IntegrationGrant(
            **{
                **value.model_dump(),
                "expires_at": CAPTURED_AT + timedelta(days=365),
            }
        )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"portrait_url": "https://images.example/portrait.png"}, "remote URLs"),
        ({"portrait_url": "//images.example/portrait.png"}, "remote URLs"),
        ({"portrait_url": "file:///tmp/portrait.png"}, "remote URLs"),
        ({"description": "<p>unsafe markup</p>"}, "HTML"),
        ({"description": "<svg><path /></svg>"}, "HTML"),
        ({"access_token": "secret"}, "sensitive key"),
        ({"idToken": "secret"}, "sensitive key"),
        ({"credentials": {"user": "x"}}, "sensitive key"),
        ({"nested": {"cookie": "session=x"}}, "sensitive key"),
        ({"action": "javascript:alert(1)"}, "executable URI"),
        ({"auth": "not-even-a-token"}, "sensitive key"),
        ({"note": "Bearer super-secret"}, "credential material"),
        ({"jwt": "eyJhbGciOiJIUzI1NiJ9.payload.signature"}, "sensitive key"),
        ({"session_id": "session-secret"}, "sensitive key"),
        ({"tokenValue": "secret"}, "sensitive key"),
        ({"apiKeyHash": "secret"}, "sensitive key"),
        (
            {"description": "data:application/xhtml+xml;base64,PGh0Ww+"},
            "executable URI",
        ),
        ({"portrait_url": r"https:\\images.example/portrait.png"}, "remote URLs"),
        ({"authorizationHeader": "Basic dXNlcjpwYXNz"}, "sensitive key"),
        ({"privateKey": "-----BEGIN PRIVATE KEY-----"}, "sensitive key"),
        ({"note": "Basic dXNlcjpwYXNz"}, "credential material"),
        ({"action": "java\nscript:alert(1)"}, "executable URI"),
    ],
)
def test_external_record_rejects_active_or_sensitive_content(
    data: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data=data,
            blob_ids=(),
            provenance=provenance(),
        )


def test_external_envelope_is_bounded_canonical_and_has_no_blob_locations() -> None:
    value = envelope()

    assert value.records[0].data["name"] == "Aster Vale"
    assert value.blobs[0].model_dump().keys() == {
        "schema_version",
        "blob_id",
        "file_name",
        "media_type",
        "byte_size",
        "sha256",
        "provenance",
    }

    with pytest.raises(ValidationError, match="sorted order"):
        envelope(
            records=(
                value.records[0].model_copy(update={"record_id": "z-record"}),
                value.records[0].model_copy(update={"record_id": "a-record"}),
            )
        )
    with pytest.raises(ValidationError, match="unknown blob"):
        envelope(records=(value.records[0].model_copy(update={"blob_ids": ("missing",)}),))
    with pytest.raises(ValidationError):
        BlobManifest(
            blob_id="bad-svg",
            file_name="payload.svg",
            media_type="image/svg+xml",
            byte_size=20,
            sha256="3" * 64,
            provenance=provenance(),
        )
    with pytest.raises(ValidationError):
        BlobManifest(
            **value.blobs[0].model_dump(),
            remote_url="https://images.example/portrait.webp",
        )
    with pytest.raises(ValidationError, match="unreferenced blob"):
        envelope(records=(value.records[0].model_copy(update={"blob_ids": ()}),))


def test_blob_bytes_must_match_the_declared_size_and_digest() -> None:
    content = b"safe"
    blob = BlobManifest(
        blob_id="portrait-safe",
        file_name="portrait-safe.webp",
        media_type="image/webp",
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        provenance=provenance(provider_record_id="portrait-safe"),
    )

    blob.require_bytes(content)
    with pytest.raises(ValueError, match="size"):
        blob.require_bytes(content + b"!")
    with pytest.raises(ValueError, match="digest"):
        blob.require_bytes(b"evil")
    with pytest.raises(ValueError, match="bytes"):
        blob.require_bytes(bytearray(content))  # type: ignore[arg-type]


def test_external_json_depth_and_size_limits_are_stable() -> None:
    nested: dict[str, object] = {"leaf": True}
    for index in range(20):
        nested = {f"level_{index}": nested}

    with pytest.raises(ValidationError, match="maximum depth"):
        ExternalContentRecord(
            record_id="deep-record",
            contribution_type="actor",
            title="Too deep",
            data=nested,
            blob_ids=(),
            provenance=provenance(),
        )


def test_external_provenance_rejects_markup_and_remote_locations() -> None:
    with pytest.raises(ValidationError, match="remote URLs"):
        provenance(source_revision="https://provider.example/revisions/7")
    with pytest.raises(ValidationError, match="HTML"):
        provenance(attribution="<a href='/publisher'>Publisher</a>")


def test_all_external_display_and_write_text_uses_the_inert_text_boundary() -> None:
    with pytest.raises(ValidationError, match="executable URI"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="data:text/plain,not-renderable-content",
            data={},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match="remote URLs"):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={"portrait": r"https:\\images.example/portrait.png"},
            summary="Create actor",
        )
    with pytest.raises(ValidationError, match="credential material"):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={},
            summary="Basic dXNlcjpwYXNz",
        )
    with pytest.raises(ValidationError, match="executable URI"):
        preview(warnings=("data:application/xhtml+xml;base64,PGh0bWw+",))
    with pytest.raises(ValidationError, match="credential material"):
        provenance(source_revision="-----BEGIN PRIVATE KEY-----")


@pytest.mark.parametrize(
    "active_text",
    [
        "ｊａｖａｓｃｒｉｐｔ:alert(1)",
        "javascript：alert(1)",
        "ｈｔｔｐｓ://evil.example/a",
        "data：text/plain,hello",
    ],
)
def test_nfkc_equivalent_active_uris_are_rejected_everywhere(active_text: str) -> None:
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title=active_text,
            data={},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"nested": [{"description": active_text}]},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={"description": active_text},
            summary="Create actor",
        )
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={},
            summary=active_text,
        )
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        preview(warnings=(active_text,))
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        provenance(source_revision=active_text)
    with pytest.raises(ValidationError, match="URI|remote URLs"):
        provenance(attribution=active_text)


def test_security_normalization_does_not_rewrite_safe_canonical_content() -> None:
    fullwidth_name = "Ａｓｔｅｒ"
    value = ExternalContentRecord(
        record_id="actor-42",
        contribution_type="actor",
        title=fullwidth_name,
        data={"name": fullwidth_name},
        blob_ids=(),
        provenance=provenance(),
    )

    assert value.title == fullwidth_name
    assert value.data["name"] == fullwidth_name
    assert canonical_digest(value) != canonical_digest(
        value.model_copy(update={"title": "Aster", "data": {"name": "Aster"}})
    )


@pytest.mark.parametrize(
    ("encoded_text", "message"),
    [
        ("https%3A%2F%2Fevil.example/a", "remote URLs"),
        ("https%253A%252F%252Fevil.example/a", "remote URLs"),
        ("javascript&#x3a;alert(1)", "executable URI"),
        ("java\u200bscript:alert(1)", "executable URI"),
        ("Bearer%20super-secret", "credential material"),
        ("Basic&#32;dXNlcjpwYXNz", "credential material"),
        ("Bea\u200brer super-secret", "credential material"),
        ("java\u2028script:alert(1)", "executable URI"),
        ("https%26%23x3a%3B%2F%2Fevil.example/a", "remote URLs"),
    ],
)
def test_encoded_active_content_is_rejected_in_every_inert_text_surface(
    encoded_text: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title=encoded_text,
            data={},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match=message):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"nested": [{"description": encoded_text}]},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match=message):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={"description": encoded_text},
            summary="Create actor",
        )
    with pytest.raises(ValidationError, match=message):
        ImportPreviewChange(
            operation="create",
            contribution_type="actor",
            external_record_id="actor-42",
            source_record_digest="sha256:" + "1" * 64,
            proposed_data={},
            summary=encoded_text,
        )
    with pytest.raises(ValidationError, match=message):
        preview(warnings=(encoded_text,))
    with pytest.raises(ValidationError, match=message):
        provenance(source_revision=encoded_text)
    with pytest.raises(ValidationError, match=message):
        provenance(attribution=encoded_text)


@pytest.mark.parametrize(
    "safe_text",
    [
        "Damage is 50% effective",
        "A value%2G remains literal",
        "Benign%20text",
        "Benign&#32;text",
        "Research &amp; development",
        "Family\u200dgroup",
        "Internal\u00a0separator",
        "Research & development",
    ],
)
def test_detection_only_decoding_preserves_safe_original_text(safe_text: str) -> None:
    value = ExternalContentRecord(
        record_id="actor-42",
        contribution_type="actor",
        title="Aster Vale",
        data={"description": safe_text},
        blob_ids=(),
        provenance=provenance(),
    )

    assert value.data["description"] == safe_text
    assert canonical_digest(value.data) == canonical_digest({"description": safe_text})


def test_security_decoding_rejects_nonconverging_nested_encodings() -> None:
    nested_encoding = "%" + "25" * 20 + "20"

    with pytest.raises(ValidationError, match="security decoding depth"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"description": nested_encoding},
            blob_ids=(),
            provenance=provenance(),
        )


def test_security_normalization_rejects_excessive_compatibility_expansion() -> None:
    # Each Arabic ligature expands to 18 codepoints under NFKC normalization.
    expanding_text = "\ufdfa" * 16_384

    with pytest.raises(ValidationError, match="security normalization length"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"description": expanding_text},
            blob_ids=(),
            provenance=provenance(),
        )


def test_execution_revalidation_rejects_forged_encoded_active_content() -> None:
    reviewed = preview()
    source = envelope()
    declared_manifest = manifest()
    grant = integration_grant(declared_manifest)
    forged_change = reviewed.changes[0].model_copy(
        update={"proposed_data": {"portrait": "https%3A%2F%2Fevil.example/a"}}
    )
    forged_preview = reviewed.model_copy(update={"changes": (forged_change,)})
    forged_commit = ImportCommit.for_preview(
        forged_preview,
        command_id="forged-encoded-content",
    )

    with pytest.raises(ValidationError, match="remote URLs"):
        forged_commit.verify_for_execution(
            forged_preview,
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
            current_revision=12,
        )


@pytest.mark.parametrize(
    "credential_key",
    [
        "access_token",
        "apiKeyHash",
        "auth",
        "authHeader",
        "authentication",
        "authorization",
        "bearer",
        "clientSecret",
        "credentials",
        "privateKey",
        "refreshToken",
        "sessionKey",
        "tokenValue",
    ],
)
def test_credential_key_families_are_rejected(credential_key: str) -> None:
    with pytest.raises(ValidationError, match="sensitive key"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"nested": [{credential_key: "opaque-value"}]},
            blob_ids=(),
            provenance=provenance(),
        )


@pytest.mark.parametrize(
    "domain_key",
    [
        "authorizationNote",
        "passwordHint",
        "secretDoor",
        "token",
        "tokenizer",
    ],
)
def test_ordinary_vtt_domain_keys_are_not_credential_false_positives(domain_key: str) -> None:
    value = ExternalContentRecord(
        record_id="actor-42",
        contribution_type="actor",
        title="Aster Vale",
        data={"nested": [{domain_key: "ordinary VTT content"}]},
        blob_ids=(),
        provenance=provenance(),
    )

    assert value.data["nested"][0][domain_key] == "ordinary VTT content"  # type: ignore[index]


def test_canonical_digest_is_order_independent_for_mapping_keys() -> None:
    assert canonical_digest({"b": 2, "a": {"d": 4, "c": 3}}) == canonical_digest(
        {"a": {"c": 3, "d": 4}, "b": 2}
    )
    assert canonical_digest(envelope()).startswith("sha256:")
    with pytest.raises(ValueError, match="finite"):
        canonical_digest({"value": float("nan")})
    assert canonical_digest({"captured_at": CAPTURED_AT}) != canonical_digest(
        {"captured_at": "2026-08-12T18:30:00Z"}
    )


def test_validated_text_rejects_unicode_surrogates_before_hashing() -> None:
    surrogate = "\ud800"

    with pytest.raises(ValidationError, match="Unicode scalar"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title=surrogate,
            data={},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match="Unicode scalar"):
        ExternalContentRecord(
            record_id="actor-42",
            contribution_type="actor",
            title="Aster Vale",
            data={"description": surrogate},
            blob_ids=(),
            provenance=provenance(),
        )
    with pytest.raises(ValidationError, match="Unicode scalar"):
        preview(warnings=(surrogate,))
    with pytest.raises(ValidationError, match="Unicode scalar"):
        provenance(attribution=surrogate)
    with pytest.raises(ValueError, match="Unicode scalar"):
        canonical_digest({"unvalidated": surrogate})
    with pytest.raises(ValueError, match="Unicode scalar"):
        canonical_digest({surrogate: "unvalidated key"})


def test_import_commit_is_bound_to_the_exact_preview_and_revision() -> None:
    value = preview()
    source = envelope()
    value.require_envelope(source)
    commit = ImportCommit.for_preview(value, command_id="import-001")

    commit.require_matches(value)
    assert commit.preview_digest == canonical_digest(value)
    assert commit.expected_revision == 12
    assert commit.conflict_policy == "reject"
    commit.require_write_set(value.changes)

    changed = value.model_copy(update={"warnings": ("A warning appeared",)})
    with pytest.raises(ValueError, match="preview_digest"):
        commit.require_matches(changed)
    with pytest.raises(ValueError, match="expected_revision"):
        commit.model_copy(update={"expected_revision": 13}).require_matches(value)
    with pytest.raises(ValueError, match="envelope_digest"):
        value.require_envelope(
            source.model_copy(update={"provider_schema_version": "characters.v4"})
        )

    changed_write = value.changes[0].model_copy(
        update={"proposed_data": {"name": "Aster Vale", "armor_class": 99}}
    )
    with pytest.raises(ValueError, match="write_set_digest"):
        commit.require_write_set((changed_write,))


def test_verified_write_set_is_detached_and_recursively_immutable() -> None:
    source = envelope()
    change = ImportPreviewChange(
        operation="create",
        contribution_type="actor",
        external_record_id="actor-42",
        source_record_digest=canonical_digest(source.records[0]),
        target_id=None,
        proposed_data={
            "name": "Aster Vale",
            "abilities": {"strength": 10, "wisdom": 16},
            "tags": ["cleric", "level-3"],
        },
        summary="Create actor Aster Vale",
    )
    reviewed = preview(changes=(change,))
    commit = ImportCommit.for_preview(reviewed, command_id="import-immutable")
    declared_manifest = manifest()
    grant = integration_grant(declared_manifest)

    verified = commit.verify_for_execution(
        reviewed,
        manifest=declared_manifest,
        grant=grant,
        envelope=source,
        at=CAPTURED_AT + timedelta(minutes=1),
        api_version=1,
        current_revision=12,
    )

    assert isinstance(verified, VerifiedImportWriteSet)
    assert verified.command_id == commit.command_id
    assert verified.write_set_digest == commit.write_set_digest
    assert canonical_digest(verified.changes) == verified.write_set_digest
    verified_digest = canonical_digest(verified.changes)

    proposed_data = reviewed.changes[0].proposed_data
    assert proposed_data is not None
    proposed_data["name"] = "Mutated after verification"
    abilities = proposed_data["abilities"]
    assert isinstance(abilities, dict)
    abilities["strength"] = 99
    tags = proposed_data["tags"]
    assert isinstance(tags, list)
    tags.append("mutated")

    verified_data = verified.changes[0]["proposed_data"]
    assert verified_data["name"] == "Aster Vale"  # type: ignore[index]
    assert verified_data["abilities"]["strength"] == 10  # type: ignore[index]
    assert verified_data["tags"] == ("cleric", "level-3")  # type: ignore[index]
    assert canonical_digest(verified.changes) == verified_digest
    with pytest.raises(TypeError):
        verified.changes[0]["proposed_data"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        verified_data["name"] = "cannot mutate"  # type: ignore[index]

    with pytest.raises(ValueError, match="current_revision"):
        commit.verify_for_execution(
            reviewed.model_copy(
                update={
                    "changes": (change,),
                }
            ),
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
            current_revision=13,
        )
    with pytest.raises(ValueError, match="not active"):
        commit.verify_for_execution(
            reviewed.model_copy(
                update={
                    "changes": (change,),
                }
            ),
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(hours=2),
            api_version=1,
            current_revision=12,
        )


def test_execution_verification_strictly_revalidates_the_complete_model_graph() -> None:
    source = envelope()
    reviewed = preview()
    declared_manifest = manifest()
    grant = integration_grant(declared_manifest)

    duplicate_preview = reviewed.model_copy(
        update={"changes": (reviewed.changes[0], reviewed.changes[0])}
    )
    duplicate_commit = ImportCommit.for_preview(
        duplicate_preview,
        command_id="duplicate-write",
    )
    with pytest.raises(ValidationError, match="unique"):
        duplicate_commit.verify_for_execution(
            duplicate_preview,
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
            current_revision=12,
        )

    invalid_update = reviewed.changes[0].model_copy(
        update={"operation": "update", "target_id": None}
    )
    invalid_target_preview = reviewed.model_copy(update={"changes": (invalid_update,)})
    invalid_target_commit = ImportCommit.for_preview(
        invalid_target_preview,
        command_id="missing-target",
    )
    with pytest.raises(ValidationError, match="target_id"):
        invalid_target_commit.verify_for_execution(
            invalid_target_preview,
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
            current_revision=12,
        )

    overlong_grant = grant.model_copy(update={"expires_at": CAPTURED_AT + timedelta(days=365)})
    with pytest.raises(ValidationError, match="maximum lifetime"):
        ImportCommit.for_preview(reviewed, command_id="overlong-grant").verify_for_execution(
            reviewed,
            manifest=declared_manifest,
            grant=overlong_grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(days=180),
            api_version=1,
            current_revision=12,
        )

    with pytest.raises(ValueError, match="not active"):
        ImportCommit.for_preview(reviewed, command_id="expired-grant").verify_for_execution(
            reviewed,
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=grant.expires_at,
            api_version=1,
            current_revision=12,
        )

    orphan_record = source.records[0].model_copy(update={"blob_ids": ()})
    orphan_envelope = source.model_copy(update={"records": (orphan_record,)})
    orphan_change = reviewed.changes[0].model_copy(
        update={"source_record_digest": canonical_digest(orphan_record)}
    )
    orphan_preview = reviewed.model_copy(
        update={
            "envelope_digest": canonical_digest(orphan_envelope),
            "changes": (orphan_change,),
        }
    )
    orphan_commit = ImportCommit.for_preview(orphan_preview, command_id="orphan-blob")
    with pytest.raises(ValidationError, match="unreferenced blob"):
        orphan_commit.verify_for_execution(
            orphan_preview,
            manifest=declared_manifest,
            grant=grant,
            envelope=orphan_envelope,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
            current_revision=12,
        )


def test_repeated_execution_verification_does_not_reuse_frozen_proxy_data() -> None:
    reviewed = preview()
    source = envelope()
    declared_manifest = manifest()
    grant = integration_grant(declared_manifest)
    commit = ImportCommit.for_preview(reviewed, command_id="repeat-verification")

    first = commit.verify_for_execution(
        reviewed,
        manifest=declared_manifest,
        grant=grant,
        envelope=source,
        at=CAPTURED_AT + timedelta(minutes=1),
        api_version=1,
        current_revision=12,
    )
    second = commit.verify_for_execution(
        reviewed,
        manifest=declared_manifest,
        grant=grant,
        envelope=source,
        at=CAPTURED_AT + timedelta(minutes=1),
        api_version=1,
        current_revision=12,
    )

    assert first is not second
    assert first.changes is not second.changes
    assert canonical_digest(first.changes) == canonical_digest(second.changes)


def test_composed_authorization_binds_manifest_grant_provider_and_content() -> None:
    source = envelope()
    value = preview()
    declared_manifest = manifest()
    grant = IntegrationGrant(
        schema_version=INTEGRATION_GRANT_SCHEMA_VERSION,
        grant_id="grant-1",
        extension_id="org.example.safe-importer",
        manifest_digest=canonical_digest(declared_manifest),
        participant_id="gm-1",
        table_id="table-1",
        permissions=("actors:import",),
        provider_ids=("example-content",),
        contribution_types=("actor",),
        issued_at=CAPTURED_AT,
        expires_at=CAPTURED_AT + timedelta(hours=1),
        revoked_at=None,
        token_hash="sha256:" + "a" * 64,
    )

    value.require_authorized(
        manifest=declared_manifest,
        grant=grant,
        envelope=source,
        at=CAPTURED_AT + timedelta(minutes=1),
        api_version=1,
    )

    with pytest.raises(ValueError, match="provider"):
        value.require_authorized(
            manifest=declared_manifest,
            grant=grant,
            envelope=source.model_copy(update={"provider_id": "other-provider"}),
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
        )
    with pytest.raises(ValueError, match="not active"):
        value.require_authorized(
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(hours=2),
            api_version=1,
        )
    with pytest.raises(ValueError, match="participant_id"):
        value.model_copy(update={"participant_id": "other-gm"}).require_authorized(
            manifest=declared_manifest,
            grant=grant,
            envelope=source,
            at=CAPTURED_AT + timedelta(minutes=1),
            api_version=1,
        )
    with pytest.raises(ValueError, match="manifest_digest"):
        grant.model_copy(update={"manifest_digest": "sha256:" + "f" * 64}).require_manifest_scope(
            declared_manifest
        )


def test_preview_requires_an_exact_relationally_valid_write_for_each_record() -> None:
    source = envelope()
    value = preview()

    value.require_envelope(source)

    with pytest.raises(ValueError, match="exactly one change"):
        value.model_copy(update={"changes": ()}).require_envelope(source)
    with pytest.raises(ValueError, match="unknown external record"):
        value.model_copy(
            update={
                "changes": (value.changes[0].model_copy(update={"external_record_id": "missing"}),)
            }
        ).require_envelope(source)
    with pytest.raises(ValueError, match="contribution_type"):
        value.model_copy(
            update={
                "changes": (value.changes[0].model_copy(update={"contribution_type": "scene"}),)
            }
        ).require_envelope(source)
    with pytest.raises(ValueError, match="source_record_digest"):
        value.model_copy(
            update={
                "changes": (
                    value.changes[0].model_copy(
                        update={"source_record_digest": "sha256:" + "9" * 64}
                    ),
                )
            }
        ).require_envelope(source)


def test_preview_rejects_duplicate_targets_and_active_warning_content() -> None:
    first = ImportPreviewChange(
        operation="update",
        contribution_type="actor",
        external_record_id="actor-1",
        source_record_digest="sha256:" + "1" * 64,
        target_id="actor-existing",
        proposed_data={"name": "First"},
        summary="Update First",
    )
    second = ImportPreviewChange(
        operation="update",
        contribution_type="actor",
        external_record_id="actor-2",
        source_record_digest="sha256:" + "2" * 64,
        target_id="actor-existing",
        proposed_data={"name": "Second"},
        summary="Update Second",
    )
    with pytest.raises(ValidationError, match="target_id"):
        preview(changes=(first, second))
    with pytest.raises(ValidationError, match="HTML"):
        preview(warnings=("<script>alert(1)</script>",))


def test_write_operations_require_data_and_skip_operations_forbid_it() -> None:
    common = {
        "contribution_type": "actor",
        "external_record_id": "actor-1",
        "source_record_digest": "sha256:" + "1" * 64,
        "summary": "A reviewed change",
    }
    with pytest.raises(ValidationError, match="proposed_data"):
        ImportPreviewChange(operation="create", target_id=None, proposed_data=None, **common)
    with pytest.raises(ValidationError, match="proposed_data"):
        ImportPreviewChange(
            operation="skip",
            target_id="actor-existing",
            proposed_data={"name": "Hidden write"},
            **common,
        )


def test_integration_contract_module_has_no_dynamic_loading_or_runtime_io() -> None:
    module_path = Path(__file__).parents[1] / "src" / "dnd_sim" / "vtt" / "integration_contracts.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "dnd_sim.engine_runtime",
        "dnd_sim.io_runtime",
        "httpx",
        "importlib",
        "os",
        "pathlib",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
        "urllib",
    }

    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)

    assert not {
        imported
        for imported in imports
        if any(
            imported == root or imported.startswith(root + ".") for root in forbidden_import_roots
        )
    }
    assert calls.isdisjoint({"eval", "exec", "compile", "__import__"})
