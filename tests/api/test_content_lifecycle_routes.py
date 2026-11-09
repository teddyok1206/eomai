"""Shelving transport uses actual actor and separate closed read/change operations."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.content_lifecycle import ContentLifecycleView
from eom_operator_identity import PermissionKey

from tests.api.test_content_planning_routes import planning_client as planning_client
from tests.api.test_hwpx_endpoints import OPERATOR_ID
from tests.web_gui.test_content_lifecycle import change, entry, mutation


def test_lifecycle_actual_actor_key_and_closed_read_boundary(planning_client):
    client, catalog, _ = planning_client
    catalog.content_planning_lifecycle = Mock(return_value=mutation())
    path = "/api/v1/content-planning/lifecycle"
    body = change().model_dump(mode="json")
    response = client.post(path, json=body, headers={"Idempotency-Key": "lifecycle-api-1234"})
    assert response.status_code == 200, response.text
    call = catalog.content_planning_lifecycle.call_args
    assert call.kwargs["actor"].operator_id == OPERATOR_ID
    assert call.kwargs["idempotency_key"] == "lifecycle-api-1234"
    assert client.post(path + "/query", json=body).status_code == 422
    catalog.content_planning_lifecycle.return_value = ContentLifecycleView(entry=entry(), events=())
    response = client.post(
        path + "/query", json=dict(action_kind="READ_LIFECYCLE", target=body["target"])
    )
    assert response.status_code == 200, response.text
    assert "idempotency_key" not in catalog.content_planning_lifecycle.call_args.kwargs


@pytest.mark.parametrize(
    "missing",
    [PermissionKey.DELIVERABLE_READ, PermissionKey.DELIVERABLE_UPDATE, PermissionKey.ITEM_READ],
)
def test_lifecycle_mutation_requires_full_permissions_before_owner(planning_client, missing):
    client, catalog, state = planning_client
    catalog.content_planning_lifecycle = Mock(return_value=mutation())
    state.authentication = replace(
        state.authentication, permissions=state.authentication.permissions - {missing}
    )
    response = client.post(
        "/api/v1/content-planning/lifecycle",
        json=change().model_dump(mode="json"),
        headers={"Idempotency-Key": "lifecycle-api-1234"},
    )
    assert response.status_code == 403
    catalog.content_planning_lifecycle.assert_not_called()


def test_lifecycle_missing_key_and_supplied_authority_rejected(planning_client):
    client, catalog, _ = planning_client
    catalog.content_planning_lifecycle = Mock(return_value=mutation())
    path = "/api/v1/content-planning/lifecycle"
    body = change().model_dump(mode="json")
    assert client.post(path, json=body).status_code == 400
    assert (
        client.post(
            path,
            json={**body, "actor_id": OPERATOR_ID},
            headers={"Idempotency-Key": "lifecycle-api-1234"},
        ).status_code
        == 422
    )
    catalog.content_planning_lifecycle.assert_not_called()
