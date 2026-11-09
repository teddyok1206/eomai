"""Lifecycle mirrors retain identity, actual session, CSRF and mutation replay keys."""

import json

import httpx
import pytest
from eom_catalog_contracts.content_lifecycle import (
    ChangeContentLifecycle,
    ContentLifecycleEntry,
    ContentLifecycleList,
    ContentLifecycleMutation,
    ContentLifecycleView,
)
from eom_web_gui.content_lifecycle_contracts import (
    LIFECYCLE_RESULT,
    ChangeLifecycle,
    ListLifecycle,
    ReadLifecycle,
)
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway

from tests.unit.content_planning_fixtures import identifier
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single


@pytest.fixture
def anyio_backend():
    return "asyncio"


def entry(kind="CONTENT", *, state="ACTIVE"):
    return ContentLifecycleEntry.model_validate(
        dict(
            target=dict(
                target_kind=kind,
                target_id=identifier("deliverable" if kind == "CONTENT" else "edition"),
            ),
            deliverable_id=identifier("deliverable"),
            title="편성 보관 확인",
            lifecycle_state=state,
            version=3,
            current_revision_id=identifier("delivrev"),
            parent_archived=False,
        )
    )


def change():
    return ChangeContentLifecycle(
        action_kind="CHANGE_LIFECYCLE",
        target=entry().target,
        expected_state="ACTIVE",
        expected_version=3,
        desired_state="ARCHIVED",
        reason="다음 판 전환",
    )


def mutation():
    return ContentLifecycleMutation(
        entry=entry(state="ARCHIVED"), replayed=False, disposition="CHANGED"
    )


class LifecycleGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def content_planning_lifecycle(self, session, value, idempotency_key=None):
        self.calls.append((session.operator["operator_id"], value, idempotency_key))
        result = (
            mutation()
            if value.action_kind == "CHANGE_LIFECYCLE"
            else ContentLifecycleView(entry=entry(), events=())
        )
        return LIFECYCLE_RESULT.validate_python(result.model_dump(mode="json"))


def test_bff_closed_read_write_csrf_and_exact_key():
    gateway = LifecycleGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        path = "/studio/api/v1/content-planning/lifecycle"
        write = change().model_dump(mode="json")
        read = dict(action_kind="READ_LIFECYCLE", target=write["target"])
        assert client.post(path, json=write).status_code == 403
        assert client.post(path + "/query", json=read).status_code == 403
        assert not gateway.calls
        headers = {"X-CSRF-Token": session["csrf_token"]}
        assert client.post(path, json=write, headers=headers).status_code == 422
        assert client.post(path + "/query", json=write, headers=headers).status_code == 422
        assert client.post(path + "/query", json=read, headers=headers).status_code == 200
        assert gateway.calls[-1][2] is None
        headers["Idempotency-Key"] = "content-lifecycle-save-1234"
        response = client.post(path, json=write, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == mutation().model_dump(mode="json")
        assert gateway.calls[-1][2] == headers["Idempotency-Key"]
        count = len(gateway.calls)
        assert (
            client.post(
                path, json={**write, "actor_id": identifier("operator")}, headers=headers
            ).status_code
            == 422
        )
        assert len(gateway.calls) == count


@pytest.mark.parametrize(
    "value",
    [
        ContentLifecycleView(entry=entry(), events=()),
        ContentLifecycleList(rows=(entry("EDITION"),), next_id=identifier("edition")),
        mutation(),
    ],
)
def test_owner_lifecycle_results_roundtrip_in_independent_web_wheel(value):
    wire = value.model_dump(mode="json")
    assert LIFECYCLE_RESULT.validate_python(wire).model_dump(mode="json") == wire


@pytest.mark.anyio
async def test_gateway_preserves_owner_scope_and_rejects_other_target_or_state():
    calls = []
    wire = mutation().model_dump(mode="json")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_single(wire))

    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    value = ChangeLifecycle.model_validate(change().model_dump(mode="json"))
    try:
        result = await gateway.content_planning_lifecycle(
            _session(), value, "lifecycle-gateway-1234"
        )
        assert result.model_dump(mode="json") == wire
        assert calls[-1].url.path == "/api/v1/content-planning/lifecycle"
        assert calls[-1].headers["Idempotency-Key"] == "lifecycle-gateway-1234"
        assert json.loads(calls[-1].content) == value.model_dump(mode="json")
        wire["entry"]["target"]["target_id"] = identifier("deliverable", 2)
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_planning_lifecycle(_session(), value, "lifecycle-gateway-1234")
        wire = mutation().model_dump(mode="json")
        wire["entry"]["lifecycle_state"] = "ACTIVE"
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_planning_lifecycle(_session(), value, "lifecycle-gateway-1234")
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_gateway_read_has_no_key_and_list_rejects_other_parent():
    wire = ContentLifecycleView(entry=entry(), events=()).model_dump(mode="json")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_single(wire))

    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        read = ReadLifecycle(
            action_kind="READ_LIFECYCLE", target=entry().target.model_dump(mode="json")
        )
        await gateway.content_planning_lifecycle(_session(), read)
        assert calls[-1].url.path.endswith("/lifecycle/query")
        assert "Idempotency-Key" not in calls[-1].headers
        wire = ContentLifecycleList(rows=(entry("EDITION"),), next_id=None).model_dump(mode="json")
        query = ListLifecycle(
            action_kind="LIST_LIFECYCLE",
            target_kind="EDITION",
            deliverable_id=identifier("deliverable", 2),
            lifecycle_state="ALL",
            after_id=None,
            limit=50,
        )
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_planning_lifecycle(_session(), query)
    finally:
        await gateway.close()
