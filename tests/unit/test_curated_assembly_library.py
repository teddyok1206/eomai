"""Titled draft/list/removal wire contracts retain immutable V1 selection semantics."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_draft import CuratedDocumentAssemblyDraftV1
from eom_catalog_contracts.curated_document_assembly_library import (
    LIBRARY_SCHEMA,
    CuratedDocumentAssemblyCreateCommandV2,
    CuratedDocumentAssemblyCreateResponseV2,
    CuratedDocumentAssemblyDraftV2,
    CuratedDocumentAssemblyListEntryV2,
    CuratedDocumentAssemblyListQueryV2,
    CuratedDocumentAssemblyListResponseV2,
    CuratedDocumentAssemblyRemovalInput,
    CuratedDocumentAssemblyRemovalReceipt,
    CuratedDocumentAssemblyRemoveCommandV1,
    CuratedDocumentAssemblyRemoveResponseV1,
    parse_curated_library_request,
    parse_curated_library_response,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.curated_document_assembly_library_dispatch import (
    dispatch_curated_assembly_library,
)
from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyError
from eom_identifiers import content_sha256
from eom_operator_identity import ActorSource
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_curated_document_assembly_application_contract import _command
from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _draft


def titled(title="통합과학 1회"):
    return CuratedDocumentAssemblyDraftV2.model_validate(
        _draft().model_dump(mode="json")
        | dict(schema_version="curated-document-assembly-draft/2.0", title=title)
    )


def commands():
    original = _command().model_dump(mode="json", exclude={"operation", "draft"})
    create = CuratedDocumentAssemblyCreateCommandV2(**original, draft=titled())
    auth = {key: value for key, value in original.items() if key != "idempotency_key"}
    listed = CuratedDocumentAssemblyListQueryV2(**auth)
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    selection = CuratedDocumentAssemblyRemovalInput(
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    removed = CuratedDocumentAssemblyRemoveCommandV1(
        **original, assembly_id=manifest.assembly_id, selection=selection
    )
    return create, listed, removed


def test_title_never_changes_released_selection_bytes_or_placement_hash():
    value = titled()
    validate_contract("curated-document-assembly-draft-v2", value.model_dump(mode="json"))
    assert value.selection() == _draft()
    assert content_sha256(value.selection().model_dump(mode="json")) == content_sha256(
        _draft().model_dump(mode="json")
    )
    with pytest.raises(ValueError):
        CuratedDocumentAssemblyDraftV1.model_validate(value.model_dump(mode="json"))


@pytest.mark.parametrize("title", ("a" * 201, "끝\n", "첫\r줄", "탭\t문자"))
def test_invalid_title_is_rejected_by_both_explicit_schema_and_typed_value(title):
    value = _draft().model_dump(mode="json") | dict(
        schema_version="curated-document-assembly-draft/2.0", title=title
    )
    with pytest.raises((SchemaError, ValueError)):
        validate_contract("curated-document-assembly-draft-v2", value)
    with pytest.raises(ValueError):
        CuratedDocumentAssemblyDraftV2.model_validate(value)


@pytest.mark.parametrize("command", commands())
def test_closed_library_requests_do_not_grant_roles_or_accept_an_implicit_revision(command):
    value = command.model_dump(mode="json")
    assert parse_curated_library_request(value) == command
    with pytest.raises((SchemaError, ValueError)):
        parse_curated_library_request(value | {"permissions": ["admin"]})
    with pytest.raises((SchemaError, ValueError)):
        parse_curated_library_request(value | {"actor_id": "WORKER"})


def test_library_success_errors_and_legacy_list_have_distinct_closed_shapes():
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    entry = CuratedDocumentAssemblyListEntryV2(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        title="시험지",
        manifest_sha256=manifest.manifest_sha256,
        created_at=manifest.created_at,
        placement_count=len(manifest.placements),
    )
    receipt = CuratedDocumentAssemblyRemovalReceipt(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        removed_at=manifest.created_at,
    )
    for result in (
        CuratedDocumentAssemblyCreateResponseV2(status="OK", manifest=manifest),
        CuratedDocumentAssemblyCreateResponseV2(status="ERROR", error_code="CURATED_SOURCE_STALE"),
        CuratedDocumentAssemblyListResponseV2(status="OK", values=(entry,)),
        CuratedDocumentAssemblyListResponseV2(
            status="ERROR", values=(), error_code="CURATED_ASSEMBLY_NOT_FOUND"
        ),
        CuratedDocumentAssemblyRemoveResponseV1(status="OK", receipt=receipt),
        CuratedDocumentAssemblyRemoveResponseV1(
            status="ERROR", error_code="CURATED_ASSEMBLY_NOT_FOUND"
        ),
    ):
        value = result.model_dump(mode="json")
        validate_contract(LIBRARY_SCHEMA, value)
        assert parse_curated_library_response(value) == result
        with pytest.raises((SchemaError, ValueError)):
            parse_curated_library_response(value | {"status": "OK", "error_code": "BAD_CODE"})
    with pytest.raises(SchemaError):
        validate_contract(
            "catalog-curated-document-assembly-list-response-v1",
            dict(
                operation="LIST_CURATED_DOCUMENT_ASSEMBLIES",
                status="OK",
                values=[entry.model_dump(mode="json")],
            ),
        )


@pytest.mark.parametrize("command", commands())
def test_adapter_passes_actual_api_identity_to_the_existing_service_and_preserves_errors(command):
    service = SimpleNamespace(
        create=Mock(side_effect=CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")),
        list_recent_titled=Mock(
            side_effect=CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
        ),
        remove_from_list=Mock(
            side_effect=CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
        ),
    )
    response = parse_curated_library_response(
        json.loads(dispatch_curated_assembly_library(service, command.model_dump(mode="json")))
    )
    assert (
        response.status == "ERROR" and response.error_code == "CURATED_ASSEMBLY_PERMISSION_DENIED"
    )
    called = [
        method
        for method in (service.create, service.list_recent_titled, service.remove_from_list)
        if method.called
    ]
    assert len(called) == 1
    actor = called[0].call_args.kwargs["actor"]
    assert actor.actor_id == command.actor_id and not actor.permissions
    assert actor.source is ActorSource.APPLICATION_API
    denied = json.loads(dispatch_curated_assembly_library(None, command.model_dump(mode="json")))
    assert denied["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
