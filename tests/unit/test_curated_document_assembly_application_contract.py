"""Private assembly create messages carry identity, never caller-supplied roles."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    CuratedDocumentAssemblyCreateCommandV1,
    CuratedDocumentAssemblyCreateResponseV1,
    CuratedDocumentAssemblyManifestV1,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _draft


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
