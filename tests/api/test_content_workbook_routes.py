"""Authenticated XLSX transport keeps bytes out of metadata and browser authority out."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.routers.content_workbook_import import XLSX_MEDIA_TYPE
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_catalog_contracts.content_workbook_import import (
    CONTENT_WORKBOOK_MAX_BYTES,
    CONTENT_WORKBOOK_PROPOSAL_SCHEMA,
    CommitContentWorkbookRequest,
    ContentWorkbookImportResult,
    ContentWorkbookPreview,
    PrepareContentWorkbookRequest,
    ReadContentWorkbookRequest,
)
from eom_catalog_contracts.content_workbook_template import render_template
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.content_planning_fixtures import SHA, composition, identifier, source_target

BASE = "/api/v1/content-planning/imports"
KEY = "workbook-import-test-1234"


def proposal():
    return dict(
        artifact_id=identifier("artifact"),
        artifact_revision_id=identifier("rev"),
        member_path="proposal.json",
        schema_ref=CONTENT_WORKBOOK_PROPOSAL_SCHEMA,
        media_type="application/json",
        sha256=SHA,
    )


def preview(*, content: bytes = b"testxlsx", filename: str = "배치.xlsx"):
    return ContentWorkbookPreview.model_validate(
        dict(
            proposal=proposal(),
            original_filename=filename,
            workbook_sha256="sha256:" + hashlib.sha256(content).hexdigest(),
            metadata=dict(
                content_title="새 교재",
                content_type="TEXTBOOK",
                edition_label="초판",
                academic_year=2026,
                print_status="NOT_PRINTED",
                printed_on=None,
            ),
            total_rows=1,
            matched_rows=1,
            unresolved_rows=0,
            duplicate_uses=0,
            can_commit=True,
            offset=0,
            rows=[
                dict(
                    row=dict(
                        row_number=2,
                        group_label="1회",
                        section_label="본문",
                        display_number="1",
                        external_number="10321",
                        points_milli=None,
                        note="",
                    ),
                    resolution=dict(
                        row_number=2,
                        status="MATCHED",
                        title="고유번호 10321",
                        target=source_target(),
                    ),
                )
            ],
            next_offset=None,
        )
    )


def imported():
    value = composition([])
    return ContentWorkbookImportResult.model_validate(
        dict(
            disposition="IMPORTED",
            replayed=False,
            composition=value,
            current_revision_id=value["deliverable_revision_id"],
            print_record_id=None,
        )
    )


@pytest.fixture
def workbook_client():
    services = disconnected_services()
    catalog = SimpleNamespace(content_workbook=Mock(return_value=preview()))
    services.catalog_application, services.audit = catalog, Mock()
    app = create_app(services)
    state = SimpleNamespace(authentication=_authentication())

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, catalog, state
    services.engine.dispose()


def upload(client, content=b"testxlsx", **headers):
    return client.put(
        BASE,
        params={"original_filename": "배치.xlsx"},
        content=content,
        headers={"Content-Type": XLSX_MEDIA_TYPE, "Idempotency-Key": KEY, **headers},
    )


def test_template_download_is_blank_xlsx_and_does_not_call_catalog(workbook_client):
    client, catalog, _ = workbook_client
    response = client.get(BASE + "/template")
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.content == render_template()
    with ZipFile(BytesIO(response.content)) as archive:
        assert "xl/workbook.xml" in archive.namelist()
    catalog.content_workbook.assert_not_called()


def test_upload_stream_hash_length_and_identity_from_authenticated_request(workbook_client):
    client, catalog, state = workbook_client
    response = upload(client)
    assert response.status_code == 200, response.text
    command = catalog.content_workbook.call_args.args[0]
    assert isinstance(command, PrepareContentWorkbookRequest)
    assert command.actor_id == OPERATOR_ID
    assert command.session_id == state.authentication.session_id
    assert command.authentication_time == state.authentication.authenticated_at
    assert command.request_id == response.headers["x-request-id"]
    assert command.idempotency_key == KEY
    assert command.sha256 == "sha256:" + hashlib.sha256(b"testxlsx").hexdigest()
    assert catalog.content_workbook.call_args.kwargs == {"content": b"testxlsx"}
    assert "content" not in command.model_dump()


def test_query_is_metadata_only_and_commit_uses_pinned_proposal(workbook_client):
    client, catalog, _ = workbook_client
    response = client.post(BASE + "/query", json={"proposal": proposal()})
    assert response.status_code == 200, response.text
    query = catalog.content_workbook.call_args.args[0]
    assert isinstance(query, ReadContentWorkbookRequest)
    assert query.limit == 100 and query.offset == 0
    assert query.proposal.model_dump() == proposal()
    assert catalog.content_workbook.call_args.kwargs == {}
    catalog.content_workbook.return_value = imported()
    response = client.post(
        BASE + "/commit", json={"proposal": proposal()}, headers={"Idempotency-Key": KEY}
    )
    assert response.status_code == 200, response.text
    command = catalog.content_workbook.call_args.args[0]
    assert isinstance(command, CommitContentWorkbookRequest)
    assert command.proposal == query.proposal and command.idempotency_key == KEY


@pytest.mark.parametrize("route", ["/query", "/commit"])
@pytest.mark.parametrize("field,value", [("actor_id", OPERATOR_ID), ("permissions", ["ADMIN"])])
def test_browser_authority_is_rejected(workbook_client, route, field, value):
    client, catalog, _ = workbook_client
    response = client.post(
        BASE + route,
        json={"proposal": proposal(), field: value},
        headers={"Idempotency-Key": KEY},
    )
    assert response.status_code == 422
    catalog.content_workbook.assert_not_called()


@pytest.mark.parametrize(
    "permission",
    [PermissionKey.DELIVERABLE_READ, PermissionKey.ITEM_READ, PermissionKey.CONTENT_INTAKE_READ],
)
def test_source_read_permissions_required_before_download_upload_or_query(
    workbook_client, permission
):
    client, catalog, state = workbook_client
    state.authentication = replace(
        state.authentication, permissions=state.authentication.permissions - {permission}
    )
    assert client.get(BASE + "/template").status_code == 403
    assert upload(client).status_code == 403
    assert client.post(BASE + "/query", json={"proposal": proposal()}).status_code == 403
    assert (
        client.post(
            BASE + "/commit", json={"proposal": proposal()}, headers={"Idempotency-Key": KEY}
        ).status_code
        == 403
    )
    catalog.content_workbook.assert_not_called()


def test_read_only_operator_cannot_prepare_or_commit(workbook_client):
    client, catalog, state = workbook_client
    state.authentication = replace(
        state.authentication,
        permissions=state.authentication.permissions - {PermissionKey.DELIVERABLE_CREATE},
    )
    assert upload(client).status_code == 403
    assert (
        client.post(
            BASE + "/commit", json={"proposal": proposal()}, headers={"Idempotency-Key": KEY}
        ).status_code
        == 403
    )
    catalog.content_workbook.assert_not_called()
    assert client.post(BASE + "/query", json={"proposal": proposal()}).status_code == 200


def test_openapi_has_binary_upload_and_bounded_pointer_only_query(workbook_client):
    client, _, _ = workbook_client
    schema = client.app.openapi()
    routes = schema["paths"]
    upload_route = routes[BASE]["put"]
    assert upload_route["requestBody"]["required"] is True
    assert set(upload_route["requestBody"]["content"]) == {XLSX_MEDIA_TYPE}
    assert upload_route["x-eom-permission"] == PermissionKey.DELIVERABLE_CREATE.value
    query_route = routes[BASE + "/query"]["post"]
    assert query_route["x-eom-read-only"] is True
    query_properties = schema["components"]["schemas"]["ReadContentWorkbookInput"]["properties"]
    assert set(query_properties) == {"proposal", "offset", "limit"}
    assert query_properties["limit"]["maximum"] == 100


@pytest.mark.parametrize("route", ["", "/commit"])
def test_mutations_require_idempotency_key(workbook_client, route):
    client, catalog, _ = workbook_client
    if route:
        response = client.post(BASE + route, json={"proposal": proposal()})
    else:
        response = client.put(
            BASE,
            params={"original_filename": "test.xlsx"},
            content=b"testxlsx",
            headers={"Content-Type": XLSX_MEDIA_TYPE},
        )
    assert response.status_code == 400
    catalog.content_workbook.assert_not_called()


@pytest.mark.parametrize(
    "media_type", ["application/json", "application/octet-stream", "application/pdf"]
)
def test_only_explicit_xlsx_media_is_allowed(workbook_client, media_type):
    client, catalog, _ = workbook_client
    assert upload(client, **{"Content-Type": media_type}).status_code == 415
    catalog.content_workbook.assert_not_called()


@pytest.mark.parametrize("declared", ["7", "9"])
def test_declared_length_mismatch_rejected(workbook_client, declared):
    client, catalog, _ = workbook_client
    response = upload(client, **{"Content-Length": declared})
    assert response.status_code in {400, 422}
    catalog.content_workbook.assert_not_called()


def test_eight_mib_bound_and_chunked_upload_rejected(workbook_client):
    client, catalog, _ = workbook_client
    assert (
        upload(client, **{"Content-Length": str(CONTENT_WORKBOOK_MAX_BYTES + 1)}).status_code == 413
    )
    assert upload(client, **{"Transfer-Encoding": "chunked"}).status_code == 400
    catalog.content_workbook.assert_not_called()


@pytest.mark.parametrize("filename", ["../test.xlsx", "a\\test.xlsx", "a\x00.xlsx"])
def test_upload_filename_cannot_supply_path(workbook_client, filename):
    client, catalog, _ = workbook_client
    response = client.put(
        BASE,
        params={"original_filename": filename},
        content=b"testxlsx",
        headers={"Content-Type": XLSX_MEDIA_TYPE, "Idempotency-Key": KEY},
    )
    assert response.status_code == 422
    catalog.content_workbook.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        ("CONTENT_IMPORT_UNAVAILABLE", 503),
        ("CONTENT_PLANNING_PERMISSION_DENIED", 403),
        ("CONTENT_WORKBOOK_PROPOSAL_OWNER_MISMATCH", 403),
        ("CONTENT_WORKBOOK_REQUEST_INVALID", 400),
        ("CONTENT_WORKBOOK_ROWS_EMPTY", 400),
        ("CONTENT_WORKBOOK_FORMULA_FORBIDDEN", 400),
        ("CONTENT_WORKBOOK_UNRESOLVED", 409),
        ("CONTENT_WORKBOOK_REPLAY_CONFLICT", 409),
        ("CONTENT_WORKBOOK_UPLOAD_TIMEOUT", 408),
    ],
)
def test_catalog_stable_error_never_exposes_workbook_or_server_path(workbook_client, code, status):
    client, catalog, _ = workbook_client
    catalog.content_workbook.side_effect = CatalogApplicationClientError(
        code, "/private/source.xlsx"
    )
    response = client.post(BASE + "/query", json={"proposal": proposal()})
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert "/private/source.xlsx" not in response.text
