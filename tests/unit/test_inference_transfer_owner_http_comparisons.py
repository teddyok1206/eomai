"""Fake fixed-peer comparison HTTP tests; no actual authorization, worker or publication."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

import pytest
from eom_api_contracts.common import CommandResult
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import SecretStr

from tests.unit.inference_transfer_invocation_fixtures import (
    WORKFLOW_ID,
    read_request,
    read_result,
    rehash,
    submit_request,
)
from tests.unit.test_inference_transfer_owner_http import (
    ACTOR,
    SESSION,
    TOKEN,
    connection,
    principal,
    wrapper,
)

KEY = "inference-transfer-test-key-001"
PERMISSIONS = tuple(
    permission.value
    for permission in (
        PermissionKey.WORKFLOW_START,
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    )
)


def command(**changes: Any) -> CommandResult:
    return CommandResult.model_validate(
        {
            "command_id": "wfcmd_" + "c" * 32,
            "resource_type": "workflow",
            "resource_id": WORKFLOW_ID,
            "status": "ACCEPTED",
            "resource_version": 1,
            "status_url": http._COMPARISON_WORKFLOWS + WORKFLOW_ID,
        }
        | changes
    )


def session(
    monkeypatch: pytest.MonkeyPatch, *, final_changes: dict[str, Any] | None = None
) -> tuple[http.AuthenticatedInferenceTransferHttpSession, list[str]]:
    calls: list[str] = []

    def read() -> Any:
        calls.append("ME")
        changes = final_changes if len(calls) >= 3 else None
        return principal(**({"effective_permissions": PERMISSIONS} | (changes or {})))

    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=read)
    )
    return http.AuthenticatedInferenceTransferHttpSession.from_bearer(SecretStr(TOKEN)), calls


def test_submission_preserves_exact_body_key_command_and_pre_post_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    selection, expected = submit_request(), command()
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(expected)), status=202)
    assert value.submit_pair(selection, idempotency_key=KEY) == expected
    method, path, payload, headers = transport.requests[0]
    assert (method, path) == ("POST", http._COMPARISONS)
    assert payload == canonical_json_bytes(selection.model_dump(mode="json"))
    assert headers["Idempotency-Key"] == KEY and headers["Authorization"] == "Bearer " + TOKEN
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]
    assert calls == ["ME", "ME", "ME"]


def test_wrong_submission_peer_never_sends_key_or_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    monkeypatch.setattr(
        http,
        "require_fixed_api_peer_socket",
        lambda _sock: (_ for _ in ()).throw(ValueError(TOKEN)),
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(submit_request(), idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert transport.requests == []
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize("key", ["", "short", "a" * 129, "a" * 16 + "\r\n", "가" * 16, "a b" * 6])
def test_invalid_key_rejected_before_http_and_no_secret_context(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(submit_request(), idempotency_key=key)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_INVALID"
    assert transport.events == [] and calls == ["ME"]


def test_schema_model_copy_bypass_is_revalidated_before_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    selection = submit_request().model_copy(update={"submission_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(selection, idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_INVALID"
    assert transport.events == [] and calls == ["ME"]


def test_timeout_is_uncertain_once_and_does_not_retry_post(monkeypatch: pytest.MonkeyPatch) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    original = transport.request

    def send(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise TimeoutError(TOKEN)

    monkeypatch.setattr(transport, "request", send)
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(submit_request(), idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"
    assert len(transport.requests) == 1 and calls == ["ME", "ME"]
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


def test_explicit_exact_replay_keeps_same_key_body_and_rechecks_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(command())), status=202)
    selection = submit_request()
    first = value.submit_pair(selection, idempotency_key=KEY)
    second = value.submit_pair(selection, idempotency_key=KEY)
    assert first == second
    assert len(transport.requests) == 2 and transport.requests[0] == transport.requests[1]
    assert calls == ["ME"] * 5


def test_previous_command_receipt_does_not_authorize_replay_after_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(command())), status=202)
    selection = submit_request()
    assert value.submit_pair(selection, idempotency_key=KEY) == command()
    monkeypatch.setattr(
        value, "_reader", SimpleNamespace(read=lambda: principal(effective_permissions=[]))
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(selection, idempotency_key=KEY)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_type": "item"},
        {"resource_id": "item_" + "d" * 32},
        {"command_id": "job_" + "d" * 32},
        {"status": "COMPLETED"},
        {"status_url": "/api/v1/workflows/" + WORKFLOW_ID},
        {"status_url": http._COMPARISON_WORKFLOWS + "workflow_" + "d" * 32},
    ],
)
def test_accepted_response_must_be_exact_comparison_command(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    connection(monkeypatch, canonical_json_bytes(wrapper(command(**changes))), status=202)
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(submit_request(), idempotency_key=KEY)
    assert caught.value.code == "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "bad", "CONTROL_AUTHORIZATION_REQUIRED"),
        (403, "INFERENCE_TRANSFER_FORBIDDEN", "CONTROL_AUTHORIZATION_REQUIRED"),
        (409, "INFERENCE_TRANSFER_SNAPSHOT_CHANGED", "INFERENCE_TRANSFER_SNAPSHOT_CHANGED"),
        (409, "API_IDEMPOTENCY_IN_PROGRESS", "API_IDEMPOTENCY_IN_PROGRESS"),
        (503, "INFERENCE_TRANSFER_NOT_READY", "INFERENCE_TRANSFER_NOT_READY"),
        (500, TOKEN, "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"),
        (301, "bad", "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN"),
    ],
)
def test_submission_status_error_is_closed_secret_safe_and_no_retry(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, expected: str
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(
        monkeypatch, canonical_json_bytes({"error_code": code, "detail": TOKEN}), status=status
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.submit_pair(submit_request(), idempotency_key=KEY)
    assert caught.value.code == expected and TOKEN not in str(caught.value)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_comparison_read_preserves_mode_state_and_exact_selection(
    monkeypatch: pytest.MonkeyPatch, mode: str, state: str
) -> None:
    value, calls = session(monkeypatch)
    expected = read_result(state, verified=mode == "CANONICAL_RESULT")
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(expected)))
    query = read_request(mode)
    assert value.read_comparison(query, selection=submit_request()) == expected
    assert transport.requests[0][:2] == (
        "GET",
        http._COMPARISON_WORKFLOWS + WORKFLOW_ID + "?mode=" + mode,
    )
    assert calls == ["ME", "ME", "ME"]
    if state != "COMPLETED" or mode == "STATUS_ONLY":
        assert expected.result is None


@pytest.mark.parametrize(
    "suffix",
    [
        WORKFLOW_ID,
        WORKFLOW_ID + "?mode=OTHER",
        WORKFLOW_ID + "?mode=CANONICAL_RESULT&actor_id=" + ACTOR,
        WORKFLOW_ID + "?mode=CANONICAL_RESULT#fragment",
        WORKFLOW_ID + "/../auth/me?mode=STATUS_ONLY",
        "workflow_a?mode=STATUS_ONLY",
    ],
)
def test_dynamic_comparison_get_path_is_closed_before_connect(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError):
        http._get(http._COMPARISON_WORKFLOWS + suffix, bearer=SecretStr(TOKEN))
    assert transport.events == []


def test_idempotency_header_only_allowed_on_actual_comparison_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = connection(monkeypatch, b"{}")
    cases: tuple[tuple[Literal["POST", "GET"], str, bytes | None, str | None], ...] = (
        ("POST", http._COMPARISONS, b"{}", None),
        ("POST", http._LOGIN, b"{}", KEY),
        ("GET", http._ORIGINAL_CORPUS, None, KEY),
    )
    for method, path, body, key in cases:
        with pytest.raises(ControlPlaneError):
            http._request(method, path, body, bearer=SecretStr(TOKEN), idempotency_key=key)
    assert transport.events == []


@pytest.mark.parametrize("workflow_id", ["../auth/me", "workflow_" + "f" * 32 + "?actor=ADMIN"])
def test_read_model_copy_cannot_inject_url(
    monkeypatch: pytest.MonkeyPatch, workflow_id: str
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}")
    query = read_request().model_copy(update={"workflow_id": workflow_id})
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(query, selection=submit_request())
    assert caught.value.code == "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
    assert transport.events == [] and calls == ["ME"]


@pytest.mark.parametrize("operation", ["submit_pair", "read_comparison"])
@pytest.mark.parametrize(
    "changes",
    [
        {"effective_permissions": []},
        {"effective_permissions": tuple(p for p in PERMISSIONS if p != "content_intake:read")},
        {"roles": ["WORKER"]},
        {"operator_id": "operator_" + "e" * 32},
        {"session_id": SESSION.replace("b", "e")},
        {"password_change_required": True},
    ],
)
def test_post_response_revocation_or_replacement_rejects_even_successful_reply(
    monkeypatch: pytest.MonkeyPatch, operation: str, changes: dict[str, Any]
) -> None:
    value, calls = session(monkeypatch, final_changes=changes)
    reply = command() if operation == "submit_pair" else read_result()
    transport = connection(
        monkeypatch,
        canonical_json_bytes(wrapper(reply)),
        status=202 if operation == "submit_pair" else 200,
    )
    with pytest.raises(ControlPlaneError) as caught:
        if operation == "submit_pair":
            value.submit_pair(submit_request(), idempotency_key=KEY)
        else:
            value.read_comparison(read_request(), selection=submit_request())
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert len(transport.requests) == 1 and calls == ["ME", "ME", "ME"]


@pytest.mark.parametrize(
    "field", ["workflow_id", "access_policy_revision_id", "access_policy_sha256"]
)
def test_read_rejects_foreign_workflow_or_policy_pins(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    value, _ = session(monkeypatch)
    raw = read_result().model_dump(mode="json")
    raw[field] = (
        "workflow_" + "e" * 32
        if field == "workflow_id"
        else "accessrev_" + "e" * 32
        if field == "access_policy_revision_id"
        else "sha256:" + "e" * 64
    )
    connection(monkeypatch, canonical_json_bytes(wrapper(rehash(raw, "result_sha256"))))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(), selection=submit_request())
    assert caught.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


def test_read_rejects_changed_graph_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = session(monkeypatch)
    raw = read_result().model_dump(mode="json")
    foreign = "graphrev_" + "f" * 32
    assert raw["graph_snapshot"]["graph_snapshot_revision_id"] != foreign
    raw["graph_snapshot"]["graph_snapshot_revision_id"] = foreign
    connection(monkeypatch, canonical_json_bytes(wrapper(rehash(raw, "result_sha256"))))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(), selection=submit_request())
    assert caught.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


def test_read_rejects_changed_comparison_request_even_when_owner_value_is_internally_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    raw = read_result("RUNNING").model_dump(mode="json")
    changed = raw["comparison"] | {"request_id": "transferrequest_" + "e" * 32}
    raw["comparison"] = rehash(changed, "request_sha256")
    connection(monkeypatch, canonical_json_bytes(wrapper(rehash(raw, "result_sha256"))))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(), selection=submit_request())
    assert caught.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_read_never_promotes_pointer_only_or_exposes_unrequested_canonical_member(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    value, _ = session(monkeypatch)
    connection(
        monkeypatch, canonical_json_bytes(wrapper(read_result(verified=mode == "STATUS_ONLY")))
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(mode), selection=submit_request())
    assert caught.value.code == "INFERENCE_TRANSFER_RESULT_INVALID"


@pytest.mark.parametrize("payload", [b"{}", b'{"data":1,"data":2}', b'{"data":NaN}', b"\xff"])
def test_read_invalid_json_or_schema_is_secret_safe_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, payload)
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(), selection=submit_request())
    assert TOKEN not in str(caught.value) and len(transport.requests) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 409, 500])
def test_read_error_codes_are_closed_and_no_redirect_or_retry(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(
        monkeypatch,
        canonical_json_bytes(
            {"error_code": "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND", "detail": TOKEN}
        ),
        status=status,
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.read_comparison(read_request(), selection=submit_request())
    assert caught.value.code == (
        "CONTROL_AUTHORIZATION_REQUIRED"
        if status in {401, 403}
        else "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND"
    )
    assert len(transport.requests) == 1 and TOKEN not in str(caught.value)
