"""Offline private transport/principal adapters; no socket, auth, SQL, or model calls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_snapshot_staging import (
    AuthenticatedApiSnapshotStagingAdapter,
)
from eom_api.services.inference_transfer_workflow_client import (
    CatalogInferenceTransferWorkflowClient,
)
from eom_api.services.inference_transfer_workflow_read import InferenceTransferWorkflowReadError
from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    InferenceTransferWorkflowBindingReply,
    parse_workflow_binding_request,
)
from eom_identifiers import content_sha256
from eom_identity_service.tokens import AccessAuthentication
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure

from tests.unit.inference_transfer_api_fixtures import ACTOR_ID, authentication
from tests.unit.inference_transfer_invocation_fixtures import read_request, read_result, rehash
from tests.unit.inference_transfer_snapshot_fixtures import hashed, snapshot_prepare_result


class Exchange:
    def __init__(self) -> None:
        self.calls: list[tuple[ChatSocketEndpoint, dict[str, object], dict[str, Any]]] = []
        self.reply: dict[str, Any] | None = None
        self.failure: Exception | None = None

    def __call__(
        self,
        endpoint: ChatSocketEndpoint,
        body: dict[str, object],
        **settings: Any,
    ) -> dict[str, object]:
        self.calls.append((endpoint, body, settings))
        if self.failure is not None:
            raise self.failure
        if self.reply is not None:
            return self.reply
        query = parse_workflow_binding_request(body)
        return hashed(
            InferenceTransferWorkflowBindingReply,
            "reply_sha256",
            actor_id=query.actor_id,
            request_binding_sha256=query.binding_sha256,
            status="SUCCESS",
            result=read_result(verified=query.request.mode == "CANONICAL_RESULT"),
            error_code=None,
        ).model_dump(mode="json")


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> Exchange:
    value = Exchange()
    monkeypatch.setattr(
        "eom_api.services.inference_transfer_workflow_client.exchange_chat_frame", value
    )
    return value


def test_catalog_client_uses_fixed_actual_peer_and_bounded_closed_binding(
    exchange: Exchange, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid_lookups: list[str] = []
    gid_lookups: list[str] = []

    def uid(name: str) -> SimpleNamespace:
        uid_lookups.append(name)
        return SimpleNamespace(pw_uid=701)

    def gid(name: str) -> SimpleNamespace:
        gid_lookups.append(name)
        return SimpleNamespace(gr_gid=702)

    monkeypatch.setattr("eom_api.services.inference_transfer_workflow_client.pwd.getpwnam", uid)
    monkeypatch.setattr("eom_api.services.inference_transfer_workflow_client.grp.getgrnam", gid)
    query = read_request()
    response = CatalogInferenceTransferWorkflowClient().execute(ACTOR_ID, query)
    assert response == read_result()
    endpoint, body, settings = exchange.calls[0]
    assert endpoint == ChatSocketEndpoint(Path(CATALOG_APPLICATION_SOCKET_PATH), 701, 702)
    assert uid_lookups == ["eom-catalog-manager"] and gid_lookups == ["eom-api"]
    binding = parse_workflow_binding_request(body)
    assert binding.actor_id == ACTOR_ID and binding.request == query
    assert settings == {
        "request_limit": MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
        "reply_limit": MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
        "timeout": 120.0,
    }
    assert set(body) == {"schema_version", "operation", "actor_id", "request", "binding_sha256"}


@pytest.mark.parametrize(
    "field,value",
    (("schema_version", "workflow-result/0.0"), ("operation", "INFERENCE_TRANSFER_SNAPSHOT")),
)
def test_private_predecessor_or_other_operation_is_unavailable_not_semantically_reused(
    exchange: Exchange, field: str, value: str
) -> None:
    exchange.reply = {
        "schema_version": "inference-transfer-workflow-binding-reply/1.0",
        "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
        field: value,
    }
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient(
            ChatSocketEndpoint(Path("/fake/socket"), 1, 2)
        ).execute(ACTOR_ID, read_request())
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"


@pytest.mark.parametrize(
    "change", ("ACTOR", "REQUEST_HASH", "REPLY_HASH", "WORKFLOW", "MODE", "RESULT_HASH")
)
def test_client_rejects_foreign_or_tampered_success_context(
    exchange: Exchange, change: str
) -> None:
    query = read_request("STATUS_ONLY")
    body = {
        "schema_version": "inference-transfer-workflow-binding-request/1.0",
        "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
        "actor_id": ACTOR_ID,
        "request": query.model_dump(mode="json"),
    }
    binding_sha256 = content_sha256(body)
    value = hashed(
        InferenceTransferWorkflowBindingReply,
        "reply_sha256",
        actor_id=ACTOR_ID,
        request_binding_sha256=binding_sha256,
        status="SUCCESS",
        result=read_result(verified=False),
        error_code=None,
    ).model_dump(mode="json")
    if change == "ACTOR":
        value["actor_id"] = "operator_" + "f" * 32
    elif change == "REQUEST_HASH":
        value["request_binding_sha256"] = content_sha256("other request")
    elif change == "REPLY_HASH":
        value["reply_sha256"] = content_sha256("tampered")
    elif change == "WORKFLOW":
        value["result"]["workflow_id"] = "workflow_" + "f" * 32
        value["result"] = rehash(value["result"], "result_sha256")
    elif change == "MODE":
        value["result"] = read_result(verified=True).model_dump(mode="json")
    else:
        value["result"]["result_sha256"] = content_sha256("tampered")
    if change != "REPLY_HASH":
        value = rehash(value, "reply_sha256")
    exchange.reply = value
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient(
            ChatSocketEndpoint(Path("/fake/socket"), 1, 2)
        ).execute(ACTOR_ID, query)
    assert error.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


@pytest.mark.parametrize(
    "error",
    (
        ChatTransportError("UNAVAILABLE"),
        ChatTransportError("INVALID"),
        OSError("synthetic unavailable"),
        KeyError("synthetic missing UID"),
    ),
)
def test_private_transport_failure_does_not_retry_or_expand_peer(
    exchange: Exchange, error: Exception
) -> None:
    exchange.failure = error
    with pytest.raises(InferenceTransferWorkflowReadError) as raised:
        CatalogInferenceTransferWorkflowClient(
            ChatSocketEndpoint(Path("/fake/socket"), 1, 2)
        ).execute(ACTOR_ID, read_request())
    assert raised.value.code == "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
    assert len(exchange.calls) == 1


@pytest.mark.parametrize("actor_id", ("ADMIN", "worker_" + "a" * 32))
def test_invalid_private_actor_never_reaches_transport(exchange: Exchange, actor_id: str) -> None:
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute(actor_id, read_request())
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
    assert not exchange.calls


def test_model_copy_read_request_hash_bypass_is_rejected_before_transport(
    exchange: Exchange,
) -> None:
    query = read_request().model_copy(update={"read_sha256": content_sha256("tampered")})
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient().execute(ACTOR_ID, query)
    assert error.value.code == "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
    assert not exchange.calls


@pytest.mark.parametrize("bound", (True, False))
def test_failed_reply_is_safe_denial_even_without_parseable_request_context(
    exchange: Exchange, bound: bool
) -> None:
    query = read_request()
    body = {
        "schema_version": "inference-transfer-workflow-binding-request/1.0",
        "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
        "actor_id": ACTOR_ID,
        "request": query.model_dump(mode="json"),
    }
    exchange.reply = hashed(
        InferenceTransferWorkflowBindingReply,
        "reply_sha256",
        actor_id=ACTOR_ID if bound else None,
        request_binding_sha256=content_sha256(body) if bound else None,
        status="FAILED",
        result=None,
        error_code="INFERENCE_TRANSFER_FORBIDDEN",
    ).model_dump(mode="json")
    with pytest.raises(InferenceTransferWorkflowReadError) as error:
        CatalogInferenceTransferWorkflowClient(
            ChatSocketEndpoint(Path("/fake/socket"), 1, 2)
        ).execute(ACTOR_ID, query)
    assert error.value.code == "INFERENCE_TRANSFER_FORBIDDEN"


class SnapshotApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[AccessAuthentication, InferenceTransferSnapshotRequest]] = []
        self.failure: ApiError | None = None

    def execute(
        self, actual: AccessAuthentication, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actual, request))
        if self.failure is not None:
            raise self.failure
        return snapshot_prepare_result()


def test_staging_adapter_keeps_captured_authentication_and_cannot_impersonate_actor() -> None:
    snapshots = SnapshotApplication()
    actual = authentication()
    adapter = AuthenticatedApiSnapshotStagingAdapter(actual, snapshots)  # type: ignore[arg-type]
    query = snapshot_prepare_result().header.prepare
    with pytest.raises(SnapshotReadFailure) as error:
        adapter.execute("operator_" + "f" * 32, query)
    assert error.value.code == "INFERENCE_TRANSFER_FORBIDDEN" and not snapshots.calls
    assert adapter.execute(ACTOR_ID, query) == snapshot_prepare_result()
    assert snapshots.calls == [(actual, query)] and snapshots.calls[0][0] is actual


@pytest.mark.parametrize(
    "code,expected",
    (
        ("PERMISSION_DENIED", "INFERENCE_TRANSFER_FORBIDDEN"),
        ("INFERENCE_TRANSFER_SNAPSHOT_CHANGED", "INFERENCE_TRANSFER_SNAPSHOT_CHANGED"),
        ("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH", "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"),
        (
            "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
            "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
        ),
        ("INFERENCE_TRANSFER_FORBIDDEN", "INFERENCE_TRANSFER_FORBIDDEN"),
        ("INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID", "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"),
        ("UNKNOWN_CONTAINING_budget_EXCEEDED", "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"),
    ),
)
def test_staging_adapter_only_explicit_budget_failure_enables_read_splitting(
    code: str, expected: str
) -> None:
    snapshots = SnapshotApplication()
    snapshots.failure = ApiError(
        503, code, "Synthetic failure", "Private detail is not a retry rule."
    )
    adapter = AuthenticatedApiSnapshotStagingAdapter(authentication(), snapshots)  # type: ignore[arg-type]
    with pytest.raises(SnapshotReadFailure) as error:
        adapter.execute(ACTOR_ID, snapshot_prepare_result().header.prepare)
    assert error.value.code == expected and len(snapshots.calls) == 1
