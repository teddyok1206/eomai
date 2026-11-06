"""Authenticated material upload/create/read boundaries never accept an actor from the browser."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.pdf_upload_stager import PdfUploadStager
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningAcceptance,
    MaterialLearningRunList,
    MaterialSourceUploadReceipt,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.test_material_learning_intake import create_command, source_receipt


@pytest.fixture
def material_client(tmp_path):
    services = disconnected_services()
    reads = SimpleNamespace(
        ingest_material_learning_source=Mock(),
        create_material_learning=Mock(),
        list_material_learning_runs=Mock(return_value=MaterialLearningRunList(runs=())),
        read_material_learning_run=Mock(),
        control_material_learning_run=Mock(),
        retry_material_learning_run=Mock(),
        read_material_learning_task=Mock(),
    )
    services.catalog_application = reads
    services.audit = Mock()
    tmp_path.chmod(0o700)
    services.pdf_review_upload_stager = PdfUploadStager(tmp_path, maximum_bytes=256 * 1024 * 1024)
    app = create_app(services)

    def authenticated(request: Request):
        auth = _authentication()
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, reads, app, tmp_path
    services.engine.dispose()


def test_control_uses_real_actor_and_revision_fence_not_browser_actor(material_client):
    from datetime import UTC, datetime

    from eom_catalog_contracts.material_learning_intake import MaterialLearningControlResult

    client, catalog, _, _ = material_client
    run_id = "materialrun_" + "1" * 32
    when = datetime(2026, 11, 6, tzinfo=UTC)
    catalog.control_material_learning_run.return_value = MaterialLearningControlResult(
        run_id=run_id,
        state="PAUSED",
        updated_at=when,
        replayed=False,
    )
    response = client.post(
        f"/api/v1/material-learning/{run_id}/control",
        json=dict(action="PAUSE", expected_updated_at="2026-11-06T00:00:00Z"),
        headers={"Idempotency-Key": f"material-control-v1:{run_id}:PAUSE:{when.isoformat()}"},
    )
    assert response.status_code == 200, response.text
    command = catalog.control_material_learning_run.call_args.args[0]
    assert command.actor_id == OPERATOR_ID and command.expected_updated_at == when
    rejected = client.post(
        f"/api/v1/material-learning/{run_id}/control",
        json=dict(
            action="PAUSE",
            expected_updated_at="2026-11-06T00:00:00Z",
            actor_id="operator_" + "f" * 32,
        ),
        headers={"Idempotency-Key": f"material-control-v1:{run_id}:PAUSE:{when.isoformat()}"},
    )
    assert rejected.status_code == 422


def test_retry_is_actor_bound_and_uses_exact_predecessor_observation(material_client):
    from datetime import UTC, datetime

    from eom_catalog_contracts.material_learning_intake import MaterialLearningRetryResult

    client, catalog, _, _ = material_client
    run_id = "materialrun_" + "1" * 32
    when = datetime(2026, 11, 6, tzinfo=UTC)
    catalog.retry_material_learning_run.return_value = MaterialLearningRetryResult(
        predecessor_run_id=run_id,
        run_id="materialrun_" + "2" * 32,
        state="PROCESSING",
        reused_tasks=10,
        retried_tasks=1,
        replayed=False,
    )
    path = f"/api/v1/material-learning/{run_id}/retry"
    body = {"expected_updated_at": "2026-11-06T00:00:00Z"}
    invalid = client.post(path, json=body, headers={"Idempotency-Key": "wrong-material-retry-1234"})
    assert invalid.status_code == 422
    catalog.retry_material_learning_run.assert_not_called()
    response = client.post(
        path,
        json=body,
        headers={"Idempotency-Key": f"material-retry-v1:{run_id}:{when.isoformat()}"},
    )
    assert response.status_code == 200, response.text
    command = catalog.retry_material_learning_run.call_args.args[0]
    assert command.actor_id == OPERATOR_ID and command.expected_updated_at == when
    denied = client.post(
        path,
        json=body | {"actor_id": "operator_" + "f" * 32},
        headers={"Idempotency-Key": f"material-retry-v1:{run_id}:{when.isoformat()}"},
    )
    assert denied.status_code == 422


def test_task_read_is_bound_to_actual_actor_and_both_server_identities(material_client):
    from eom_catalog_contracts.material_learning_intake import MaterialLearningTaskDetail

    client, catalog, _, _ = material_client
    run_id, task_id = "materialrun_" + "1" * 32, "materialtask_" + "2" * 32
    catalog.read_material_learning_task.return_value = MaterialLearningTaskDetail.model_validate(
        dict(
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
            source_pages=[dict(source_role="MAIN", original_filename="자료.pdf", physical_page=5)],
        )
    )
    response = client.get(f"/api/v1/material-learning/{run_id}/tasks/{task_id}")
    assert response.status_code == 200, response.text
    query = catalog.read_material_learning_task.call_args.args[0]
    assert (query.actor_id, query.run_id, query.task_id) == (OPERATOR_ID, run_id, task_id)
    assert response.json()["data"]["source_pages"][0]["physical_page"] == 5


def test_catalog_retry_client_rejects_other_predecessor(monkeypatch):
    from datetime import UTC, datetime

    from eom_api.services.catalog_application_client import (
        CatalogApplicationClient,
        CatalogApplicationClientError,
    )
    from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand

    client = CatalogApplicationClient()
    command = RetryMaterialLearningRunCommand(
        actor_id=OPERATOR_ID,
        run_id="materialrun_" + "1" * 32,
        expected_updated_at=datetime(2026, 11, 6, tzinfo=UTC),
    )
    monkeypatch.setattr(
        client,
        "_raw_request",
        lambda *_args, **_kwargs: dict(
            schema_version="material-learning-retry-result/1.0",
            predecessor_run_id="materialrun_" + "2" * 32,
            run_id="materialrun_" + "3" * 32,
            state="PROCESSING",
            reused_tasks=1,
            retried_tasks=1,
            replayed=False,
        ),
    )
    with pytest.raises(CatalogApplicationClientError, match="identity differs"):
        client.retry_material_learning_run(command)


def test_upload_uses_authenticated_actor_and_actual_bytes(material_client):
    client, catalog, _app, tmp_path = material_client
    # Deliberately labelled hwp and sent as octet-stream: signature wins.
    payload = b"PK\x03\x04test-payload"
    reply = source_receipt("HWPX", OPERATOR_ID)
    reply["original"]["bytes"] = len(payload)
    reply["original"]["sha256"] = content_sha256({"synthetic": True})
    catalog.ingest_material_learning_source.return_value = (
        MaterialSourceUploadReceipt.model_validate(reply)
    )
    response = client.put(
        "/api/v1/material-learning/sources",
        params={"original_filename": "자료.hwp"},
        content=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "Idempotency-Key": "material-source-test-1234",
            "X-EOM-Rights-Confirmed": "true",
        },
    )
    assert response.status_code == 201, response.text
    source_path, command = catalog.ingest_material_learning_source.call_args.args
    assert command.actor_id == OPERATOR_ID
    assert command.source_format == "HWPX"
    assert command.original_filename == "자료.hwp"
    assert not source_path.exists()
    assert not list(tmp_path.iterdir())


def test_creation_replays_exact_catalog_key_not_a_second_http_state_machine(material_client):
    client, catalog, _, _ = material_client
    command = create_command()
    command["sources"][0]["source_upload"]["uploaded_by"] = OPERATOR_ID
    body = {"upload": command["upload"], "sources": command["sources"]}
    accepted = MaterialLearningAcceptance(
        material_id="material_" + "1" * 32,
        material_revision_id="materialrev_" + "2" * 32,
        run_id="materialrun_" + "3" * 32,
        request_sha256="sha256:" + "4" * 64,
        replayed=False,
    )
    catalog.create_material_learning.return_value = accepted
    for _ in range(2):
        response = client.post(
            "/api/v1/material-learning",
            json=body,
            headers={"Idempotency-Key": "material-create-test-1234"},
        )
        assert response.status_code == 202, response.text
    first, second = (call.args[0] for call in catalog.create_material_learning.call_args_list)
    assert first == second
    assert first.actor_id == OPERATOR_ID
    assert first.idempotency_key == "material-create-test-1234"


def test_browser_cannot_override_submission_actor(material_client):
    client, catalog, _, _ = material_client
    command = create_command()
    response = client.post(
        "/api/v1/material-learning",
        json=command,
        headers={"Idempotency-Key": "material-create-test-1234"},
    )
    assert response.status_code == 422
    catalog.create_material_learning.assert_not_called()


def test_recent_runs_are_bounded_and_authorized(material_client):
    client, catalog, _, _ = material_client
    response = client.get("/api/v1/material-learning?limit=20")
    assert response.status_code == 200, response.text
    query = catalog.list_material_learning_runs.call_args.args[0]
    assert query.actor_id == OPERATOR_ID and query.limit == 20
    assert response.json()["data"]["runs"] == []
    assert client.get("/api/v1/material-learning?limit=51").status_code == 422


def test_permission_denial_happens_before_upload_or_catalog_read(material_client):
    client, catalog, app, _ = material_client

    def denied(request: Request):
        auth = replace(_authentication(), permissions=frozenset({PermissionKey.ITEM_READ}))
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = denied
    assert client.get("/api/v1/material-learning").status_code == 403
    catalog.list_material_learning_runs.assert_not_called()
