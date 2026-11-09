"""Independent BFF values preserve owner payloads, session and replay identity."""

import json

import httpx
import pytest
from eom_web_gui.content_planning_contracts import (
    PLANNING_RESULT,
    PlanningCommand,
    PlanningQuery,
    WriteResult,
)
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.request_limits import request_body_limit
from pydantic import TypeAdapter

from tests.api.test_content_planning_routes import command, result
from tests.unit.content_planning_fixtures import composition, identifier, slot
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single


@pytest.fixture
def anyio_backend():
    return "asyncio"


class PlanningGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def content_planning_write(self, session, value, idempotency_key):
        self.calls.append((session.operator["operator_id"], value, idempotency_key))
        return WriteResult.model_validate(result().model_dump(mode="json"))

    async def content_planning_query(self, session, value):
        self.calls.append((session.operator["operator_id"], value))
        return PLANNING_RESULT.validate_python(dict(result_kind="CONTENTS", rows=[], next_id=None))

    async def content_planning_delivery(self, session, value, idempotency_key):
        from eom_web_gui.content_planning_contracts import PreparedDelivery

        from tests.api.test_content_delivery_routes import delivery_example

        self.calls.append((session.operator["operator_id"], value, idempotency_key))
        return PreparedDelivery.model_validate(delivery_example()[1].model_dump(mode="json"))


def test_content_bff_csrf_key_and_actual_session():
    gateway = PlanningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        body = command().model_dump(mode="json")
        path = "/studio/api/v1/content-planning/commands"
        assert client.post(path, json=body).status_code == 403
        assert not gateway.calls
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": "content-bff-save-1234",
        }
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert gateway.calls[0][2] == headers["Idempotency-Key"]
        assert gateway.calls[0][1].model_dump(mode="json") == body
        assert response.json() == result().model_dump(mode="json")
        assert (
            client.post(
                path, json={**body, "actor_id": identifier("operator")}, headers=headers
            ).status_code
            == 422
        )
        assert len(gateway.calls) == 1


def test_large_pointer_array_is_not_reduced_to_200_or_truncated_at_normal_body_limit():
    gateway = PlanningGateway()
    client, _ = make_client(gateway=gateway)
    data = composition()
    change = dict(
        section_id=data["sections"][0]["section_id"],
        before_assembly_revision_id=data["sections"][0]["form"]["assembly_revision_id"],
        before_manifest_sha256=data["sections"][0]["form"]["manifest_sha256"],
        placements=[slot(n) for n in range(1, 1201)],
    )
    body = dict(
        command_kind="EDIT_EDITION",
        edition_id=data["edition_id"],
        edit=dict(
            change_kind="SAVE_SECTIONS",
            expected_revision_id=data["deliverable_revision_id"],
            expected_sha256=data["composition_sha256"],
            changes=[change],
        ),
    )
    assert len(json.dumps(body).encode()) > 262144
    with client:
        session = login(client)
        response = client.post(
            "/studio/api/v1/content-planning/commands",
            json=body,
            headers={
                "X-CSRF-Token": session["csrf_token"],
                "Idempotency-Key": "content-bff-large-1234",
            },
        )
        assert response.status_code == 200, response.text
        assert len(gateway.calls[0][1].edit.changes[0].placements) == 1200
    assert request_body_limit("POST", "/studio/api/v1/content-planning/commands") == 4 * 1024**2
    assert request_body_limit("POST", "/studio/api/v1/content-planning/query") == 262144


@pytest.mark.anyio
async def test_http_gateway_preserves_key_and_owner_response():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_single(result().model_dump(mode="json")))

    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    try:
        value = TypeAdapter(PlanningCommand).validate_python(command().model_dump(mode="json"))
        reply = await gateway.content_planning_write(_session(), value, "content-gateway-1234")
        assert reply.model_dump(mode="json") == result().model_dump(mode="json")
        assert calls[0].headers["Idempotency-Key"] == "content-gateway-1234"
        assert json.loads(calls[0].content) == value.model_dump(mode="json")
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_different_edition_response_is_not_shown():
    data = composition()
    reply = dict(
        result_kind="COMPOSITION",
        composition=data,
        current_revision_id=data["deliverable_revision_id"],
    )
    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_single(reply))),
    )
    try:
        query = TypeAdapter(PlanningQuery).validate_python(
            dict(query_kind="READ_EDITION", edition_id=identifier("edition", 2), revision_id=None)
        )
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_planning_query(_session(), query)
    finally:
        await gateway.close()


def test_query_still_requires_browser_csrf_and_rejects_authority_fields():
    gateway = PlanningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        path = "/studio/api/v1/content-planning/query"
        body = dict(query_kind="LIST_CONTENTS", text="", limit=50, after_id=None)
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        assert response.status_code == 200, response.text
        assert response.json()["result_kind"] == "CONTENTS"


def test_content_dtos_roundtrip_owner_composition_and_slot_page():
    from eom_catalog_contracts.content_planning_queries import (
        ContentEditionView,
        ContentSectionPage,
    )

    data = composition()
    replies = [
        ContentEditionView(composition=data, current_revision_id=data["deliverable_revision_id"]),
        ContentSectionPage(
            edition_id=data["edition_id"],
            revision_id=data["deliverable_revision_id"],
            composition_sha256=data["composition_sha256"],
            section_id=data["sections"][0]["section_id"],
            form=data["sections"][0]["form"],
            rows=[slot(1)],
            labels=[
                dict(placement_id=slot(1)["placement_id"], title="기출 문항", external_number=None)
            ],
            next_position=None,
            total=1,
        ),
    ]
    for reply in replies:
        wire = reply.model_dump(mode="json")
        assert PLANNING_RESULT.validate_python(wire).model_dump(mode="json") == wire


def test_content_planning_browser_and_pure_draft():
    import os
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the browser draft checks")
    root = Path(__file__).parent
    check = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(root / "content_planning_draft_checks.mjs"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert check.returncode == 0, check.stderr
    assert "content_planning_draft=PASS" in check.stdout
    pending = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(root / "content_planning_pending_checks.mjs"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert pending.returncode == 0, pending.stderr
    assert "content_planning_pending=PASS" in pending.stdout
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Actual browser check requires the existing opt-in Playwright environment")
    check = subprocess.run(
        [node, str(root / "content_planning_browser_checks.mjs")],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert check.returncode == 0, check.stderr
    assert "CONTENT_PLANNING_BROWSER=PASS" in check.stdout
    assert "live_writes=0" in check.stdout


def test_content_delivery_bff_does_not_expose_authority_or_start_a_build():
    from tests.api.test_content_delivery_routes import delivery_example

    request, prepared = delivery_example()
    gateway = PlanningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": "content-output-12345678",
        }
        path = "/studio/api/v1/content-planning/deliveries"
        assert client.post(path, json=request.model_dump(mode="json")).status_code == 403
        reply = client.post(path, json=request.model_dump(mode="json"), headers=headers)
        assert reply.status_code == 200 and reply.json() == prepared.model_dump(mode="json")
        assert len(gateway.calls) == 1 and gateway.calls[0][2] == headers["Idempotency-Key"]


@pytest.mark.anyio
async def test_content_delivery_gateway_preserves_1200_positions_and_rejects_other_edition():
    from eom_web_gui.content_planning_contracts import PrepareDelivery

    from tests.api.test_content_delivery_routes import delivery_example

    request, prepared = delivery_example()
    wire = prepared.model_dump(mode="json")
    calls = []

    def handle(http_request):
        calls.append(http_request)
        return httpx.Response(200, json=_single(wire))

    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handle),
    )
    try:
        value = PrepareDelivery.model_validate(request.model_dump(mode="json"))
        result = await gateway.content_planning_delivery(
            _session(), value, "content-output-12345678"
        )
        assert (
            result.placement_count == 1200
            and calls[0].headers["Idempotency-Key"] == "content-output-12345678"
        )
        wire["edition_id"] = identifier("edition", 99)
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_planning_delivery(_session(), value, "content-output-12345678")
    finally:
        await gateway.close()
