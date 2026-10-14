"""Real source HMAC with synthetic DB rows; no installed peer/native/production acceptance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.dependencies import Auth, get_request_context, require_permission
from eom_api.openapi import install_route_metadata
from eom_api.problem_details import install_exception_handlers
from eom_api.request_context import RequestContext
from eom_identity_service import tokens as token_module
from eom_identity_service.tokens import AuthenticatedAccess
from eom_operator_identity import PermissionKey
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from tests.api.test_auth_unit import source_auth
from tests.api.test_token_unit import TokenMutationSession
from tests.unit.test_authenticated_session_fence import assert_current, verified_capture


def request_context() -> RequestContext:
    return RequestContext(
        request_id="webreq_" + "a" * 24,
        started_at=datetime.now(UTC),
        route_template="/synthetic-owner",
        method="POST",
        client_name=None,
        source_address_hash=None,
        user_agent_hash=None,
    )


def application(monkeypatch, *, operation="workflow_start", fault=""):
    source = TokenMutationSession()
    verified_capture(monkeypatch, source)
    service, roots = source_auth(monkeypatch, source)
    calls = []
    observed = []
    real_auth = service.authenticate_access
    real_capture = service.authenticate_and_capture_access
    hmac = Mock(wraps=source.codec.matches)
    monkeypatch.setattr(source.codec, "matches", hmac)

    def authenticate(token):
        calls.append("authenticate")
        return real_auth(token)

    def capture(token):
        calls.append("authenticate_and_capture")
        result = real_capture(token)
        observed.append(result)
        return result

    monkeypatch.setattr(service, "authenticate_access", authenticate)
    monkeypatch.setattr(service, "authenticate_and_capture_access", capture)
    if fault == "revoked":
        source.token.revoked_at = source.token.issued_at
    elif fault == "expired":
        source.token.expires_at = datetime.now(UTC)
    elif fault == "permission":
        source.permissions = frozenset()
    elif fault == "password":
        projector = token_module.operator_projection
        monkeypatch.setattr(
            token_module,
            "operator_projection",
            lambda *args: projector(*args).model_copy(update={"must_change_password": True}),
        )
    app = FastAPI()
    app.state.services = SimpleNamespace(
        auth=service,
        audit=SimpleNamespace(append=Mock()),
        settings=SimpleNamespace(
            rate_limit=SimpleNamespace(general_per_minute=30),
            auth=SimpleNamespace(fresh_auth_seconds=300),
        ),
        rate_limiter=SimpleNamespace(
            check=lambda *_args, **_kwargs: SimpleNamespace(allowed=fault != "rate", retry_after=1)
        ),
    )

    @app.middleware("http")
    async def context(request: Request, call_next):
        request.state.request_context = request_context()
        return await call_next(request)

    @app.post(
        "/synthetic-owner",
        operation_id=operation,
        dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    )
    def endpoint(request: Request, authentication: Auth):
        current = get_request_context(request)
        assert current.authentication is authentication
        if operation == "workflow_start":
            owner = current.owner_capture()
            assert_current(source, owner)
            assert observed[-1].capture is owner
        else:
            assert current.authenticated_access is None
            with pytest.raises(RuntimeError, match="OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE"):
                current.owner_capture()
        calls.append("endpoint")
        return {"operator": authentication.operator.operator_id}

    install_route_metadata(app)
    install_exception_handlers(app)
    return SimpleNamespace(
        client=TestClient(app),
        source=source,
        service=service,
        roots=roots,
        calls=calls,
        observed=observed,
        hmac=hmac,
    )


@pytest.mark.parametrize("operation", ("workflow_start", "workflow_get"))
def test_permission_and_endpoint_share_one_hmac_without_reauthentication_or_id_mint(
    monkeypatch, operation
):
    case = application(monkeypatch, operation=operation)
    with case.client:
        result = case.client.post(
            "/synthetic-owner", headers={"Authorization": "Bearer " + case.source.raw_token}
        )
    assert result.status_code == 200
    assert case.calls == [
        "authenticate_and_capture" if operation == "workflow_start" else "authenticate",
        "endpoint",
    ]
    assert case.roots == ["begin", "end"]
    case.hmac.assert_called_once()
    assert case.source.raw_token not in result.text
    assert case.source.token.verifier_hash not in result.text
    if case.observed:
        observed = case.observed[0]
        assert observed.authentication.session_id == case.source.api_session.api_session_id
        assert observed.authentication.access_expires_at == case.source.token.expires_at
        with pytest.raises(FrozenInstanceError):
            observed.capture = None


@pytest.mark.parametrize(
    "fault,status",
    (("revoked", 401), ("expired", 401), ("password", 403), ("permission", 403), ("rate", 429)),
)
def test_existing_auth_password_permission_and_rate_guards_still_stop_owner_work(
    monkeypatch, fault, status
):
    case = application(monkeypatch, fault=fault)
    with case.client:
        result = case.client.post(
            "/synthetic-owner", headers={"Authorization": "Bearer " + case.source.raw_token}
        )
    assert result.status_code == status and case.calls == ["authenticate_and_capture"]
    assert case.roots == ["begin", "end"]
    case.hmac.assert_called_once()
    assert case.source.raw_token not in result.text
    assert case.source.token.verifier_hash not in result.text
    if fault in {"revoked", "expired", "password"}:
        assert case.observed == []


def test_body_ids_cannot_replace_missing_or_changed_request_identity(monkeypatch):
    case = application(monkeypatch)
    value = case.service.authenticate_and_capture_access(case.source.raw_token)
    context = request_context()
    context.authentication = value.authentication
    with pytest.raises(RuntimeError, match="OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE"):
        context.owner_capture()
    context.authenticated_access = value
    assert context.owner_capture() is value.capture
    assert "authenticated_access" not in repr(context)
    assert case.source.token.verifier_hash not in repr(context)
    assert case.source.raw_token not in repr(value)
    # An equal presentation DTO is not the actual pair observed by this request.
    context.authentication = replace(value.authentication)
    with pytest.raises(RuntimeError, match="OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE"):
        context.owner_capture()
    context.authentication = value.authentication
    context.authenticated_access = AuthenticatedAccess(value.authentication, SimpleNamespace())
    with pytest.raises(RuntimeError, match="OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE"):
        context.owner_capture()
    changed = replace(
        value.authentication,
        operator=value.authentication.operator.model_copy(
            update={"operator_id": "operator_" + "f" * 32}
        ),
    )
    context.authentication = changed
    context.authenticated_access = AuthenticatedAccess(changed, value.capture)
    with pytest.raises(RuntimeError, match="OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE"):
        context.owner_capture()


def test_followup_requests_authenticate_again_without_caching_or_extending_token_lifetime(
    monkeypatch,
):
    case = application(monkeypatch)
    expires = case.source.token.expires_at
    with case.client:
        for _ in range(2):
            result = case.client.post(
                "/synthetic-owner", headers={"Authorization": "Bearer " + case.source.raw_token}
            )
            assert result.status_code == 200
    assert case.calls == ["authenticate_and_capture", "endpoint"] * 2
    assert case.roots == ["begin", "end"] * 2
    assert case.hmac.call_count == 2
    first, second = case.observed
    assert first is not second and first.capture is not second.capture
    assert first.authentication.session_id == second.authentication.session_id
    assert (
        first.authentication.access_expires_at
        == second.authentication.access_expires_at
        == case.source.token.expires_at
        == expires
    )
