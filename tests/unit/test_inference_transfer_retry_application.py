"""Current source authorization before explicit successor retry; synthetic ports only."""

from __future__ import annotations

from typing import Any

import pytest
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_retry import (
    AuthorizedInferenceTransferRetry,
    InferenceTransferRetryApplicationService,
)
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService
from eom_api.services.inference_transfer_submission import (
    InferenceTransferSubmissionApplicationService,
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
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey

from tests.unit.inference_transfer_api_fixtures import (
    ACTOR_ID,
    NOW,
    PERMISSIONS,
    SnapshotReader,
    Starter,
    authentication,
    selection,
)
from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID, rehash


def retry_request(reader: SnapshotReader) -> InferenceTransferPairRetryRequestV1:
    selected: InferenceTransferPairSubmitRequestV11 = parse_pair_submit_request_v11(
        rehash(
            selection(reader).model_dump(mode="json")
            | {"schema_version": "inference-transfer-pair-submit/1.1"},
            "submission_sha256",
        )
    )
    return parse_pair_retry_request_v1(
        rehash(
            {
                "schema_version": "inference-transfer-pair-retry/1.0",
                "failed_step_run_id": "steprun_" + "1" * 32,
                "failed_attempt": 1,
                "selection": selected.model_dump(mode="json"),
                "reason": "Retry the fixed result validation defect without changing inputs.",
            },
            "retry_sha256",
        )
    )


def retry_actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=ACTOR_ID,
        session_id="apisession_" + "b" * 32,
        request_id="request_" + "c" * 32,
        authentication_time=NOW,
        permissions=PERMISSIONS,
        source=ActorSource.APPLICATION_API,
    )


class FailedReader:
    def __init__(self, request: InferenceTransferPairRetryRequestV1) -> None:
        selected = request.selection
        self.body: dict[str, Any] = {
            "schema_version": "inference-transfer-workflow-read-result/1.1",
            "workflow_id": WORKFLOW_ID,
            "workflow_state": "FAILED",
            "resource_version": 4,
            "comparison": selected.comparison.model_dump(mode="json"),
            "graph_snapshot": selected.snapshot_prepare.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": selected.snapshot_prepare.access_policy_revision_id,
            "access_policy_sha256": selected.snapshot_prepare.access_policy_sha256,
            "result_state": "NO_RESULT",
            "result_artifact": None,
            "result": None,
            "failure_code": "WORKFLOW_STEP_FAILED",
        }
        self.calls: list[tuple[str, InferenceTransferWorkflowReadRequestV11]] = []
        self.failure: str | None = None

    def execute_v11(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11:
        self.calls.append((actor_id, request))
        if self.failure:
            raise InferenceTransferWorkflowReadError(self.failure)
        return parse_workflow_read_result_v11(rehash(self.body, "result_sha256"))


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
        return "wfcmd_" + "d" * 32, "workflow_" + "e" * 32, 1


def configured() -> tuple[
    InferenceTransferRetryApplicationService, SnapshotReader, FailedReader, RetryPort, Starter
]:
    snapshots = SnapshotReader()
    request = retry_request(snapshots)
    reads = FailedReader(request)
    retry_port = RetryPort()
    starts = Starter()
    service = InferenceTransferRetryApplicationService(
        InferenceTransferSubmissionApplicationService(
            InferenceTransferSnapshotApplicationService(snapshots), starts
        ),
        InferenceTransferWorkflowReadApplicationServiceV11(reads),
        retry_port,
    )
    return service, snapshots, reads, retry_port, starts


def test_exact_original_sources_are_reauthorized_without_ordinary_start() -> None:
    service, snapshots, reads, port, starts = configured()
    request = retry_request(snapshots)
    authorized = service.authorize_retry(authentication(), WORKFLOW_ID, request)
    result = service.retry(
        authorized, retry_actor(), expected_version=4, idempotency_key="same-key"
    )
    assert result[1] == "workflow_" + "e" * 32
    assert reads.calls[0][0] == ACTOR_ID and reads.calls[0][1].mode == "STATUS_ONLY"
    assert len(snapshots.calls) == 3
    assert all(actor_id == ACTOR_ID for actor_id, _ in snapshots.calls)
    assert authorized.submission.selection == request.selection
    assert len(port.calls) == 1 and not starts.calls


@pytest.mark.parametrize("missing", [PermissionKey.WORKFLOW_START, PermissionKey.WORKFLOW_READ])
def test_current_permission_denial_cannot_replay_or_create(missing: PermissionKey) -> None:
    service, snapshots, reads, port, starts = configured()
    with pytest.raises(ApiError, match="PERMISSION_DENIED"):
        service.authorize_retry(
            authentication(PERMISSIONS - {missing}), WORKFLOW_ID, retry_request(snapshots)
        )
    assert not port.calls and not starts.calls and not snapshots.calls and not reads.calls


@pytest.mark.parametrize(
    "failure", ["INFERENCE_TRANSFER_FORBIDDEN", "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND"]
)
def test_foreign_or_missing_parent_denied_before_source_materialization(failure: str) -> None:
    service, snapshots, reads, port, _ = configured()
    reads.failure = failure
    with pytest.raises(ApiError, match=failure):
        service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    assert not snapshots.calls and not port.calls


def test_revoked_source_is_not_overridden_by_historical_failure() -> None:
    service, snapshots, _, port, _ = configured()
    snapshots.failure = "INFERENCE_TRANSFER_FORBIDDEN"
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_FORBIDDEN"):
        service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    assert not port.calls


@pytest.mark.parametrize("state", ["RUNNING", "REQUESTED", "CANCELLED"])
def test_nonfailed_parent_is_not_retry_eligible(state: str) -> None:
    service, snapshots, reads, port, _ = configured()
    reads.body.update(workflow_state=state, failure_code=None)
    if state in {"RUNNING", "REQUESTED"}:
        reads.body["result_state"] = "PENDING"
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    assert not port.calls


@pytest.mark.parametrize("field", ["access_policy_sha256", "access_policy_revision_id"])
def test_changed_original_policy_is_explicit_conflict(field: str) -> None:
    service, snapshots, reads, port, _ = configured()
    reads.body[field] = (
        "sha256:" + "f" * 64 if field.endswith("sha256") else "accessrev_" + "f" * 32
    )
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_CONFLICT"):
        service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    assert not port.calls


@pytest.mark.parametrize("version", [0, -1, True])
def test_retry_requires_positive_exact_integer_version(version: int) -> None:
    service, snapshots, _, port, _ = configured()
    authorized = service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INVALID"):
        service.retry(
            authorized, retry_actor(), expected_version=version, idempotency_key="same-key"
        )
    assert not port.calls


def test_changed_actual_actor_permissions_are_not_a_cached_permission_token() -> None:
    service, snapshots, _, port, _ = configured()
    authorized = service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    actor = retry_actor().model_copy(
        update={"permissions": PERMISSIONS - {PermissionKey.ITEM_READ}}
    )
    with pytest.raises(ApiError, match="PERMISSION_DENIED"):
        service.retry(authorized, actor, expected_version=4, idempotency_key="same-key")
    assert not port.calls
