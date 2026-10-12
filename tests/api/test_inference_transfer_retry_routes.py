"""Fake authenticated retry presentation and replay; no SQL, live source or worker."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest
from eom_api.services.inference_transfer_retry import (
    AuthorizedInferenceTransferRetry,
    InferenceTransferRetryApplicationService,
)
from eom_api.services.inference_transfer_workflow_read import (
    InferenceTransferWorkflowReadApplicationServiceV11,
    InferenceTransferWorkflowReadError,
)
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_pair_submit_request_v11,
    parse_workflow_read_result_v11,
)
from eom_catalog_contracts.inference_transfer_retry import (
    InferenceTransferPairRetryRequestV1,
    parse_pair_retry_request_v1,
)
from eom_operator_identity import ActorContext, ActorSource, PermissionKey
from fastapi import FastAPI

from tests.unit.inference_transfer_api_fixtures import (
    ACTOR_ID,
    PERMISSIONS,
    ApiHarness,
    authentication,
    harness,
    selection,
)
from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID, read_result, rehash

CHILD = "workflow_" + "c" * 32
COMMAND = "wfcmd_" + "d" * 32
ENDPOINT = "/api/v1/knowledge/inference-transfer/workflows/"
RETRY = ENDPOINT + WORKFLOW_ID + "/retries/v1.1"
KEY = "synthetic-inference-transfer-retry-0001"
HEADERS = {"Idempotency-Key": KEY, "If-Match": '"v7"'}


def retry_request(value: ApiHarness) -> InferenceTransferPairRetryRequestV1:
    selected = parse_pair_submit_request_v11(
        rehash(
            selection(value.snapshots).model_dump(mode="json")
            | {"schema_version": "inference-transfer-pair-submit/1.1"},
            "submission_sha256",
        )
    )
    return parse_pair_retry_request_v1(
        rehash(
            {
                "schema_version": "inference-transfer-pair-retry/1.0",
                "failed_step_run_id": "steprun_" + "a" * 32,
                "failed_attempt": 1,
                "selection": selected.model_dump(mode="json"),
                "reason": "Synthetic explicit successor verification.",
            },
            "retry_sha256",
        )
    )


class ParentReader:
    def __init__(self, selected: InferenceTransferPairSubmitRequestV11) -> None:
        self.calls: list[tuple[str, InferenceTransferWorkflowReadRequestV11]] = []
        self.failure: str | None = None
        self.selected = selected

    def execute_v11(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11:
        self.calls.append((actor_id, request))
        if self.failure is not None:
            raise InferenceTransferWorkflowReadError(self.failure)
        return parse_workflow_read_result_v11(
            rehash(
                read_result("FAILED", verified=False).model_dump(mode="json")
                | {
                    "schema_version": "inference-transfer-workflow-read-result/1.1",
                    "workflow_id": request.workflow_id,
                    "comparison": self.selected.comparison.model_dump(mode="json"),
                },
                "result_sha256",
            )
        )


class RetryPort:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthorizedInferenceTransferRetry, ActorContext, int, str]] = []

    def retry(
        self,
        authorized: AuthorizedInferenceTransferRetry,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        self.calls.append((authorized, actor, expected_version, idempotency_key))
        return COMMAND, CHILD, 1


@dataclass
class RetryHarness:
    api: ApiHarness
    parents: ParentReader
    retry: RetryPort


@contextmanager
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[RetryHarness]:
    value = harness()
    parents, port = ParentReader(retry_request(value).selection), RetryPort()
    service = InferenceTransferRetryApplicationService(
        value.services.inference_transfer_submissions,
        InferenceTransferWorkflowReadApplicationServiceV11(parents),
        port,
    )
    monkeypatch.setattr(value.services, "inference_transfer_retries", service)
    try:
        with value.client:
            yield RetryHarness(value, parents, port)
    finally:
        value.services.engine.dispose()


def test_route_reauthorizes_parent_sources_then_binds_actual_actor_version_and_child_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with api(monkeypatch) as value:
        body = retry_request(value.api)
        response = value.api.client.post(RETRY, headers=HEADERS, json=body.model_dump(mode="json"))
        assert response.status_code == 202
        result = response.json()["data"]
        assert result["resource_id"] == CHILD != WORKFLOW_ID
        assert result["command_id"] == COMMAND and result["status"] == "ACCEPTED"
        assert result["resource_version"] == 1
        assert result["status_url"] == ENDPOINT + CHILD + "/v1.1"
        authorized, actor, version, key = value.retry.calls[0]
        assert authorized.parent_workflow_id == WORKFLOW_ID and authorized.request == body
        assert authorized.submission.operator_id == actor.actor_id == ACTOR_ID
        assert actor.source == ActorSource.APPLICATION_API and actor.permissions == PERMISSIONS
        assert version == 7
        assert key == value.api.idempotency.submission_key(
            operator_id=ACTOR_ID, endpoint_key="inference_transfer_pair_retry_v11", raw_key=KEY
        )
        assert [request.mode for _, request in value.parents.calls] == ["STATUS_ONLY"]
        assert [request.phase for _, request in value.api.snapshots.calls] == [
            "PREPARE",
            "READ",
            "READ",
        ]
        assert not value.api.starter.calls


def test_same_retry_key_cached_replay_requires_new_current_source_reads_and_never_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with api(monkeypatch) as value:
        body = retry_request(value.api).model_dump(mode="json")
        first = value.api.client.post(RETRY, headers=HEADERS, json=body)
        replay = value.api.client.post(RETRY, headers=HEADERS, json=body)
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"] == replay.json()["data"]
        assert len(value.retry.calls) == 1 and len(value.api.idempotency.claims) == 2
        assert len(value.parents.calls) == 2
        assert [request.phase for _, request in value.api.snapshots.calls] == [
            "PREPARE",
            "READ",
            "READ",
        ] * 2
        assert not value.api.starter.calls


@pytest.mark.parametrize("revocation", ["PARENT", "SOURCE", "PERMISSION"])
def test_current_revocation_blocks_cached_retry_before_idempotency_claim(
    monkeypatch: pytest.MonkeyPatch, revocation: str
) -> None:
    with api(monkeypatch) as value:
        body = retry_request(value.api).model_dump(mode="json")
        assert value.api.client.post(RETRY, headers=HEADERS, json=body).status_code == 202
        history = dict(value.api.idempotency.responses)
        if revocation == "PARENT":
            value.parents.failure = "INFERENCE_TRANSFER_FORBIDDEN"
        elif revocation == "SOURCE":
            value.api.snapshots.failure = "INFERENCE_TRANSFER_FORBIDDEN"
        else:
            value.api.authentication = authentication(PERMISSIONS - {PermissionKey.ITEM_READ})
        denied = value.api.client.post(RETRY, headers=HEADERS, json=body)
        assert denied.status_code == 403
        assert len(value.retry.calls) == len(value.api.idempotency.claims) == 1
        assert value.api.idempotency.responses == history and not value.api.idempotency.failures


@pytest.mark.parametrize("change", ["PARENT", "VERSION", "BODY"])
def test_retry_http_key_hash_includes_exact_parent_expected_version_and_body(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    with api(monkeypatch) as value:
        body = retry_request(value.api).model_dump(mode="json")
        assert value.api.client.post(RETRY, headers=HEADERS, json=body).status_code == 202
        path, headers = RETRY, HEADERS
        if change == "PARENT":
            path = ENDPOINT + "workflow_" + "e" * 32 + "/retries/v1.1"
        elif change == "VERSION":
            headers = HEADERS | {"If-Match": '"v8"'}
        else:
            body = rehash(body | {"reason": "A different explicit request."}, "retry_sha256")
        conflict = value.api.client.post(path, headers=headers, json=body)
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"
        assert len(value.retry.calls) == 1 and len(value.api.idempotency.responses) == 1


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_retry_requires_existing_workflow_and_source_permissions_before_port_call(
    monkeypatch: pytest.MonkeyPatch, permission: PermissionKey
) -> None:
    with api(monkeypatch) as value:
        value.api.authentication = authentication(PERMISSIONS - {permission})
        response = value.api.client.post(
            RETRY, headers=HEADERS, json=retry_request(value.api).model_dump(mode="json")
        )
        assert response.status_code == 403
        assert not value.retry.calls and not value.api.idempotency.claims


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Idempotency-Key": KEY}, 428),
        (HEADERS | {"If-Match": 'W/"v7"'}, 412),
        (HEADERS | {"If-Match": '"v0"'}, 412),
        ({"If-Match": '"v7"'}, 400),
        (HEADERS | {"Idempotency-Key": "short"}, 422),
    ],
)
def test_invalid_precondition_or_key_never_authorizes_or_creates_successor(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], status: int
) -> None:
    with api(monkeypatch) as value:
        response = value.api.client.post(
            RETRY, headers=headers, json=retry_request(value.api).model_dump(mode="json")
        )
        assert response.status_code == status
        assert not value.parents.calls and not value.retry.calls
        assert not value.api.idempotency.claims


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": ACTOR_ID},
        {"preset": "latest"},
        {"failed_attempt": True},
        {"failed_attempt": 2},
        {"reason": " "},
        {"retry_sha256": "sha256:" + "f" * 64},
    ],
)
def test_retry_wire_cannot_supply_authority_new_attempt_or_forged_hash(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    with api(monkeypatch) as value:
        body = retry_request(value.api).model_dump(mode="json") | changes
        response = value.api.client.post(RETRY, headers=HEADERS, json=body)
        assert response.status_code == 422
        assert (
            not value.parents.calls and not value.retry.calls and not value.api.idempotency.claims
        )


def test_retry_openapi_exposes_existing_permissions_if_match_and_closed_dto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with api(monkeypatch) as value:
        document = cast(FastAPI, value.api.client.app).openapi()
        operation = document["paths"][
            "/api/v1/knowledge/inference-transfer/workflows/{workflow_id}/retries/v1.1"
        ]["post"]
        assert operation["operationId"] == "inference_transfer_pair_retry_v11"
        assert {row["name"] for row in operation["parameters"]} >= {
            "workflow_id",
            "If-Match",
            "Idempotency-Key",
        }
        assert operation["x-eom-additional-permissions"] == [
            PermissionKey.WORKFLOW_READ.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ]
        assert "202" in operation["responses"]
