"""Source-only Item DB routes retain both Item and Intake read permissions."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.pagination import PageResult
from eom_api_contracts.external_item_db import ExternalItemDbEntryView
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ID = "extitem_" + "1" * 32
REVISION_ID = "extitemrev_" + "2" * 32


def _entry() -> ExternalItemDbEntryView:
    return ExternalItemDbEntryView(
        source_id=SOURCE_ID,
        source_revision_id=REVISION_ID,
        external_number="12345",
        observation_sha256="sha256:" + "3" * 64,
        match_status="MATCHED",
        selected_filename="문항_12345.hwp",
    )


def _client(*, allow_intake: bool = True):
    services = disconnected_services()
    reads = SimpleNamespace(
        list=Mock(return_value=PageResult((_entry(),), None, False)),
        detail=Mock(),
        export=Mock(),
    )
    services.external_item_db_reads = reads
    app = create_app(services)

    def authenticated(request: Request):
        value = _authentication(admin=True)
        if not allow_intake:
            value = replace(
                value,
                permissions=value.permissions - {PermissionKey.CONTENT_INTAKE_READ},
            )
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, reads


def test_source_list_shows_business_number_but_not_internal_import_keys() -> None:
    client, services, reads = _client()
    try:
        with client:
            response = client.get("/api/v1/item-db/external-sources?limit=50")
        assert response.status_code == 200
        entry = response.json()["data"][0]
        assert entry["source_id"] == SOURCE_ID
        assert entry["external_number"] == "12345"
        assert "import_id" not in entry
        assert entry["similarity_state"] == "NOT_INDEXED"
        assert entry["graph_state"] == "NOT_PUBLISHED"
        reads.list.assert_called_once_with(
            exact_number=None,
            major_unit=None,
            field_label=None,
            match_status=None,
            limit=50,
            cursor=None,
        )
    finally:
        services.engine.dispose()


def test_intake_permission_is_required_before_source_read() -> None:
    client, services, reads = _client(allow_intake=False)
    try:
        with client:
            response = client.get("/api/v1/item-db/external-sources")
        assert response.status_code == 403
        reads.list.assert_not_called()
    finally:
        services.engine.dispose()


def test_schema_2020_12_and_pydantic_agree_on_entry() -> None:
    schema = json.loads(
        (
            ROOT
            / "packages/api_contracts/eom_api_contracts/schemas"
            / "external-item-db-view-v1.schema.json"
        )
        .read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema["$defs"]["entry"]).validate(_entry().model_dump(mode="json"))


def test_bounded_advanced_search_uses_same_permission_and_filter_contract() -> None:
    client, services, reads = _client()
    body = {
        "schema_version": "external-item-db-filter/1.0",
        "match_mode": "ALL",
        "conditions": [
            {"field": "U", "operator": "EQ", "value": "12345"},
            {"field": "Q", "operator": "CONTAINS", "value": "물질"},
        ],
        "limit": 50,
        "cursor": None,
    }
    try:
        with client:
            response = client.post("/api/v1/item-db/external-sources/search", json=body)
        assert response.status_code == 200
        assert response.json()["data"][0]["external_number"] == "12345"
        assert reads.list.call_args.kwargs["advanced"].conditions[0].field == "U"
        body["conditions"][0]["value"] = "42"
        with client:
            invalid = client.post("/api/v1/item-db/external-sources/search", json=body)
        assert invalid.status_code == 422
    finally:
        services.engine.dispose()


def test_filter_schema_is_2020_12_and_matches_request() -> None:
    schema = json.loads(
        (
            ROOT
            / "packages/api_contracts/eom_api_contracts/schemas"
            / "external-item-db-filter-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "schema_version": "external-item-db-filter/1.0",
            "match_mode": "ALL",
            "conditions": [{"field": "U", "operator": "EQ", "value": "12345"}],
            "limit": 50,
            "cursor": None,
        }
    )


def test_excel_export_is_permission_gated_and_returns_pinned_bytes() -> None:
    client, services, reads = _client()
    services.audit.append = Mock()
    reads.export.return_value = SimpleNamespace(
        payload=b"PK\x03\x04test-xlsx",
        sha256="sha256:" + "4" * 64,
        row_count=1,
    )
    body = {
        "schema_version": "external-item-db-filter/1.0",
        "match_mode": "ALL",
        "conditions": [{"field": "U", "operator": "EQ", "value": "12345"}],
        "limit": 50,
        "cursor": None,
    }
    try:
        with client:
            response = client.post("/api/v1/item-db/external-sources/export", json=body)
        assert response.status_code == 200
        assert response.content.startswith(b"PK\x03\x04")
        assert response.headers["x-eom-row-count"] == "1"
        assert reads.export.call_args.args[0].conditions[0].field == "U"
    finally:
        services.engine.dispose()

    denied_client, denied_services, denied_reads = _client(allow_intake=False)
    try:
        with denied_client:
            denied = denied_client.post("/api/v1/item-db/external-sources/export", json=body)
        assert denied.status_code == 403
        denied_reads.export.assert_not_called()
    finally:
        denied_services.engine.dispose()


def test_original_document_download_uses_pinned_revision_and_authenticated_catalog() -> None:
    client, services, reads = _client()
    reads.detail.return_value = SimpleNamespace(entry=_entry())
    services.audit.append = Mock()
    media = SimpleNamespace(
        media_type="application/vnd.hancom.hwpx",
        content_length=8,
        sha256="sha256:" + "4" * 64,
        filename="원본문항_12345.hwpx",
        iter_chunks=lambda: iter((b"test-hwp",)),
    )
    services.catalog_application.download_external_item_document = Mock(return_value=media)
    path = f"/api/v1/item-db/external-sources/{SOURCE_ID}/editions/3/download"
    try:
        with client:
            stale = client.get(path, params={"source_revision_id": "extitemrev_" + "9" * 32})
            assert stale.status_code == 409
            response = client.get(path, params={"source_revision_id": REVISION_ID})
        assert response.status_code == 200
        assert response.content == b"test-hwp"
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        services.catalog_application.download_external_item_document.assert_called_once_with(
            SOURCE_ID, REVISION_ID, 3
        )
    finally:
        services.engine.dispose()
