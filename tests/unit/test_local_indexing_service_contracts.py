"""Synthetic metadata only: no authenticated service, policy grant or runtime activation."""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import (
    LOCAL_INDEXING_SERVICE_SCHEMA_REF,
    MAX_LOCAL_INDEXING_SERVICE_BYTES,
    LocalIndexingServiceError,
    LocalIndexingServiceErrorCode,
    LocalIndexingServiceIdentity,
    LocalIndexingServiceReference,
    LocalIndexingServiceStatus,
    local_indexing_service_bytes,
    local_indexing_service_identity_sha256,
    local_indexing_service_reference,
    local_indexing_service_schema,
    parse_local_indexing_service_identity,
    parse_local_indexing_service_reference,
    parse_local_indexing_service_status,
    validate_local_indexing_service_current,
    validate_local_indexing_service_successor,
)
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SERVICE = "localindexservice_" + "1" * 32
REVISION = "localindexservicerev_" + "2" * 32


def identity_document(**changes: object) -> dict[str, Any]:
    values = {
        "schema_version": "local-indexing-service-identity/1.0",
        "service_id": SERVICE,
        "service_revision_id": REVISION,
        "previous_service_revision_id": None,
        "revision_number": 1,
        "purpose": "LOCAL_EMBEDDING_INDEX",
        "runtime_user": "eom-workflow-runner",
        "database_role": "synthetic_indexing_owner",
        "runtime_source_commit": "3" * 40,
        "created_at": "2026-10-14T00:00:00Z",
        "content_sha256": "sha256:" + "0" * 64,
    }
    values.update(changes)
    values["content_sha256"] = local_indexing_service_identity_sha256(values)
    return values


def identity(**changes: object) -> LocalIndexingServiceIdentity:
    return LocalIndexingServiceIdentity.model_validate(identity_document(**changes))


def status_document(**changes: object) -> dict[str, Any]:
    values = {
        "schema_version": "local-indexing-service-status/1.0",
        "service_id": SERVICE,
        "state": "ACTIVE",
        "current": local_indexing_service_reference(identity()).model_dump(mode="json"),
        "resource_version": 1,
        "updated_at": "2026-10-14T00:00:01Z",
    }
    values.update(changes)
    return values


def test_schema_mirror_package_resource_and_independent_copy() -> None:
    raw = (ROOT / "schemas/identity/local-indexing-service-v1.schema.json").read_bytes()
    packaged = (
        ROOT
        / "packages/operator_identity/eom_operator_identity/resources"
        / "local-indexing-service-v1.schema.json"
    )
    assert packaged.read_bytes() == raw
    assert hashlib.sha256(raw).hexdigest() == (
        "dc7de7cef0239b48096609c79f4f08c976e272640d89b42a33ff8634bb835807"
    )
    schema = local_indexing_service_schema()
    assert schema == json.loads(raw)
    assert schema["$id"] == LOCAL_INDEXING_SERVICE_SCHEMA_REF
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for value in (
        identity_document(),
        local_indexing_service_reference(identity()).model_dump(mode="json"),
        status_document(),
    ):
        validator.validate(value)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert (
        "resources/local-indexing-service-v1.schema.json"
        in (project["tool"]["setuptools"]["package-data"]["eom_operator_identity"])
    )
    schema["$defs"]["identity"]["properties"]["purpose"]["const"] = "ADMIN"
    assert local_indexing_service_schema()["$defs"]["identity"]["properties"]["purpose"] == {
        "const": "LOCAL_EMBEDDING_INDEX"
    }


def test_content_hash_timestamp_normalization_and_exact_canonical_wire() -> None:
    document = identity_document()
    original = deepcopy(document)
    checked = LocalIndexingServiceIdentity.model_validate(document)
    assert document == original
    normalized = {**document, "created_at": "2026-10-14T00:00:00.000000Z"}
    body = {key: value for key, value in normalized.items() if key != "content_sha256"}
    assert checked.content_sha256 == content_sha256(body)
    assert local_indexing_service_identity_sha256(checked) == checked.content_sha256
    assert local_indexing_service_bytes(checked) == canonical_json_bytes(normalized)
    assert parse_local_indexing_service_identity(local_indexing_service_bytes(checked)) == checked
    ref = local_indexing_service_reference(checked)
    assert parse_local_indexing_service_reference(local_indexing_service_bytes(ref)) == ref
    status = LocalIndexingServiceStatus.model_validate(status_document())
    assert parse_local_indexing_service_status(local_indexing_service_bytes(status)) == status
    assert local_indexing_service_bytes(identity(created_at="2026-10-14T00:00:00.0Z")) == (
        local_indexing_service_bytes(checked)
    )
    with pytest.raises(ValueError, match="canonical"):
        parse_local_indexing_service_identity(canonical_json_bytes(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "operator_" + "1" * 32),
        ("service_id", "localindexservice_" + "A" * 32),
        ("service_revision_id", "localindexservicerev_" + "2" * 31),
        ("schema_version", "local-indexing-service-identity/2.0"),
        ("purpose", "LOCAL_EMBEDDING_QUERY"),
        ("runtime_user", "root"),
        ("database_role", "ADMIN"),
        ("database_role", "role; SET ROLE admin"),
        ("database_role", "synthetic_owner\n"),
        ("database_role", "a" * 64),
        ("runtime_source_commit", "3" * 39),
        ("runtime_source_commit", "latest"),
        ("runtime_source_commit", "a" * 39 + "A"),
        ("created_at", "2026-10-14T00:00:00+00:00"),
        ("created_at", "2026-10-14T09:00:00+09:00"),
        ("created_at", "2026-02-30T00:00:00Z"),
        ("created_at", "2026-10-14T00:00:00.1234567Z"),
        ("created_at", datetime(2026, 10, 14)),
        (
            "created_at",
            datetime(2026, 10, 14, tzinfo=UTC).astimezone(timezone(timedelta(hours=9))),
        ),
        ("content_sha256", "sha256:" + "a" * 63),
        ("previous_service_revision_id", REVISION),
    ],
)
def test_schema_rejects_invalid_identity_before_hash_or_behavior(field: str, value: object) -> None:
    document = identity_document()
    document[field] = value
    with pytest.raises(ValueError):
        LocalIndexingServiceIdentity.model_validate(document)


@pytest.mark.parametrize("value", [True, False, "1", 1.0, 0, -1, 2147483648, None])
def test_versions_are_exact_bounded_integers(value: object) -> None:
    document = identity_document()
    document["revision_number"] = value
    with pytest.raises(ValueError):
        LocalIndexingServiceIdentity.model_validate(document)
    head = status_document(resource_version=value)
    with pytest.raises(ValueError):
        LocalIndexingServiceStatus.model_validate(head)


@pytest.mark.parametrize(
    "field", ["password", "token", "permissions", "roles", "source_grant", "operator_id", "path"]
)
def test_identity_reference_status_forbid_credentials_and_synthetic_authority(field: str) -> None:
    values = (
        (LocalIndexingServiceIdentity, identity_document()),
        (LocalIndexingServiceReference, local_indexing_service_reference(identity()).model_dump()),
        (LocalIndexingServiceStatus, status_document()),
    )
    for model, document in values:
        document[field] = "FORBIDDEN"
        with pytest.raises(ValueError):
            model.model_validate(document)


@pytest.mark.parametrize("field", ["database_role", "runtime_source_commit", "service_id"])
def test_identity_content_mutation_without_rehash_fails(field: str) -> None:
    document = identity_document()
    changes = {
        "database_role": "other_synthetic_owner",
        "runtime_source_commit": "4" * 40,
        "service_id": "localindexservice_" + "a" * 32,
    }
    document[field] = changes[field]
    with pytest.raises(ValueError, match="content hash"):
        LocalIndexingServiceIdentity.model_validate(document)


def test_revision_chain_is_exact_monotonic_and_not_activation() -> None:
    original = identity()
    successor = identity(
        service_revision_id="localindexservicerev_" + "4" * 32,
        previous_service_revision_id=original.service_revision_id,
        revision_number=2,
        runtime_source_commit="5" * 40,
        created_at="2026-10-14T00:00:02Z",
    )
    assert validate_local_indexing_service_successor(original, successor) == successor
    assert not hasattr(successor, "state")
    assert not hasattr(successor, "permissions")
    disabled = LocalIndexingServiceStatus.model_validate(
        status_document(state="DISABLED", current=None)
    )
    with pytest.raises(LocalIndexingServiceError) as error:
        validate_local_indexing_service_current(disabled, successor)
    assert error.value.code == LocalIndexingServiceErrorCode.INACTIVE
    for changes in (
        {"service_id": "localindexservice_" + "6" * 32},
        {"previous_service_revision_id": "localindexservicerev_" + "7" * 32},
        {"revision_number": 3},
        {"created_at": "2026-10-13T23:59:59Z"},
    ):
        document = successor.model_dump(mode="json")
        document.update(changes)
        document["content_sha256"] = local_indexing_service_identity_sha256(document)
        with pytest.raises(LocalIndexingServiceError) as error:
            validate_local_indexing_service_successor(
                original, LocalIndexingServiceIdentity.model_validate(document)
            )
        assert error.value.code == LocalIndexingServiceErrorCode.REVISION_CONFLICT
    with pytest.raises(LocalIndexingServiceError):
        validate_local_indexing_service_successor(original, original)
    with pytest.raises(ValueError, match="own predecessor"):
        identity(
            previous_service_revision_id=REVISION,
            revision_number=2,
        )


def test_active_metadata_requires_exact_identity_not_latest_or_foreign_service() -> None:
    current = identity()
    head = LocalIndexingServiceStatus.model_validate(status_document())
    assert validate_local_indexing_service_current(head, current) == current
    other = identity(runtime_source_commit="7" * 40)
    with pytest.raises(LocalIndexingServiceError) as error:
        validate_local_indexing_service_current(head, other)
    assert error.value.code == LocalIndexingServiceErrorCode.STALE_REVISION
    for invalid in (
        status_document(current=None),
        status_document(service_id="localindexservice_" + "9" * 32),
        status_document(state="RELEASED"),
    ):
        with pytest.raises(ValueError):
            LocalIndexingServiceStatus.model_validate(invalid)
    retained = LocalIndexingServiceStatus.model_validate(status_document(state="DISABLED"))
    assert retained.current == head.current
    with pytest.raises(LocalIndexingServiceError) as error:
        validate_local_indexing_service_current(retained, current)
    assert error.value.code == LocalIndexingServiceErrorCode.INACTIVE
    old_head = LocalIndexingServiceStatus.model_validate(
        status_document(updated_at="2026-10-13T23:59:59Z")
    )
    with pytest.raises(LocalIndexingServiceError, match="predates"):
        validate_local_indexing_service_current(old_head, current)


def test_missing_fields_and_forged_copied_models_are_revalidated_before_serialization() -> None:
    for model in (
        identity(),
        local_indexing_service_reference(identity()),
        LocalIndexingServiceStatus.model_validate(status_document()),
    ):
        for field in type(model).model_fields:
            document = model.model_dump()
            del document[field]
            with pytest.raises(ValueError):
                type(model).model_validate(document)
        forged = model.model_copy(update={"permissions": ["ADMIN"]})
        with pytest.raises(ValueError, match="extra fields"):
            local_indexing_service_bytes(forged)
    nested = LocalIndexingServiceStatus.model_validate(status_document())
    assert nested.current is not None
    nested_forgery = nested.model_copy(
        update={"current": nested.current.model_copy(update={"permissions": ["ADMIN"]})}
    )
    with pytest.raises(ValueError, match="extra fields"):
        local_indexing_service_bytes(nested_forgery)
    invalid_hash = identity().model_copy(update={"content_sha256": "sha256:" + "f" * 64})
    for action in (
        lambda: local_indexing_service_bytes(invalid_hash),
        lambda: local_indexing_service_reference(invalid_hash),
        lambda: validate_local_indexing_service_current(nested, invalid_hash),
    ):
        with pytest.raises(ValueError, match="content hash"):
            action()


def test_immutable_metadata_and_validation_errors_do_not_echo_extra_input() -> None:
    checked = identity()
    with pytest.raises(ValueError, match="frozen"):
        checked.database_role = "other_owner"
    document = identity_document()
    document["token"] = "MUST_NOT_APPEAR_IN_ERROR"
    with pytest.raises(ValueError) as error:
        LocalIndexingServiceIdentity.model_validate(document)
    assert "MUST_NOT_APPEAR_IN_ERROR" not in str(error.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b"{",
        b'{"service_id":"first","service_id":"second"}',
        b'{"resource_version":NaN}',
        b'{"nested":' * 1100 + b"{}" + b"}" * 1100,
        b" " * (MAX_LOCAL_INDEXING_SERVICE_BYTES + 1),
    ],
)
def test_wire_rejects_duplicate_nonfinite_nested_and_oversized_input(raw: bytes) -> None:
    for parser in (
        parse_local_indexing_service_identity,
        parse_local_indexing_service_reference,
        parse_local_indexing_service_status,
    ):
        with pytest.raises(ValueError):
            parser(raw)


def test_wire_rejects_nested_duplicate_keys_and_noncanonical_representation() -> None:
    head = LocalIndexingServiceStatus.model_validate(status_document())
    raw = local_indexing_service_bytes(head)
    duplicate = raw.replace(b'"current":{', b'"current":{"service_id":"bad",', 1)
    with pytest.raises(ValueError, match="duplicate"):
        parse_local_indexing_service_status(duplicate)
    with pytest.raises(ValueError, match="canonical"):
        parse_local_indexing_service_status(b" " + raw)
    with pytest.raises(ValueError, match="immutable bytes"):
        parse_local_indexing_service_status(bytearray(raw))  # type: ignore[arg-type]


def test_contract_has_no_database_runtime_or_authentication_adapters() -> None:
    source = ROOT / "packages/operator_identity/eom_operator_identity/local_indexing_service.py"
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        module.startswith(
            ("eom_identity_service", "eom_catalog_service", "sqlalchemy", "subprocess")
        )
        for module in imports
    )
    assert not {"admit", "authenticate", "activate", "grant", "mint"} & {
        name for name in dir(__import__("eom_operator_identity")) if not name.startswith("_")
    }
