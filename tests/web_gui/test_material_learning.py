"""BFF preserves explicit consent, operator boundary and typed immutable receipts."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from eom_identifiers import sha256_bytes
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.material_learning_contracts import (
    MaterialLearningControlReply,
    MaterialLearningRetry,
    MaterialLearningRetryReply,
    MaterialLearningRuns,
    MaterialLearningSourceReceipt,
    MaterialLearningTaskDetail,
)

from tests.unit.test_material_learning_intake import source_receipt
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single


@pytest.fixture
def anyio_backend():
    return "asyncio"


class LearningGateway(FakeGateway):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.learning_calls = []

    async def material_learning_runs(self, session):
        self.learning_calls.append("list")
        return MaterialLearningRuns(schema_version="material-learning-run-list/1.0", runs=())

    async def control_material_learning(self, session, run_id, value):
        self.learning_calls.append((run_id, value.action))
        return MaterialLearningControlReply(
            schema_version="material-learning-control-result/1.0",
            run_id=run_id,
            state="PAUSED",
            updated_at=value.expected_updated_at,
            replayed=False,
        )

    async def retry_material_learning(self, session, run_id, value):
        self.learning_calls.append((run_id, "RETRY", value.expected_updated_at.isoformat()))
        return MaterialLearningRetryReply(
            schema_version="material-learning-retry-result/1.0",
            predecessor_run_id=run_id,
            run_id="materialrun_" + "b" * 32,
            state="PROCESSING",
            reused_tasks=10,
            retried_tasks=1,
            replayed=False,
        )

    async def material_learning_task(self, session, run_id, task_id):
        self.learning_calls.append((run_id, task_id))
        return MaterialLearningTaskDetail.model_validate(
            dict(
                schema_version="material-learning-task-detail/1.0",
                run_id=run_id,
                task=dict(
                    task_id=task_id,
                    ordinal=3,
                    task_kind="QUESTION",
                    state="FAILED",
                    workflow_id=None,
                    item_revision_id=None,
                    analysis_run_id=None,
                    graph_snapshot_revision_id=None,
                    error_code="SYNTHETIC_FAILURE",
                ),
                attempt=1,
                predecessor_task_id=None,
                printed_label="12",
                section_path=["1장"],
                source_pages=[
                    dict(source_role="MAIN", original_filename="자료.pdf", physical_page=5)
                ],
            )
        )

    async def material_learning_source(self, session, **kwargs):
        data = b"".join([chunk async for chunk in kwargs.pop("content")])
        self.learning_calls.append((kwargs, data))
        receipt = source_receipt()
        receipt["original_filename"] = kwargs["original_filename"]
        receipt["original"]["bytes"] = len(data)
        receipt["original"]["sha256"] = sha256_bytes(data)
        return MaterialLearningSourceReceipt.model_validate(receipt)


def test_new_learning_list_preserves_admin_only_boundary():
    gateway = LearningGateway(roles=["VIEWER"])
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        assert client.get("/studio/api/v1/material-learning").status_code == 403
        assert not gateway.learning_calls


def test_learning_list_has_typed_empty_projection():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        response = client.get("/studio/api/v1/material-learning")
        assert response.status_code == 200, response.text
        assert response.json()["runs"] == []
        assert gateway.learning_calls == ["list"]


def test_material_upload_without_csrf_is_denied_before_reading_source():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        response = client.put(
            "/studio/api/v1/material-learning/sources?original_filename=test.pdf",
            content=b"%PDF-1.7\ntest",
            headers={
                "Content-Type": "application/octet-stream",
                "Idempotency-Key": "material-upload-test-1234",
                "X-EOM-Rights-Confirmed": "true",
            },
        )
        assert response.status_code == 403
        assert not gateway.learning_calls


def test_material_upload_stream_uses_binary_limit_and_exact_consent():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    body = b"%PDF-1.7\n" + b"x" * 300_000
    with client:
        session = login(client)
        response = client.put(
            "/studio/api/v1/material-learning/sources?original_filename=test.pdf",
            content=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Idempotency-Key": "material-upload-test-1234",
                "X-EOM-Rights-Confirmed": "true",
                "X-CSRF-Token": session["csrf_token"],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["original"]["sha256"] == sha256_bytes(body)
        assert gateway.learning_calls[0][1] == body
        assert gateway.learning_calls[0][0]["content_length"] == len(body)


def test_learning_control_preserves_csrf_and_actual_bff_forwarding():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    run_id = "materialrun_" + "a" * 32
    with client:
        session = login(client)
        body = dict(action="PAUSE", expected_updated_at="2026-11-06T00:00:00Z")
        path = f"/studio/api/v1/material-learning/{run_id}/control"
        assert client.post(path, json=body).status_code == 403
        assert not gateway.learning_calls
        response = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "PAUSED"
        assert gateway.learning_calls == [(run_id, "PAUSE")]


def test_learning_retry_uses_csrf_and_task_read_keeps_server_identity():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    run_id, task_id = "materialrun_" + "a" * 32, "materialtask_" + "c" * 32
    with client:
        session = login(client)
        body = dict(expected_updated_at="2026-11-06T00:00:00Z")
        path = f"/studio/api/v1/material-learning/{run_id}/retry"
        assert client.post(path, json=body).status_code == 403
        assert not gateway.learning_calls
        response = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        assert response.status_code == 200, response.text
        assert response.json()["run_id"] != run_id
        assert gateway.learning_calls[0] == (run_id, "RETRY", "2026-11-06T00:00:00+00:00")
        source = client.get(f"/studio/api/v1/material-learning/{run_id}/tasks/{task_id}")
        assert source.status_code == 200, source.text
        assert source.json()["source_pages"][0]["physical_page"] == 5
        assert gateway.learning_calls[-1] == (run_id, task_id)


@pytest.mark.anyio
async def test_actual_gateway_reuses_observation_key_and_checks_successor_identity():
    run_id, next_id = "materialrun_" + "a" * 32, "materialrun_" + "b" * 32
    when = datetime(2026, 11, 6, tzinfo=UTC)
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.path == f"/api/v1/material-learning/{run_id}/retry"
        assert (
            request.headers["Idempotency-Key"] == f"material-retry-v1:{run_id}:{when.isoformat()}"
        )
        assert json.loads(request.content) == {"expected_updated_at": "2026-11-06T00:00:00Z"}
        return httpx.Response(
            200,
            json=_single(
                dict(
                    schema_version="material-learning-retry-result/1.0",
                    predecessor_run_id=run_id,
                    run_id=next_id,
                    state="PROCESSING",
                    reused_tasks=10,
                    retried_tasks=1,
                    replayed=len(calls) > 1,
                )
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(respond),
        observability_transport=httpx.MockTransport(respond),
    )
    try:
        first = await gateway.retry_material_learning(
            _session(), run_id, MaterialLearningRetry(expected_updated_at=when)
        )
        again = await gateway.retry_material_learning(
            _session(), run_id, MaterialLearningRetry(expected_updated_at=when)
        )
        assert first.run_id == again.run_id == next_id and again.replayed
        assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_gateway_rejects_retry_result_for_other_predecessor():
    run_id = "materialrun_" + "a" * 32

    def respond(request):
        return httpx.Response(
            200,
            json=_single(
                dict(
                    schema_version="material-learning-retry-result/1.0",
                    predecessor_run_id="materialrun_" + "f" * 32,
                    run_id="materialrun_" + "b" * 32,
                    state="PROCESSING",
                    reused_tasks=1,
                    retried_tasks=1,
                    replayed=False,
                )
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(respond),
        observability_transport=httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.retry_material_learning(
                _session(),
                run_id,
                MaterialLearningRetry(expected_updated_at=datetime(2026, 11, 6, tzinfo=UTC)),
            )
    finally:
        await gateway.close()


def test_material_learning_browser_replay_and_owner_reset():
    import os
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in check requires an existing local Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual material upload browser check")
    script = Path(__file__).with_name("material_learning_browser_checks.mjs")
    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, timeout=90, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "MATERIAL_LEARNING_BROWSER=PASS" in result.stdout
