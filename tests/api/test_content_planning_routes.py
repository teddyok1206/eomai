"""Public content transport uses the existing authentication and Catalog owner."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts.content_planning_commands import (
    ContentPlanningWriteResult,
    CreatePlannedContent,
)
from eom_catalog_contracts.content_planning_queries import (
    ContentEditionView,
    PlannedContentList,
    ReadContentEdition,
)
from eom_catalog_service.content_planning_dispatch import dispatch_content_planning
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.content_planning_fixtures import composition, identifier, slot
from tests.unit.test_curated_document_assembly_resolution import _actor


def command():
    value = composition([])
    return CreatePlannedContent.model_validate(
        {
            "command_kind": "CREATE_CONTENT",
            "sections": [],
            **{
                key: value[key]
                for key in ("content_title", "content_type", "edition_label", "academic_year")
            },
        }
    )


def result():
    value = composition([])
    return ContentPlanningWriteResult.model_validate(
        dict(
            disposition="SAVED",
            replayed=False,
            composition=value,
            current_revision_id=value["deliverable_revision_id"],
        )
    )


@pytest.fixture
def planning_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        write_content_planning=Mock(return_value=result()),
        query_content_planning=Mock(return_value=PlannedContentList(rows=(), next_id=None)),
        record_content_print=Mock(),
    )
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


def test_create_and_read_use_actual_authenticated_actor(planning_client):
    client, catalog, _ = planning_client
    reply = client.post(
        "/api/v1/content-planning/commands",
        json=command().model_dump(mode="json"),
        headers={"Idempotency-Key": "content-create-test-1234"},
    )
    assert reply.status_code == 200, reply.text
    assert catalog.write_content_planning.call_args.kwargs["actor"].operator_id == OPERATOR_ID
    assert reply.json()["data"]["composition"]["sections"] == []
    reply = client.post(
        "/api/v1/content-planning/query",
        json=dict(
            query_kind="LIST_CONTENTS",
            text="학교",
            limit=20,
            after_id=None,
        ),
    )
    assert reply.status_code == 200, reply.text
    assert catalog.query_content_planning.call_args.kwargs["actor"].operator_id == OPERATOR_ID


@pytest.mark.parametrize("field,value", [("actor_id", OPERATOR_ID), ("permissions", ["ADMIN"])])
def test_browser_cannot_supply_authority(planning_client, field, value):
    client, catalog, _ = planning_client
    reply = client.post(
        "/api/v1/content-planning/commands",
        json={
            **command().model_dump(mode="json"),
            field: value,
        },
        headers={"Idempotency-Key": "content-create-test-1234"},
    )
    assert reply.status_code == 422
    catalog.write_content_planning.assert_not_called()


def test_missing_key_and_item_permission_reject_before_owner(planning_client):
    client, catalog, state = planning_client
    reply = client.post("/api/v1/content-planning/commands", json=command().model_dump(mode="json"))
    assert reply.status_code == 400
    state.authentication = replace(
        state.authentication, permissions=frozenset({PermissionKey.DELIVERABLE_READ})
    )
    reply = client.post(
        "/api/v1/content-planning/commands",
        json=command().model_dump(mode="json"),
        headers={"Idempotency-Key": "content-create-test-1234"},
    )
    assert reply.status_code == 403
    reply = client.post(
        "/api/v1/content-planning/query",
        json=dict(
            query_kind="LIST_CONTENTS",
            text="",
            limit=20,
            after_id=None,
        ),
    )
    assert reply.status_code == 403
    catalog.write_content_planning.assert_not_called()
    catalog.query_content_planning.assert_not_called()


def test_1200_slot_command_survives_public_http_boundary(planning_client):
    client, catalog, _ = planning_client
    data = composition()
    reply = client.post(
        "/api/v1/content-planning/commands",
        json=dict(
            command_kind="EDIT_EDITION",
            edition_id=data["edition_id"],
            edit=dict(
                change_kind="SAVE_SECTIONS",
                expected_revision_id=data["deliverable_revision_id"],
                expected_sha256=data["composition_sha256"],
                changes=[
                    dict(
                        section_id=data["sections"][0]["section_id"],
                        before_assembly_revision_id=data["sections"][0]["form"][
                            "assembly_revision_id"
                        ],
                        before_manifest_sha256=data["sections"][0]["form"]["manifest_sha256"],
                        placements=[
                            {**slot(i), "note": "검토 메모 " * 100} for i in range(1, 1201)
                        ],
                    )
                ],
            ),
        ),
        headers={"Idempotency-Key": "content-1200-test-1234"},
    )
    assert reply.status_code == 200, reply.text
    assert len(catalog.write_content_planning.call_args.args[0].edit.changes[0].placements) == 1200


def test_client_dispatch_closed_roundtrip_and_no_client_roles(monkeypatch):
    import json

    service = Mock()
    service.execute.return_value = result()
    client = CatalogApplicationClient()
    captured = []

    def transport(payload, **_):
        captured.append(payload)
        return json.loads(dispatch_content_planning(service, payload))

    monkeypatch.setattr(client, "_raw_request", transport)
    actor = _actor(PermissionKey.DELIVERABLE_CREATE)
    saved = client.write_content_planning(
        command(), actor=actor, idempotency_key="content-roundtrip-1234"
    )
    assert saved == result()
    assert "permissions" not in captured[0] and "roles" not in captured[0]
    actual = service.execute.call_args.kwargs["actor"]
    assert actual.operator_id == actor.operator_id and not actual.permissions
    malicious = {**captured[0], "permissions": ["ADMIN"]}
    assert (
        json.loads(dispatch_content_planning(service, malicious))["error_code"]
        == "CONTENT_PLANNING_REQUEST_INVALID"
    )


def test_client_rejects_valid_but_unrelated_reply(monkeypatch):
    client = CatalogApplicationClient()
    value = composition([], edition_id=identifier("edition", 5))
    view = ContentEditionView.model_validate(
        dict(
            composition=value,
            current_revision_id=value["deliverable_revision_id"],
        )
    )
    monkeypatch.setattr(
        client,
        "_raw_request",
        lambda *_args, **_kwargs: dict(
            operation="CONTENT_PLANNING_QUERY",
            status="OK",
            result=view.model_dump(mode="json"),
            error_code=None,
        ),
    )
    with pytest.raises(CatalogApplicationClientError):
        client.query_content_planning(
            ReadContentEdition(
                query_kind="READ_EDITION",
                edition_id=identifier("edition"),
                revision_id=None,
            ),
            actor=_actor(PermissionKey.DELIVERABLE_READ),
        )


def test_print_route_is_explicit_user_fact_and_audited(planning_client):
    from tests.unit.test_content_planning_read_contracts import print_example

    client, catalog, _ = planning_client
    command, result = print_example()
    catalog.record_content_print.return_value = result
    reply = client.post(
        "/api/v1/content-planning/prints",
        json=command.model_dump(mode="json"),
        headers={"Idempotency-Key": "content-print-test-1234"},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["data"]["record"]["origin"] == "USER_RECORDED"
    assert catalog.record_content_print.call_args.kwargs["actor"].operator_id == OPERATOR_ID
