"""Fake explicit successor transport; no live auth, parent mutation, DB or worker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import Mock

import pytest
from eom_api_contracts.common import CommandResult
from eom_catalog_contracts.inference_transfer_invocation_v11 import parse_pair_submit_request_v11
from eom_catalog_contracts.inference_transfer_retry import (
    InferenceTransferPairRetryRequestV1,
    parse_pair_retry_request_v1,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import SecretStr

from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID, rehash, submit_request
from tests.unit.test_inference_transfer_owner_http import TOKEN, connection, principal, wrapper
from tests.unit.test_inference_transfer_owner_http_comparisons import PERMISSIONS, session

CHILD = "workflow_" + "c" * 32
KEY = "synthetic-inference-transfer-retry-0001"
VERSION = 7
PATH = http._COMPARISON_WORKFLOWS + WORKFLOW_ID + "/retries/v1.1"


def retry_request() -> InferenceTransferPairRetryRequestV1:
    selected = parse_pair_submit_request_v11(
        rehash(
            submit_request().model_dump(mode="json")
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


def accepted(**changes: Any) -> CommandResult:
    return CommandResult.model_validate(
        {
            "command_id": "wfcmd_" + "d" * 32,
            "resource_type": "workflow",
            "resource_id": CHILD,
            "status": "ACCEPTED",
            "resource_version": 1,
            "status_url": http._COMPARISON_WORKFLOWS + CHILD + "/v1.1",
        }
        | changes
    )


def test_retry_preserves_parent_body_if_match_key_and_returns_child_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    request = retry_request()
    transport = connection(
        monkeypatch, canonical_json_bytes(wrapper(accepted())), status=202, expected_timeout=510
    )
    assert (
        value.retry_comparison_v11(
            WORKFLOW_ID, request, expected_version=VERSION, idempotency_key=KEY
        )
        == accepted()
    )
    method, path, body, headers = transport.requests[0]
    assert (method, path) == ("POST", PATH)
    assert body == canonical_json_bytes(request.model_dump(mode="json"))
    assert headers["If-Match"] == '"v7"' and headers["Idempotency-Key"] == KEY
    assert headers["Authorization"] == "Bearer " + TOKEN
    assert calls == ["ME", "ME", "ME"] and len(transport.requests) == 1
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]


@pytest.mark.parametrize(
    "changes",
    [
        {"parent_workflow_id": "workflow_" + "a" * 31},
        {"parent_workflow_id": WORKFLOW_ID + "/../auth/me"},
        {"parent_workflow_id": WORKFLOW_ID + "?latest=true"},
        {"expected_version": True},
        {"expected_version": 0},
        {"expected_version": -1},
        {"expected_version": 1.0},
        {"idempotency_key": "short"},
        {"idempotency_key": "a" * 16 + "\r\n"},
        {"request": retry_request().model_copy(update={"failed_attempt": 2})},
        {"request": retry_request().model_copy(update={"retry_sha256": "sha256:" + "f" * 64})},
        {"request": retry_request().model_copy(update={"reason": " "})},
        {"request": {"selection": "not an explicit DTO"}},
    ],
)
def test_invalid_retry_is_rejected_before_auth_or_http(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202, expected_timeout=510)
    kwargs: dict[str, Any] = {
        "parent_workflow_id": WORKFLOW_ID,
        "request": retry_request(),
        "expected_version": VERSION,
        "idempotency_key": KEY,
    }
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(**(kwargs | changes))
    assert caught.value.code == "INFERENCE_TRANSFER_RETRY_INVALID"
    assert transport.events == [] and calls == ["ME"]
    assert caught.value.__cause__ is None and TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_id": WORKFLOW_ID},
        {"command_id": "codexcmd_" + "a" * 32},
        {"resource_type": "item"},
        {"status": "COMPLETED"},
        {"status_url": http._COMPARISON_WORKFLOWS + WORKFLOW_ID + "/v1.1"},
        {"status_url": http._COMPARISON_WORKFLOWS + CHILD},
        {"resource_version": True},
        {"extra": TOKEN},
    ],
)
def test_invalid_accepted_child_reply_is_uncertain_without_a_new_execution(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(
        monkeypatch,
        canonical_json_bytes(wrapper(accepted().model_dump(mode="json") | changes)),
        status=202,
        expected_timeout=510,
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, retry_request(), expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert len(transport.requests) == 1 and TOKEN not in str(caught.value)


def test_retry_timeout_is_unknown_and_exact_explicit_replay_preserves_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    request = retry_request()
    transport = connection(monkeypatch, b"{}", status=202, expected_timeout=510)
    monkeypatch.setattr(transport, "getresponse", Mock(side_effect=TimeoutError(TOKEN)))
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, request, expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert len(transport.requests) == 1 and calls == ["ME", "ME"]
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None
    replay = connection(
        monkeypatch, canonical_json_bytes(wrapper(accepted())), status=202, expected_timeout=510
    )
    assert (
        value.retry_comparison_v11(
            WORKFLOW_ID, request, expected_version=VERSION, idempotency_key=KEY
        )
        == accepted()
    )
    assert transport.requests == replay.requests


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "bad", "CONTROL_AUTHORIZATION_REQUIRED"),
        (403, "INFERENCE_TRANSFER_FORBIDDEN", "CONTROL_AUTHORIZATION_REQUIRED"),
        (409, "API_IDEMPOTENCY_IN_PROGRESS", "API_IDEMPOTENCY_IN_PROGRESS"),
        (409, "INFERENCE_TRANSFER_RETRY_CONFLICT", "INFERENCE_TRANSFER_RETRY_CONFLICT"),
        (422, "INFERENCE_TRANSFER_RETRY_INELIGIBLE", "INFERENCE_TRANSFER_RETRY_INELIGIBLE"),
        (412, "API_PRECONDITION_FAILED", "API_PRECONDITION_FAILED"),
        (500, TOKEN, "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"),
    ],
)
def test_retry_rejection_or_unknown_reply_has_no_automatic_resubmission(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, expected: str
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(
        monkeypatch, canonical_json_bytes({"error_code": code}), status=status, expected_timeout=510
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, retry_request(), expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == expected and len(transport.requests) == 1
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_permissions": []},
        {
            "effective_permissions": [
                "workflow:start",
                "item:read",
                "knowledge_graph:retrieve",
                "knowledge_analysis:read",
                "content_intake:read",
            ]
        },
        {"operator_id": "operator_" + "e" * 32},
        {"session_id": "apisession_" + "e" * 32},
        {"roles": ["WORKER"]},
    ],
)
def test_retry_post_response_rechecks_exact_actor_session_and_both_workflow_permissions(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, calls = session(monkeypatch, final_changes=changes)
    transport = connection(
        monkeypatch, canonical_json_bytes(wrapper(accepted())), status=202, expected_timeout=510
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, retry_request(), expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert len(transport.requests) == 1 and calls == ["ME", "ME", "ME"]


def test_retry_missing_parent_read_permission_is_rejected_before_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    monkeypatch.setattr(
        value,
        "_reader",
        SimpleNamespace(
            read=lambda: principal(
                effective_permissions=tuple(p for p in PERMISSIONS if p != "workflow:read")
            )
        ),
    )
    transport = connection(monkeypatch, b"{}", status=202, expected_timeout=510)
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, retry_request(), expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert transport.events == []


def test_wrong_retry_peer_never_sends_body_version_key_or_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202, expected_timeout=510)
    monkeypatch.setattr(http, "require_fixed_api_peer_socket", Mock(side_effect=ValueError(TOKEN)))
    with pytest.raises(ControlPlaneError) as caught:
        value.retry_comparison_v11(
            WORKFLOW_ID, retry_request(), expected_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert transport.requests == [] and transport.events == ["FACTORY", "CONNECT", "CLOSE"]
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


def steps_reply(**changes: Any) -> dict[str, Any]:
    return {
        "data": [
            {
                "step_run_id": "steprun_" + "a" * 32,
                "workflow_id": WORKFLOW_ID,
                "step_key": "compare-pair",
                "attempt": 1,
                "step_type": "AGENT_EXECUTE",
                "worker_role": "support",
                "state": "FAILED",
                "started_at": "2026-10-12T00:00:00Z",
                "finished_at": "2026-10-12T00:01:00Z",
                "error_code": "WORKER_RESULT_INVALID",
            }
            | changes
        ],
        "page": {"limit": 200, "has_more": False, "next_cursor": None},
        "meta": {"request_id": "synthetic-step-read", "api_version": "1"},
    }


def test_step_metadata_uses_fixed_existing_read_and_does_not_retry_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    raw = steps_reply()
    transport = connection(monkeypatch, canonical_json_bytes(raw), expected_timeout=120)
    result = value.get_workflow_steps(WORKFLOW_ID)
    assert result.model_dump(mode="json") == raw
    assert transport.requests[0][:2] == ("GET", "/api/v1/workflows/" + WORKFLOW_ID + "/steps")
    assert calls == ["ME", "ME", "ME"]
    assert "If-Match" not in transport.requests[0][3]


@pytest.mark.parametrize(
    "changes",
    [{"workflow_id": CHILD}, {"step_run_id": "foreign"}, {"attempt": True}, {"extra": TOKEN}],
)
def test_step_reply_identity_or_schema_mismatch_does_not_grant_retry(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes(steps_reply(**changes)))
    with pytest.raises(ControlPlaneError) as caught:
        value.get_workflow_steps(WORKFLOW_ID)
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert len(transport.requests) == 1 and transport.requests[0][0] == "GET"


@pytest.mark.parametrize(
    "method,path,version",
    [
        ("POST", PATH + "?latest=true", VERSION),
        ("POST", PATH.replace("/v1.1", "/v1.0"), VERSION),
        ("POST", PATH, None),
        ("POST", PATH, True),
        ("GET", PATH, None),
        ("POST", http._COMPARISONS_V11, VERSION),
    ],
)
def test_transport_accepts_if_match_only_on_exact_supported_retry_post(
    monkeypatch: pytest.MonkeyPatch,
    method: Literal["GET", "POST"],
    path: str,
    version: int | None,
) -> None:
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError):
        http._request(
            method,
            path,
            canonical_json_bytes(retry_request().model_dump(mode="json"))
            if method == "POST"
            else None,
            bearer=SecretStr(TOKEN),
            idempotency_key=KEY,
            expected_resource_version=version,
        )
    assert transport.events == []
