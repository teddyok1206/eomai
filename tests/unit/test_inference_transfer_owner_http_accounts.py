"""Typed official account HTTP fake tests; no auth, native CLI, DB or network calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from eom_api_contracts.common import CommandResult
from eom_api_contracts.control_plane import (
    CodexAccountCommandRequest,
    CodexAccountView,
    CodexControlCommandView,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import SecretStr

from tests.unit.test_inference_transfer_owner_http import (
    ACTOR,
    AUTHENTICATED_AT,
    NEXT_REFRESH,
    NEXT_TOKEN,
    REFRESH_TOKEN,
    SESSION,
    TOKEN,
    connection,
    principal,
    wrapper,
)

BINDING = "authbinding_" + "a" * 32
COMMAND = "codexcmd_" + "b" * 32
KEY = "inference-transfer-observe-test-001"
VERSION = 7
PERMISSIONS = (
    PermissionKey.CODEX_ACCOUNT_READ.value,
    PermissionKey.CODEX_ACCOUNT_MANAGE.value,
)
OBSERVE = CodexAccountCommandRequest(command_type="OBSERVE")


def account(**changes: Any) -> CodexAccountView:
    return CodexAccountView.model_validate(
        {
            "binding_id": BINDING,
            "slot_key": "slot06",
            "account_label": "synthetic-only",
            "state": "READY",
            "reason_code": None,
            "codex_cli_version": "0.115.0",
            "observed_at": "2026-10-10T00:00:00Z",
            "valid_until": "2026-10-10T01:00:00Z",
            "resource_version": VERSION,
            "capabilities": [
                {"model": "gpt-5.6-terra", "reasoning_effort": "medium", "state": "AVAILABLE"}
            ],
            "active_lease_count": 0,
            "last_successful_job_id": None,
        }
        | changes
    )


def accepted(**changes: Any) -> CommandResult:
    return CommandResult.model_validate(
        {
            "command_id": COMMAND,
            "resource_type": "codex_control_command",
            "resource_id": COMMAND,
            "status": "ACCEPTED",
            "resource_version": VERSION,
            "status_url": "/api/v1/codex-control-commands/" + COMMAND,
        }
        | changes
    )


def control_command(**changes: Any) -> CodexControlCommandView:
    return CodexControlCommandView.model_validate(
        {
            "command_id": COMMAND,
            "command_type": "OBSERVE",
            "binding_id": BINDING,
            "state": "PENDING",
            "attempts": 0,
            "result_resource_version": None,
            "error_code": None,
            "requested_at": "2026-10-11T00:00:00Z",
            "processed_at": None,
        }
        | changes
    )


def listing(*values: CodexAccountView) -> dict[str, Any]:
    return {
        "data": [value.model_dump(mode="json") for value in values],
        "page": {"next_cursor": None, "has_more": False, "limit": 200},
        "meta": {"request_id": "synthetic-request", "api_version": "1"},
    }


def session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_changes: dict[str, Any] | None = None,
    final_changes: dict[str, Any] | None = None,
) -> tuple[http.AuthenticatedInferenceTransferHttpSession, list[str]]:
    calls: list[str] = []

    def read() -> Any:
        calls.append("ME")
        changes = final_changes if len(calls) >= 3 else initial_changes
        return principal(**({"effective_permissions": PERMISSIONS} | (changes or {})))

    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=read)
    )
    return http.AuthenticatedInferenceTransferHttpSession.from_bearer(SecretStr(TOKEN)), calls


@pytest.mark.parametrize("operation", ["LIST", "ACCOUNT", "COMMAND"])
def test_fixed_typed_reads_preserve_metadata_and_pre_post_authorization(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    value, calls = session(monkeypatch)
    if operation == "LIST":
        wire = listing(account(), account(binding_id="authbinding_" + "c" * 32, slot_key="slot02"))
        path = "/api/v1/codex-accounts"
    elif operation == "ACCOUNT":
        wire, path = wrapper(account()), "/api/v1/codex-accounts/" + BINDING
    else:
        wire, path = wrapper(control_command()), "/api/v1/codex-control-commands/" + COMMAND
    transport = connection(monkeypatch, canonical_json_bytes(wire))
    if operation == "LIST":
        result = value.read_codex_accounts()
        assert tuple(item.binding_id for item in result.data) == (
            BINDING,
            "authbinding_" + "c" * 32,
        )
        assert result.model_dump(mode="json") == wire
    elif operation == "ACCOUNT":
        assert value.read_codex_account(BINDING) == account()
    else:
        assert value.read_codex_control_command(COMMAND, binding_id=BINDING) == control_command()
    method, target, body, headers = transport.requests[0]
    assert (method, target) == ("GET", path)
    assert body is None
    assert headers["Authorization"] == "Bearer " + TOKEN
    assert "If-Match" not in headers and "Idempotency-Key" not in headers
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "SEND", "CLOSE"]
    assert calls == ["ME", "ME", "ME"]


def test_observe_preserves_exact_body_version_key_and_verified_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(accepted())), status=202)
    result = value.observe_codex_account(
        BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
    )
    assert result == accepted()
    method, path, payload, headers = transport.requests[0]
    assert (method, path) == ("POST", "/api/v1/codex-accounts/" + BINDING + "/commands")
    assert payload == canonical_json_bytes(OBSERVE.model_dump(mode="json"))
    assert headers["If-Match"] == '"v7"' and headers["Idempotency-Key"] == KEY
    assert headers["Authorization"] == "Bearer " + TOKEN
    assert calls == ["ME", "ME", "ME"] and len(transport.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"binding_id": "authbinding_" + "a" * 31},
        {"binding_id": BINDING + "/commands"},
        {"binding_id": BINDING + "?latest=true"},
        {"binding_id": BINDING.upper()},
        {"expected_resource_version": True},
        {"expected_resource_version": 0},
        {"expected_resource_version": -1},
        {"expected_resource_version": 1.0},
        {"expected_resource_version": "7"},
        {"idempotency_key": "short"},
        {"idempotency_key": "a" * 16 + "\r\n"},
        {"idempotency_key": "a b" * 6},
        {"request": CodexAccountCommandRequest(command_type="ENABLE")},
        {"request": CodexAccountCommandRequest(command_type="DRAIN", reason_code="MAINTENANCE")},
        {"request": OBSERVE.model_copy(update={"reason_code": "FORGED_REASON"})},
        {"request": {"command_type": "OBSERVE"}},
    ],
)
def test_invalid_observation_is_rejected_before_auth_or_http(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    kwargs: dict[str, Any] = {
        "binding_id": BINDING,
        "request": OBSERVE,
        "expected_resource_version": VERSION,
        "idempotency_key": KEY,
    }
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(**(kwargs | changes))
    assert caught.value.code == "CONTROL_ACCOUNT_REQUEST_INVALID"
    assert transport.events == [] and calls == ["ME"]
    assert caught.value.__cause__ is None and TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"command_id": "codexcmd_" + "c" * 32, "resource_id": COMMAND},
        {"resource_type": "workflow"},
        {"resource_id": "codexcmd_" + "c" * 32},
        {"status": "COMPLETED"},
        {"resource_version": VERSION + 1},
        {"resource_version": True},
        {"status_url": "/api/v1/codex-control-commands/" + COMMAND + "?latest=true"},
        {"extra": TOKEN},
    ],
)
def test_accepted_reply_closure_failure_is_uncertain_without_retry(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    reply = wrapper(accepted().model_dump(mode="json") | changes)
    transport = connection(monkeypatch, canonical_json_bytes(reply), status=202)
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(
            BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"
    assert len(transport.requests) == 1 and transport.events.count("FACTORY") == 1
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


def test_timeout_preserves_original_version_key_and_does_not_resubmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    send = transport.request

    def timeout(method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        send(method, path, body=body, headers=headers)
        raise TimeoutError(TOKEN)

    monkeypatch.setattr(transport, "request", timeout)
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(
            BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"
    assert len(transport.requests) == 1
    assert transport.requests[0][3]["If-Match"] == '"v7"'
    assert transport.requests[0][3]["Idempotency-Key"] == KEY
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "AUTH_REAUTHENTICATION_REQUIRED", "CONTROL_AUTHORIZATION_REQUIRED"),
        (403, "API_FORBIDDEN", "CONTROL_AUTHORIZATION_REQUIRED"),
        (409, "API_IDEMPOTENCY_IN_PROGRESS", "API_IDEMPOTENCY_IN_PROGRESS"),
        (409, "API_IDEMPOTENCY_CONFLICT", "API_IDEMPOTENCY_CONFLICT"),
        (409, "CONTROL_RESOURCE_VERSION_CONFLICT", "CONTROL_RESOURCE_VERSION_CONFLICT"),
        (412, "API_PRECONDITION_FAILED", "API_PRECONDITION_FAILED"),
        (428, "API_PRECONDITION_REQUIRED", "API_PRECONDITION_REQUIRED"),
        (500, TOKEN, "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"),
        (500, "API_IDEMPOTENCY_IN_PROGRESS", "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"),
        (302, "API_PRECONDITION_FAILED", "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"),
        (302, "UNKNOWN", "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"),
    ],
)
def test_known_rejection_codes_are_safe_and_unknown_outcomes_remain_uncertain(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, expected: str
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, canonical_json_bytes({"error_code": code}), status=status)
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(
            BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == expected and len(transport.requests) == 1
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("operation", ["LIST", "ACCOUNT", "OBSERVE", "COMMAND"])
@pytest.mark.parametrize("after", [False, True])
def test_required_current_permission_is_checked_before_and_after_each_operation(
    monkeypatch: pytest.MonkeyPatch, operation: str, after: bool
) -> None:
    changes: dict[str, Any] = {"effective_permissions": []}
    value, calls = session(
        monkeypatch,
        initial_changes=None if after else changes,
        final_changes=changes if after else None,
    )
    wire = (
        listing(account())
        if operation == "LIST"
        else wrapper(
            accepted()
            if operation == "OBSERVE"
            else control_command()
            if operation == "COMMAND"
            else account()
        )
    )
    transport = connection(
        monkeypatch, canonical_json_bytes(wire), status=202 if operation == "OBSERVE" else 200
    )
    with pytest.raises(ControlPlaneError) as caught:
        if operation == "LIST":
            value.read_codex_accounts()
        elif operation == "ACCOUNT":
            value.read_codex_account(BINDING)
        elif operation == "OBSERVE":
            value.observe_codex_account(
                BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
            )
        else:
            value.read_codex_control_command(COMMAND, binding_id=BINDING)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert len(transport.requests) == int(after)
    assert len(calls) == (3 if after else 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_id": "operator_" + "c" * 32},
        {"session_id": "apisession_" + "c" * 32},
        {"authenticated_at": AUTHENTICATED_AT + timedelta(seconds=1)},
        {"username": "other-user"},
        {"roles": ["REVIEWER"]},
        {"password_change_required": True},
    ],
)
def test_same_actual_actor_session_authentication_time_and_admin_guard_remain_required(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch, final_changes=changes)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(account())))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_account(BINDING)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"command_id": "codexcmd_" + "c" * 32},
        {"binding_id": "authbinding_" + "c" * 32},
        {"command_type": "ENABLE"},
        {"state": "UNKNOWN"},
        {"attempts": True},
        {"result_resource_version": 0},
        {"result_resource_version": -1},
        {"result_resource_version": True},
    ],
)
def test_poll_reply_requires_exact_observe_command_and_binding(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    reply = wrapper(control_command().model_dump(mode="json") | changes)
    transport = connection(monkeypatch, canonical_json_bytes(reply))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_control_command(COMMAND, binding_id=BINDING)
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert len(transport.requests) == 1 and transport.requests[0][0] == "GET"


@pytest.mark.parametrize("state", ["PENDING", "PROCESSING", "SUCCEEDED", "FAILED"])
def test_poll_preserves_native_nonterminal_terminal_and_failure_metadata(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    value, _ = session(monkeypatch)
    expected = control_command(
        state=state,
        attempts=0 if state == "PENDING" else 1,
        result_resource_version=VERSION + 1 if state == "SUCCEEDED" else None,
        error_code="CODEX_USAGE_SLOT_BUSY" if state == "FAILED" else None,
        processed_at="2026-10-11T00:01:00Z" if state in {"SUCCEEDED", "FAILED"} else None,
    )
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(expected)))
    assert value.read_codex_control_command(COMMAND, binding_id=BINDING) == expected
    assert len(transport.requests) == 1 and transport.requests[0][0] == "GET"


@pytest.mark.parametrize("reply", [listing(account(), account()), listing(account(binding_id="x"))])
def test_listing_rejects_duplicate_or_nonbinding_identity(
    monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    connection(monkeypatch, canonical_json_bytes(reply))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_accounts()
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"


def test_account_reply_cannot_substitute_another_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = session(monkeypatch)
    connection(
        monkeypatch, canonical_json_bytes(wrapper(account(binding_id="authbinding_" + "c" * 32)))
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_account(BINDING)
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"


@pytest.mark.parametrize("operation", ["ACCOUNT", "COMMAND"])
@pytest.mark.parametrize("identity", ["invalid", BINDING + "?latest=true", "a/../b"])
def test_invalid_read_identity_is_rejected_before_auth_or_http(
    monkeypatch: pytest.MonkeyPatch, operation: str, identity: str
) -> None:
    value, calls = session(monkeypatch)
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError) as caught:
        if operation == "ACCOUNT":
            value.read_codex_account(identity)
        else:
            value.read_codex_control_command(identity, binding_id=BINDING)
    assert caught.value.code == "CONTROL_ACCOUNT_REQUEST_INVALID"
    assert transport.events == [] and calls == ["ME"]


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_version": True},
        {"resource_version": 0},
        {"observed_at": "2026-10-11T09:00:00+09:00"},
        {"capabilities": [{"model": "synthetic"}]},
        {"untrusted_extra": TOKEN},
    ],
)
def test_malformed_account_reply_is_sanitized_without_native_admission(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, _ = session(monkeypatch)
    reply = wrapper(account().model_dump(mode="json") | changes)
    transport = connection(monkeypatch, canonical_json_bytes(reply))
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_account(BINDING)
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert len(transport.requests) == 1
    assert TOKEN not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_official_read_denial_or_failure_has_no_retry(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=status)
    with pytest.raises(ControlPlaneError) as caught:
        value.read_codex_account(BINDING)
    assert caught.value.code == (
        "CONTROL_AUTHORIZATION_REQUIRED"
        if status in {401, 403}
        else "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    )
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("method", "path", "version"),
    [
        ("POST", "/api/v1/codex-accounts/" + BINDING + "/commands?latest=true", VERSION),
        ("POST", "/api/v1/codex-accounts/" + BINDING + "/reauthentications", VERSION),
        ("GET", "/api/v1/codex-control-commands/" + COMMAND + "/result", None),
        ("GET", "/api/v1/codex-accounts/" + BINDING, VERSION),
        ("POST", http._COMPARISONS, VERSION),
        ("POST", "/api/v1/codex-accounts/" + BINDING + "/commands", True),
    ],
)
def test_transport_keeps_fixed_routes_and_observe_only_if_match(
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
            canonical_json_bytes(OBSERVE.model_dump(mode="json")) if method == "POST" else None,
            bearer=SecretStr(TOKEN),
            idempotency_key=KEY if method == "POST" else None,
            expected_resource_version=version,
        )
    assert transport.events == []


def test_transport_rejects_nonobserve_body_before_any_send(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = connection(monkeypatch, b"{}")
    with pytest.raises(ControlPlaneError):
        http._request(
            "POST",
            "/api/v1/codex-accounts/" + BINDING + "/commands",
            b'{"command_type":"DISABLE","reason_code":"MAINTENANCE"}',
            bearer=SecretStr(TOKEN),
            idempotency_key=KEY,
            expected_resource_version=VERSION,
        )
    assert transport.requests == []
    assert transport.events == ["FACTORY", "CONNECT", "PEER", "CLOSE"]


def test_observe_wrong_peer_does_not_send_secrets_or_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, b"{}", status=202)
    monkeypatch.setattr(
        http,
        "require_fixed_api_peer_socket",
        lambda _sock: (_ for _ in ()).throw(ValueError(TOKEN)),
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(
            BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"
    assert transport.requests == [] and TOKEN not in str(caught.value)


@pytest.mark.parametrize("payload", [b'{"data":{},"data":{}}', b'{"data":NaN}', b"", b"[", b"\xff"])
def test_observation_untrusted_json_failure_does_not_retry(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    value, _ = session(monkeypatch)
    transport = connection(monkeypatch, payload, status=202)
    with pytest.raises(ControlPlaneError) as caught:
        value.observe_codex_account(
            BINDING, OBSERVE, expected_resource_version=VERSION, idempotency_key=KEY
        )
    assert caught.value.code == "CONTROL_ACCOUNT_OBSERVATION_UNCERTAIN"
    assert len(transport.requests) == 1


def test_new_account_read_uses_existing_same_session_refresh_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=30)
    monkeypatch.setattr(
        http,
        "FixedApiControlPrincipalReader",
        lambda token: SimpleNamespace(
            read=lambda: principal(
                effective_permissions=PERMISSIONS,
                access_expires_at=expires_at
                if token.get_secret_value() == NEXT_TOKEN
                else datetime.now(UTC) + timedelta(seconds=30),
            )
        ),
    )
    value = http.AuthenticatedInferenceTransferHttpSession(
        SecretStr(TOKEN), refresh=SecretStr(REFRESH_TOKEN)
    )
    assert value.read().operator_id == ACTOR
    events: list[str] = []

    def refresh(path: str, body: Any) -> tuple[int, object]:
        assert path == http._REFRESH
        assert body() == canonical_json_bytes({"refresh_token": REFRESH_TOKEN})
        events.append("REFRESH")
        return 200, wrapper(
            {
                "access_token": NEXT_TOKEN,
                "refresh_token": NEXT_REFRESH,
                "token_type": "bearer",
                "access_expires_at": expires_at.isoformat(),
                "refresh_expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "session_id": SESSION,
                "password_change_required": False,
            }
        )

    monkeypatch.setattr(http, "_post", refresh)
    transport = connection(monkeypatch, canonical_json_bytes(wrapper(account())))
    assert value.read_codex_account(BINDING) == account()
    assert events == ["REFRESH"]
    assert transport.requests[0][3]["Authorization"] == "Bearer " + NEXT_TOKEN
    assert value._authenticated_at == AUTHENTICATED_AT
