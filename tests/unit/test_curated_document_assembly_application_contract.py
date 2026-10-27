"""Private assembly create messages carry identity, never caller-supplied roles."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    CuratedDocumentAssemblyCreateCommandV1,
    CuratedDocumentAssemblyCreateResponseV1,
    CuratedDocumentAssemblyListEntryV1,
    CuratedDocumentAssemblyListQueryV1,
    CuratedDocumentAssemblyListResponseV1,
    CuratedDocumentAssemblyManifestV1,
    CuratedDocumentAssemblyReadQueryV1,
    CuratedDocumentAssemblyReadResponseV1,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _draft

ROOT = Path(__file__).resolve().parents[2]


def _command() -> CuratedDocumentAssemblyCreateCommandV1:
    return CuratedDocumentAssemblyCreateCommandV1(
        actor_id="operator_" + "1" * 32,
        session_id="apisession_" + "2" * 32,
        request_id="curated-create-1",
        authentication_time=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        idempotency_key="curated-create-key-1",
        draft=_draft().model_dump(mode="json"),
    )


def test_create_request_has_exact_schema_and_no_permission_field() -> None:
    payload = _command().model_dump(mode="json")
    validate_contract("catalog-curated-document-assembly-create-request-v1", payload)
    assert CuratedDocumentAssemblyCreateCommandV1.model_validate(payload) == _command()
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(
            "catalog-curated-document-assembly-create-request-v1",
            {**payload, "permissions": ["deliverable:create"]},
        )
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyCreateCommandV1.model_validate(
            {**payload, "draft": {"schema_version": "curated-document-assembly-draft/1.0"}}
        )


def test_create_response_is_pinned_input_not_hwp_delivery() -> None:
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    success = CuratedDocumentAssemblyCreateResponseV1(status="OK", manifest=manifest)
    validate_contract(
        "catalog-curated-document-assembly-create-response-v1",
        success.model_dump(mode="json", exclude_none=True),
    )
    failed = CuratedDocumentAssemblyCreateResponseV1(
        status="ERROR", error_code="CURATED_SOURCE_STALE"
    )
    validate_contract(
        "catalog-curated-document-assembly-create-response-v1",
        failed.model_dump(mode="json", exclude_none=True),
    )
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyCreateResponseV1(status="OK", error_code="CURATED_SOURCE_STALE")


def test_read_contract_is_owner_scoped_and_schema_pinned() -> None:
    for suffix in ("request", "response"):
        name = f"catalog-curated-document-assembly-read-{suffix}-v1.schema.json"
        assert (ROOT / "schemas/catalog-application" / name).read_bytes() == (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
            / name
        ).read_bytes()
    query = CuratedDocumentAssemblyReadQueryV1(
        actor_id="operator_" + "1" * 32,
        session_id="apisession_" + "2" * 32,
        request_id="curated-read-1",
        authentication_time=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        assembly_id="assembly_" + "1" * 32,
    )
    validate_contract(
        "catalog-curated-document-assembly-read-request-v1", query.model_dump(mode="json")
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(
            "catalog-curated-document-assembly-read-request-v1",
            {**query.model_dump(mode="json"), "permissions": ["admin"]},
        )
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    for response in (
        CuratedDocumentAssemblyReadResponseV1(status="OK", manifest=manifest),
        CuratedDocumentAssemblyReadResponseV1(
            status="ERROR", error_code="CURATED_ASSEMBLY_NOT_FOUND"
        ),
    ):
        validate_contract(
            "catalog-curated-document-assembly-read-response-v1",
            response.model_dump(mode="json", exclude_none=True),
        )


def test_list_contract_is_owner_scoped_and_bounded() -> None:
    for suffix in ("request", "response"):
        name = f"catalog-curated-document-assembly-list-{suffix}-v1.schema.json"
        assert (ROOT / "schemas/catalog-application" / name).read_bytes() == (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
            / name
        ).read_bytes()
    query = CuratedDocumentAssemblyListQueryV1(
        actor_id="operator_" + "1" * 32,
        session_id="apisession_" + "2" * 32,
        request_id="curated-list-1",
        authentication_time=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    )
    validate_contract(
        "catalog-curated-document-assembly-list-request-v1",
        query.model_dump(mode="json", exclude_none=True),
    )
    page_cursor = "1793100000000000|assembly_" + "a" * 32
    validate_contract(
        "catalog-curated-document-assembly-list-request-v1",
        query.model_copy(update={"cursor": page_cursor}).model_dump(mode="json", exclude_none=True),
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(
            "catalog-curated-document-assembly-list-request-v1",
            {**query.model_dump(mode="json", exclude_none=True), "permissions": ["admin"]},
        )
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    entry = CuratedDocumentAssemblyListEntryV1(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        created_at=manifest.created_at,
        placement_count=len(manifest.placements),
        manifest_sha256=manifest.manifest_sha256,
    )
    for response in (
        CuratedDocumentAssemblyListResponseV1(status="OK", values=(entry,)),
        CuratedDocumentAssemblyListResponseV1(
            status="OK", values=(entry,), next_cursor=page_cursor
        ),
        CuratedDocumentAssemblyListResponseV1(
            status="ERROR", values=(), error_code="CURATED_ASSEMBLY_PERMISSION_DENIED"
        ),
    ):
        validate_contract(
            "catalog-curated-document-assembly-list-response-v1",
            response.model_dump(mode="json", exclude_none=True),
        )
