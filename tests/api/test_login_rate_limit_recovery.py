"""Login pacing must not override the authoritative credential/recovery state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.rate_limit import BoundedRateLimiter
from eom_api.request_context import RequestContext
from eom_api.routers.auth import login
from eom_api_contracts.auth import LoginRequest
from eom_identity_service.auth_service import AuthenticationFailure
from fastapi import FastAPI, Request


def request_case(*, global_limit: int = 100, username_limit: int = 2):
    now = datetime.now(UTC)
    pair = SimpleNamespace(
        access_token="eom_at_TEST_ONLY",
        refresh_token="eom_rt_TEST_ONLY",
        access_expires_at=now + timedelta(minutes=30),
        refresh_expires_at=now + timedelta(days=1),
        session_id="apisession_" + "a" * 32,
        password_change_required=True,
    )

    def authenticate(*, username, password, client_name):
        if password != "TEST_ONLY correct":
            raise AuthenticationFailure("PASSWORD_MISMATCH")
        return SimpleNamespace(pair=pair)

    services = SimpleNamespace(
        settings=SimpleNamespace(
            rate_limit=SimpleNamespace(
                login_global_per_minute=global_limit,
                login_username_per_window=username_limit,
            ),
            auth=SimpleNamespace(login_failure_window_seconds=900),
        ),
        fingerprint_key=b"TEST_ONLY_FINGERPRINT_KEY_012345678901",
        rate_limiter=BoundedRateLimiter(),
        auth=SimpleNamespace(login=Mock(side_effect=authenticate), authenticate_access=Mock()),
        audit=SimpleNamespace(append=Mock()),
    )
    app = FastAPI()
    app.state.services = services
    request = Request({"type": "http", "app": app, "method": "POST", "path": "/auth/login"})
    request.state.request_context = RequestContext(
        request_id="req_" + "a" * 32,
        started_at=now,
        route_template="/auth/login",
        method="POST",
        client_name=None,
        source_address_hash=None,
        user_agent_hash=None,
    )
    return request, services


def payload(password="TEST_ONLY correct", username="reviewer"):
    return LoginRequest(username=username, password=password, client_name="TEST_ONLY")


def test_repeated_successful_logins_never_fill_the_username_failure_window() -> None:
    request, services = request_case()
    for _ in range(8):
        assert login(request, payload()).data.password_change_required is True
    assert services.auth.login.call_count == 8
    assert services.rate_limiter.bucket_count == 1  # Global burst remains enforced.


def test_recovered_correct_password_can_login_after_username_failure_budget_is_full() -> None:
    request, services = request_case()
    for _ in range(2):
        with pytest.raises(AuthenticationFailure):
            login(request, payload("TEST_ONLY wrong"))
    with pytest.raises(ApiError) as failure:
        login(request, payload("TEST_ONLY wrong"))
    assert failure.value.error_code == "API_RATE_LIMITED"
    assert login(request, payload()).data.password_change_required is True
    assert services.auth.login.call_count == 4
    with pytest.raises(AuthenticationFailure):
        login(request, payload("TEST_ONLY wrong"))


def test_success_does_not_clear_another_username_failure_budget() -> None:
    request, _ = request_case(username_limit=1)
    with pytest.raises(AuthenticationFailure):
        login(request, payload("TEST_ONLY wrong", username="otheruser"))
    login(request, payload())
    with pytest.raises(ApiError) as failure:
        login(request, payload("TEST_ONLY wrong", username="otheruser"))
    assert failure.value.error_code == "API_RATE_LIMITED"


def test_global_burst_limit_still_precedes_password_verification() -> None:
    request, services = request_case(global_limit=1)
    login(request, payload())
    with pytest.raises(ApiError) as failure:
        login(request, payload())
    assert failure.value.error_code == "API_RATE_LIMITED"
    assert services.auth.login.call_count == 1


def test_authoritative_account_lock_is_never_bypassed() -> None:
    request, services = request_case()
    services.auth.login.side_effect = AuthenticationFailure("ACCOUNT_LOCKED")
    with pytest.raises(AuthenticationFailure):
        login(request, payload())
    assert services.audit.append.call_args.kwargs["event_type"] == "ACCOUNT_LOCKED"
