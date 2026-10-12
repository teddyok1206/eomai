"""Successor fixed transport and exact typed responses; fake peers, never live calls."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_api.services import inference_transfer_workflow_client as client
from eom_api.services.inference_transfer_workflow_read import InferenceTransferWorkflowReadError
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_pair_submit_request_v11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import (
    COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS,
)
from eom_catalog_contracts.inference_transfer_workflow_binding_v11 import (
    parse_workflow_binding_reply_v11,
    parse_workflow_binding_request_v11,
)
from eom_catalog_service.inference_transfer_workflow_dispatch import (
    dispatch_inference_transfer_workflow_frame,
)
from eom_catalog_service.inference_transfer_workflow_read import (
    CatalogInferenceTransferWorkflowReadService,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import decode_chat_frame

from tests.unit.inference_transfer_invocation_fixtures import (
    ACTOR_ID,
    WORKFLOW_ID,
    read_request,
    read_result,
    rehash,
    submit_request,
)
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_body_v11
from tests.unit.test_inference_transfer_owner_http import TOKEN, connection, wrapper
from tests.unit.test_inference_transfer_owner_http_comparisons import KEY, command, session


def selection_v11() -> InferenceTransferPairSubmitRequestV11:
    body = submit_request().model_dump(mode="json")
    body["schema_version"] = "inference-transfer-pair-submit/1.1"
    return parse_pair_submit_request_v11(rehash(body, "submission_sha256"))


def query_v11(mode: str = "CANONICAL_RESULT") -> InferenceTransferWorkflowReadRequestV11:
    body = read_request(mode).model_dump(mode="json")
    body["schema_version"] = "inference-transfer-workflow-read-request/1.1"
    return parse_workflow_read_request_v11(rehash(body, "read_sha256"))


def response_v11(mode: str = "CANONICAL_RESULT") -> InferenceTransferWorkflowReadResultV11:
    body = read_result(verified=mode == "CANONICAL_RESULT").model_dump(mode="json")
    body["schema_version"] = "inference-transfer-workflow-read-result/1.1"
    body["result_artifact"]["schema_ref"] = (
        "https://eom.local/schemas/workflow/roles/item-inference-transfer-pair-result-v2.schema.json"
    )
    if body["result"] is not None:
        body["result"] = pair_result_body_v11()
    return parse_workflow_read_result_v11(rehash(body, "result_sha256"))


def binding_body() -> dict[str, Any]:
    return rehash(
        {
            "schema_version": "inference-transfer-workflow-binding-request/1.1",
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "actor_id": ACTOR_ID,
            "request": query_v11().model_dump(mode="json"),
        },
        "binding_sha256",
    )


def test_fixed_dispatch_accepts_only_explicit_new_binding_and_calls_current_owner_v11() -> None:
    owner = Mock(spec=CatalogInferenceTransferWorkflowReadService)
    owner.read_v11.return_value = response_v11()
    request = parse_workflow_binding_request_v11(binding_body())
    raw = dispatch_inference_transfer_workflow_frame(owner, canonical_json_bytes(request) + b"\n")
    reply = parse_workflow_binding_reply_v11(decode_chat_frame(raw[:-1]))
    assert reply.status == "SUCCESS" and reply.result == response_v11()
    owner.read_v11.assert_called_once_with(ACTOR_ID, query_v11())
    owner.read.assert_not_called()
    assert reply.request_binding_sha256 == request.binding_sha256


def test_new_dispatch_does_not_promote_old_owner_result_to_axes() -> None:
    owner = Mock(spec=CatalogInferenceTransferWorkflowReadService)
    owner.read_v11.return_value = read_result()
    raw = dispatch_inference_transfer_workflow_frame(
        owner, canonical_json_bytes(binding_body()) + b"\n"
    )
    reply = parse_workflow_binding_reply_v11(decode_chat_frame(raw[:-1]))
    assert reply.status == "FAILED" and reply.error_code == "INFERENCE_TRANSFER_RESULT_INVALID"
    assert reply.result is None


def test_api_client_binds_actual_actor_and_exact_new_request_without_model_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def exchange(_endpoint: object, body: dict[str, Any], **limits: Any) -> dict[str, Any]:
        calls.append(body)
        request = parse_workflow_binding_request_v11(body)
        assert limits["timeout"] == 120.0
        return rehash(
            {
                "schema_version": "inference-transfer-workflow-binding-reply/1.1",
                "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
                "actor_id": request.actor_id,
                "request_binding_sha256": request.binding_sha256,
                "status": "SUCCESS",
                "result": response_v11().model_dump(mode="json"),
                "error_code": None,
            },
            "reply_sha256",
        )

    monkeypatch.setattr(client, "exchange_chat_frame", exchange)
    value = client.CatalogInferenceTransferWorkflowClient(cast(Any, object()))
    assert value.execute_v11(ACTOR_ID, query_v11()) == response_v11()
    assert calls[0] == binding_body()


def test_api_client_rejects_wrong_generation_before_result_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client,
        "exchange_chat_frame",
        lambda *_args, **_kwargs: {
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "schema_version": "inference-transfer-workflow-binding-reply/1.0",
        },
    )
    value = client.CatalogInferenceTransferWorkflowClient(cast(Any, object()))
    with pytest.raises(InferenceTransferWorkflowReadError, match="WORKFLOW_UNAVAILABLE"):
        value.execute_v11(ACTOR_ID, query_v11())


@pytest.mark.parametrize("new_entry", [False, True])
def test_public_client_entry_requires_its_exact_generation_before_transport(
    monkeypatch: pytest.MonkeyPatch, new_entry: bool
) -> None:
    transport = Mock()
    monkeypatch.setattr(client, "exchange_chat_frame", transport)
    value = client.CatalogInferenceTransferWorkflowClient(cast(Any, object()))
    with pytest.raises(InferenceTransferWorkflowReadError, match="WORKFLOW_REQUEST_INVALID"):
        if new_entry:
            value.execute_v11(ACTOR_ID, cast(Any, read_request()))
        else:
            value.execute(ACTOR_ID, cast(Any, query_v11()))
    transport.assert_not_called()


@pytest.mark.parametrize("new_entry", [False, True])
def test_public_http_submit_entry_does_not_implicitly_upgrade_or_downgrade(
    monkeypatch: pytest.MonkeyPatch, new_entry: bool
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    with pytest.raises(ControlPlaneError) as caught:
        if new_entry:
            value.submit_pair_v11(cast(Any, submit_request()), idempotency_key=KEY)
        else:
            value.submit_pair(cast(Any, selection_v11()), idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_INVALID"
    assert not transport.events


def test_http_submit_uses_new_route_retains_same_key_and_pre_post_current_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    expected = command(status_url=http._COMPARISON_WORKFLOWS + WORKFLOW_ID + "/v1.1")
    transport = connection(
        monkeypatch,
        canonical_json_bytes(wrapper(expected)),
        status=202,
        expected_timeout=COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS,
    )
    assert value.submit_pair_v11(selection_v11(), idempotency_key=KEY) == expected
    method, target, body, headers = transport.requests[0]
    assert (method, target) == ("POST", http._COMPARISONS + "/v1.1")
    assert body == canonical_json_bytes(selection_v11())
    assert headers["Idempotency-Key"] == KEY
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]
    assert calls == ["ME"] * 3


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_http_read_preserves_exact_new_mode_profile_graph_policy_and_axe_content(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    value, calls = session(monkeypatch)
    expected = response_v11(mode)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(expected)))
    assert value.read_comparison_v11(query_v11(mode), selection=selection_v11()) == expected
    assert transport.requests[0][:2] == (
        "GET",
        http._COMPARISON_WORKFLOWS + WORKFLOW_ID + "/v1.1?mode=" + mode,
    )
    assert calls == ["ME"] * 3


def test_http_new_read_rejects_legacy_result_instead_of_filling_unevaluated_axes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    connection(monkeypatch, canonical_json_bytes(wrapper(read_result())))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison_v11(query_v11(), selection=selection_v11())
    assert caught.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


def test_new_post_uncertainty_never_retries_or_leaks_transport_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(
        monkeypatch,
        b"{}",
        status=202,
        expected_timeout=COMPARISON_SUBMISSION_HTTP_TIMEOUT_SECONDS,
    )
    monkeypatch.setattr(transport, "getresponse", Mock(side_effect=TimeoutError(TOKEN)))
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair_v11(selection_v11(), idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert len(transport.requests) == 1
    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None
