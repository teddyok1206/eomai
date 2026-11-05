"""Actual authenticated routing, with synthetic metadata instead of production DB."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_catalog_contracts.knowledge_map import KnowledgeMapView
from eom_operator_identity import PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.test_knowledge_map_read import view_document


def authentication():
    original = _authentication()
    permissions = frozenset(
        {
            PermissionKey.KNOWLEDGE_GRAPH_READ,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            PermissionKey.ITEM_READ,
            PermissionKey.CONTENT_INTAKE_READ,
        }
    )
    return replace(
        original,
        operator=original.operator.model_copy(update={"roles": (RoleKey.ADMIN,)}),
        permissions=permissions,
    )


@pytest.fixture
def setup():
    services = disconnected_services()
    services.audit = FakeAudit()
    owner = Mock()
    owner.read.return_value = KnowledgeMapView.model_validate(view_document())
    services.queries.knowledge_map = owner
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            yield client, app, owner
    finally:
        services.engine.dispose()


def test_map_returns_exact_read_model_without_creating_work(setup):
    client, app, owner = setup
    response = client.get("/api/v1/knowledge-map", params={"query": "운동"})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == owner.read.return_value.model_dump(mode="json")
    owner.read.assert_called_once_with(
        graph_snapshot_revision_id=None,
        snapshot_sha256=None,
        query="운동",
        node_id=None,
        edge_id=None,
    )
    operation = app.openapi()["paths"]["/api/v1/knowledge-map"]["get"]
    assert operation["x-eom-permission"] == "knowledge_graph:read"
    assert operation["x-eom-read-only"] is True


def test_map_rejects_missing_authority_before_read(setup):
    client, app, owner = setup
    auth = replace(authentication(), permissions=frozenset({PermissionKey.KNOWLEDGE_GRAPH_READ}))

    def authenticated(request: Request):
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = authenticated
    assert client.get("/api/v1/knowledge-map").status_code == 403
    owner.read.assert_not_called()


def test_map_followup_passes_both_immutable_pins(setup):
    client, _app, owner = setup
    value = view_document()
    response = client.get(
        "/api/v1/knowledge-map",
        params={
            "graph_snapshot_revision_id": value["graph_snapshot_revision_id"],
            "snapshot_sha256": value["snapshot_sha256"],
            "node_id": value["focus_node_id"],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        owner.read.call_args.kwargs["graph_snapshot_revision_id"]
        == value["graph_snapshot_revision_id"]
    )
    assert owner.read.call_args.kwargs["snapshot_sha256"] == value["snapshot_sha256"]


def test_map_rejects_untyped_paths_and_excessive_query(setup):
    client, _app, owner = setup
    assert client.get("/api/v1/knowledge-map", params={"query": "x" * 81}).status_code == 422
    assert (
        client.get("/api/v1/knowledge-map", params={"node_id": "../../etc/passwd"}).status_code
        == 422
    )
    owner.read.assert_not_called()


def test_map_does_not_give_full_permission_viewer_admin_visibility(setup):
    client, app, owner = setup
    auth = authentication()
    auth = replace(auth, operator=auth.operator.model_copy(update={"roles": (RoleKey.VIEWER,)}))

    def authenticated(request: Request):
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = authenticated
    assert client.get("/api/v1/knowledge-map").status_code == 403
    owner.read.assert_not_called()
