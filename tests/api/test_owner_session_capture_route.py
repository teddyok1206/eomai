"""Source route with genuine synthetic HMAC path; no installed API/key/provider or SQL."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_api.openapi import install_route_metadata
from eom_api.problem_details import install_exception_handlers
from eom_api.routers.owner_session_capture import router
from eom_identity_service import AuthenticatedOperatorSession
from eom_operator_identity.owner_session_capture import (
    owner_session_capture_bytes,
    parse_owner_session_capture_response,
    validate_owner_session_capture_response,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.test_auth_unit import source_auth
from tests.api.test_token_unit import TokenMutationSession
from tests.unit.test_authenticated_session_fence import verified_capture
from tests.unit.test_owner_session_capture_contracts import request


def api(
    monkeypatch: pytest.MonkeyPatch, fault: str = ""
) -> tuple[TestClient, TokenMutationSession, list[str], list[str]]:
    source = TokenMutationSession()
    verified_capture(monkeypatch, source)
    service, roots = source_auth(monkeypatch, source)
    calls: list[str] = []
    real_capture = service.capture_access

    def capture(token: str) -> AuthenticatedOperatorSession:
        calls.append("capture")
        if fault == "unexpected":
            raise RuntimeError(token + " private-verifier-digest")
        return real_capture(token)

    monkeypatch.setattr(service, "capture_access", capture)
    if fault == "revoked":
        source.token.revoked_at = source.token.issued_at
    app = FastAPI()
    app.state.services = SimpleNamespace(
        auth=service,
        settings=SimpleNamespace(rate_limit=SimpleNamespace(general_per_minute=30)),
        rate_limiter=SimpleNamespace(
            check=lambda *_args, **_kwargs: SimpleNamespace(allowed=fault != "rate")
        ),
    )
    app.include_router(router, prefix="/api/v1")
    install_route_metadata(app)
    install_exception_handlers(app)
    return TestClient(app), source, calls, roots


def test_exact_one_official_capture_canonical_reply_no_store_closed_auth_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, source, calls, roots = api(monkeypatch)
    with client:
        response = client.post(
            "/api/v1/auth/owner-session-capture",
            content=owner_session_capture_bytes(request()),
            headers={
                "Authorization": "Bearer " + source.raw_token,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200
    reply = parse_owner_session_capture_response(response.content)
    validate_owner_session_capture_response(request(), reply)
    assert calls == ["capture"] and roots == ["begin", "end"]
    assert (
        reply.operator_id == source.operator.operator_id
        and reply.verifier_digest == source.token.verifier_hash
    )
    assert response.headers["cache-control"] == "no-store"
    assert source.raw_token not in response.text
    assert isinstance(client.app, FastAPI)
    schema = client.app.openapi()
    operation = schema["paths"]["/api/v1/auth/owner-session-capture"]["post"]
    assert operation["x-eom-auth-control"] is True
    assert "x-eom-permission" not in operation


@pytest.mark.parametrize("fault,status", [("revoked", 401), ("unexpected", 503), ("rate", 429)])
def test_auth_errors_are_content_free_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, fault: str, status: int
) -> None:
    client, source, calls, _roots = api(monkeypatch, fault)
    with client:
        result = client.post(
            "/api/v1/auth/owner-session-capture",
            content=owner_session_capture_bytes(request()),
            headers={
                "Authorization": "Bearer " + source.raw_token,
                "Content-Type": "application/json",
            },
        )
    assert result.status_code == status and calls == ["capture"]
    for secret in (source.raw_token, source.token.verifier_hash, "private-verifier-digest"):
        assert secret not in result.text


@pytest.mark.parametrize(
    "raw",
    [
        b" " + owner_session_capture_bytes(request()),
        b'{"nonce":NaN}',
        b'{"nonce":"x","nonce":"y"}',
        b"{" * 1000 + b"}" * 1000,
        b"x" * 4097,
    ],
)
def test_bounded_invalid_raw_request_never_authenticates_or_echoes(
    monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    client, source, calls, _roots = api(monkeypatch)
    with client:
        result = client.post(
            "/api/v1/auth/owner-session-capture",
            content=raw,
            headers={
                "Authorization": "Bearer " + source.raw_token,
                "Content-Type": "application/json",
            },
        )
    assert result.status_code == 422 and not calls
    assert source.raw_token not in result.text


def test_missing_bearer_and_transfer_encoding_never_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, source, calls, _roots = api(monkeypatch)
    with client:
        missing = client.post(
            "/api/v1/auth/owner-session-capture",
            content=owner_session_capture_bytes(request()),
            headers={"Content-Type": "application/json"},
        )
        chunked = client.post(
            "/api/v1/auth/owner-session-capture",
            content=owner_session_capture_bytes(request()),
            headers={
                "Authorization": "Bearer " + source.raw_token,
                "Content-Type": "application/json",
                "Transfer-Encoding": "chunked",
            },
        )
    assert missing.status_code == 401 and chunked.status_code == 422 and not calls


def test_route_never_calls_authentication_twice_or_native_source_paths() -> None:
    import ast
    from pathlib import Path

    from eom_api.routers import owner_session_capture as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    assert attributes.count("capture_access") == 1
    assert not set(attributes) & {
        "authenticate_access",
        "refresh",
        "start_local_embedding_in_session",
        "execute",
        "register_embedding_index",
    }
