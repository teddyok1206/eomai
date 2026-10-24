"""Fake official HTTP/session tests; no credentials, production reads or networking."""

from __future__ import annotations

import http.client as http_client
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api_contracts.auth import CurrentOperator, TokenPair
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import snapshot_phase_deadlines
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_owner_http as http
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure
from pydantic import SecretStr

from tests.unit.inference_transfer_metadata_fixtures import metadata_request, metadata_result
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
)

ACTOR = "operator_" + "a" * 32
SESSION = "apisession_" + "b" * 32
TOKEN = "eom_at_" + "x" * 64
AUTHENTICATED_AT = datetime.now(UTC) - timedelta(minutes=1)
REFRESH_TOKEN = "eom_rt_" + "r" * 22 + "." + "r" * 43
NEXT_TOKEN = "eom_at_" + "n" * 22 + "." + "n" * 43
NEXT_REFRESH = "eom_rt_" + "s" * 22 + "." + "s" * 43


def principal(**changes: Any) -> CurrentOperator:
    now = datetime.now(UTC)
    return CurrentOperator.model_validate(
        {
            "operator_id": ACTOR,
            "username": "guiadmin",
            "display_name": "합성 사용자",
            "roles": ["ADMIN"],
            "effective_permissions": ["item:read"],
            "session_id": SESSION,
            "authenticated_at": AUTHENTICATED_AT,
            "access_expires_at": now + timedelta(minutes=30),
            "password_change_required": False,
        }
        | changes
    )


def wrapper(value: Any) -> dict[str, Any]:
    return {
        "data": value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
        "meta": {"request_id": "synthetic-request", "api_version": "1"},
    }


def session(monkeypatch: pytest.MonkeyPatch) -> http.AuthenticatedInferenceTransferHttpSession:
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=principal)
    )
    return http.AuthenticatedInferenceTransferHttpSession.from_bearer(SecretStr(TOKEN))


class Response:
    def __init__(self, payload: bytes, status: int = 200, media: str = "application/json"):
        self.payload, self.status, self.media = payload, status, media

    def getheader(self, _name: str, _default: str = "") -> str:
        return self.media

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class Connection:
    def __init__(self, response: Response, events: list[str]):
        self.sock = object()
        self.response, self.events = response, events
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []

    def connect(self) -> None:
        self.events.append("CONNECT")

    def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        self.events.append("SEND")
        self.requests.append((method, path, body, headers))

    def getresponse(self) -> Response:
        return self.response

    def close(self) -> None:
        self.events.append("CLOSE")


def connection(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    status: int = 200,
    media: str = "application/json",
    expected_timeout: float = 120.0,
) -> Connection:
    events: list[str] = []
    value = Connection(Response(payload, status, media), events)

    def factory(host: str, port: int, *, timeout: float) -> Connection:
        assert (host, port, timeout) == ("127.0.0.1", 8765, expected_timeout)
        events.append("FACTORY")
        return value

    monkeypatch.setattr(http_client, "HTTPConnection", factory)
    monkeypatch.setattr(http, "require_fixed_api_peer_socket", lambda _sock: events.append("PEER"))
    return value


def test_connected_peer_is_verified_before_any_secret_body_or_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = connection(monkeypatch, b"{}")

    def body() -> bytes:
        value.events.append("SECRET_BODY")
        return b'{"password":"synthetic-only"}'

    assert http._post(http._LOGIN, body, bearer=SecretStr(TOKEN)) == (200, {})
    assert value.events == ["FACTORY", "CONNECT", "PEER", "SECRET_BODY", "SEND", "CLOSE"]
    assert value.requests[0][3]["Authorization"] == "Bearer " + TOKEN


def test_wrong_peer_does_not_materialize_secret_or_send_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = connection(monkeypatch, b"{}")
    monkeypatch.setattr(
        http,
        "require_fixed_api_peer_socket",
        lambda _sock: (_ for _ in ()).throw(ValueError("bad")),
    )
    with pytest.raises(ControlPlaneError) as caught:
        http._post(http._LOGIN, lambda: pytest.fail("secret materialized"), bearer=SecretStr(TOKEN))
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert value.requests == [] and value.events == ["FACTORY", "CONNECT", "CLOSE"]
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("payload", [b"", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"["])
def test_untrusted_json_failure_is_sanitized_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    value = connection(monkeypatch, payload)
    with pytest.raises(ControlPlaneError):
        http._post(http._LOGIN, b"{}")
    assert len(value.requests) == 1 and value.events.count("FACTORY") == 1


def test_only_fixed_paths_and_actual_envelope_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ControlPlaneError):
        http._post("http://attacker.example/", b"{}")
    value = connection(monkeypatch, b"x" * 65)
    monkeypatch.setattr(http, "_MAX_ENVELOPE_BYTES", 64)
    with pytest.raises(ControlPlaneError):
        http._post(http._LOGIN, b"{}")
    assert len(value.requests) == 1
    value = connection(monkeypatch, b"{}", media="text/html")
    with pytest.raises(ControlPlaneError):
        http._post(http._LOGIN, b"{}")
    assert len(value.requests) == 1


def test_actual_login_password_is_not_masked_and_tokens_are_secretstr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    reply = wrapper(
        {
            "access_token": TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "bearer",
            "access_expires_at": (now + timedelta(minutes=30)).isoformat(),
            "refresh_expires_at": (now + timedelta(days=1)).isoformat(),
            "session_id": SESSION,
            "password_change_required": False,
        }
    )
    value = connection(monkeypatch, canonical_json_bytes(reply))
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=principal)
    )
    actual = http.AuthenticatedInferenceTransferHttpSession.login_guiadmin(
        SecretStr("synthetic-only")
    )
    wire = json.loads(value.requests[0][2])
    assert wire["username"] == "guiadmin" and wire["password"] == "synthetic-only"
    assert isinstance(actual._bearer, SecretStr) and isinstance(actual._refresh, SecretStr)
    assert TOKEN not in repr(actual._bearer)
    assert "Authorization" not in value.requests[0][3]


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_login_denials_redirects_and_server_failure_have_no_refresh_or_retry(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    value = connection(monkeypatch, b"{}", status=status)
    with pytest.raises(ControlPlaneError):
        http.AuthenticatedInferenceTransferHttpSession.login_guiadmin(SecretStr("synthetic-only"))
    assert len(value.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "other-admin"},
        {"operator_id": "operator_foreign"},
        {"session_id": "apisession_foreign"},
        {"password_change_required": True},
        {"access_expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"authenticated_at": datetime(2100, 1, 1, tzinfo=UTC)},
    ],
)
def test_current_guiadmin_identity_and_expiry_are_not_caller_claims(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    value = session(monkeypatch)
    monkeypatch.setattr(value, "_reader", SimpleNamespace(read=lambda: principal(**changes)))
    with pytest.raises(ControlPlaneError) as caught:
        value.read()
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"


@pytest.mark.parametrize(
    "field,pin",
    [
        ("operator_id", "operator_" + "c" * 32),
        ("session_id", "apisession_" + "c" * 32),
    ],
)
def test_pinned_actual_session_cannot_switch_principal(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    pin: str,
) -> None:
    value = session(monkeypatch)
    monkeypatch.setattr(value, "_reader", SimpleNamespace(read=lambda: principal(**{field: pin})))
    with pytest.raises(ControlPlaneError):
        value.read()


def test_each_snapshot_phase_revalidates_actual_principal_and_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    reads: list[str] = []

    def current() -> CurrentOperator:
        reads.append("ME")
        return principal()

    monkeypatch.setattr(value, "_reader", SimpleNamespace(read=current))
    records = snapshot_records()
    prepared = snapshot_prepare_result(header=snapshot_header(actor_id=ACTOR))
    read_request = snapshot_read_request(prepared)
    read_reply = snapshot_read_result(records, request=read_request)
    authorize = hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=prepared.header,
        staged_entry_set_sha256=content_sha256("entries"),
        staged_baseline_set_sha256=content_sha256("baselines"),
    )
    authorized = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        header_sha256=prepared.header.header_sha256,
        authorization_sha256=authorize.authorization_sha256,
        source_count=3,
        profile_count=3,
        missing_report_count=0,
        staged_entry_set_sha256=authorize.staged_entry_set_sha256,
        staged_baseline_set_sha256=authorize.staged_baseline_set_sha256,
    )
    for request, reply in (
        (snapshot_prepare(), prepared),
        (read_request, read_reply),
        (authorize, authorized),
    ):
        wire = connection(
            monkeypatch,
            canonical_json_bytes(wrapper(reply)),
            expected_timeout=snapshot_phase_deadlines(request.phase).owner_http_seconds,
        )
        assert value.execute(ACTOR, request) == reply
        assert wire.requests[0][1] == http._SNAPSHOT
    assert reads == ["ME", "ME", "ME"]


def test_actor_mismatch_is_rejected_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    value = session(monkeypatch)
    monkeypatch.setattr(http, "_post", lambda *_args, **_kw: pytest.fail("HTTP called"))
    with pytest.raises(SnapshotReadFailure) as caught:
        value.execute("operator_" + "c" * 32, snapshot_prepare())
    assert caught.value.code == "INFERENCE_TRANSFER_FORBIDDEN"
    foreign = snapshot_prepare_result(header=snapshot_header(actor_id="operator_" + "c" * 32))
    with pytest.raises(SnapshotReadFailure):
        value.execute(ACTOR, snapshot_read_request(foreign))


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "UNKNOWN", "INFERENCE_TRANSFER_FORBIDDEN"),
        (403, "UNKNOWN", "INFERENCE_TRANSFER_FORBIDDEN"),
        (409, "INFERENCE_TRANSFER_SNAPSHOT_CHANGED", "INFERENCE_TRANSFER_SNAPSHOT_CHANGED"),
        (500, "eom_at_secret", "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"),
    ],
)
def test_official_error_codes_are_closed_and_no_replay(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    expected: str,
) -> None:
    value = session(monkeypatch)
    wire = connection(monkeypatch, canonical_json_bytes({"error_code": code}), status=status)
    with pytest.raises(SnapshotReadFailure) as caught:
        value.execute(ACTOR, snapshot_prepare())
    assert caught.value.code == expected and len(wire.requests) == 1


def test_valid_hashed_foreign_actor_reply_is_not_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    value = session(monkeypatch)
    foreign = snapshot_prepare_result(header=snapshot_header(actor_id="operator_" + "c" * 32))
    connection(monkeypatch, canonical_json_bytes(wrapper(foreign)))
    with pytest.raises(SnapshotReadFailure) as caught:
        value.execute(ACTOR, snapshot_prepare())
    assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"


def test_current_auth_service_failure_is_not_reclassified_as_session_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)

    def unavailable() -> Any:
        raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "synthetic secret")

    monkeypatch.setattr(value, "_reader", SimpleNamespace(read=unavailable))
    with pytest.raises(ControlPlaneError) as caught:
        value.read()
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert "secret" not in str(caught.value) and caught.value.__cause__ is None


def test_exact_metadata_http_uses_current_session_and_pinned_official_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    request, result = metadata_request(), metadata_result()
    wire = connection(monkeypatch, canonical_json_bytes(wrapper(result)))
    assert value.resolve_metadata(request) == result
    assert wire.requests[0][1] == http._METADATA
    assert json.loads(wire.requests[0][2]) == request.model_dump(mode="json")
    assert "actor_id" not in json.loads(wire.requests[0][2])
    assert wire.requests[0][3]["Authorization"] == "Bearer " + TOKEN


def test_metadata_semantic_hash_is_not_manifest_hash_or_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = session(monkeypatch)
    request = metadata_request()
    result = metadata_result(snapshot_sha256="sha256:" + "e" * 64)
    connection(monkeypatch, canonical_json_bytes(wrapper(result)))
    with pytest.raises(ControlPlaneError) as caught:
        value.resolve_metadata(request)
    assert caught.value.code == "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "UNKNOWN", "INFERENCE_TRANSFER_FORBIDDEN"),
        (
            409,
            "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH",
            "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH",
        ),
        (500, "eom_at_secret", "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"),
    ],
)
def test_metadata_error_closed_allowlist_no_retry_or_secret_echo(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    expected: str,
) -> None:
    value = session(monkeypatch)
    wire = connection(monkeypatch, canonical_json_bytes({"error_code": code}), status=status)
    with pytest.raises(ControlPlaneError) as caught:
        value.resolve_metadata(metadata_request())
    assert caught.value.code == expected and len(wire.requests) == 1
    assert "secret" not in str(caught.value)


def refresh_session(
    monkeypatch: pytest.MonkeyPatch, *, remaining_seconds: int = 179
) -> tuple[http.AuthenticatedInferenceTransferHttpSession, dict[str, datetime]]:
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(http, "datetime", SimpleNamespace(now=lambda _tz: clock["now"]))
    initial = principal(access_expires_at=clock["now"] + timedelta(seconds=remaining_seconds))
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=lambda: initial)
    )
    value = http.AuthenticatedInferenceTransferHttpSession(
        SecretStr(TOKEN), refresh=SecretStr(REFRESH_TOKEN)
    )
    assert value.read() == initial
    return value, clock


def refresh_reply(now: datetime, **changes: Any) -> dict[str, Any]:
    return wrapper(
        {
            "access_token": NEXT_TOKEN,
            "refresh_token": NEXT_REFRESH,
            "token_type": "bearer",
            "access_expires_at": (now + timedelta(minutes=30)).isoformat(),
            "refresh_expires_at": (now + timedelta(days=1)).isoformat(),
            "session_id": SESSION,
            "password_change_required": False,
        }
        | changes
    )


@pytest.mark.parametrize("expired", [False, True])
def test_public_rotation_retains_real_identity_and_current_permissions_in_memory(
    monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    now = datetime.now(UTC)
    current = principal(access_expires_at=now + timedelta(seconds=-1 if expired else 30))
    renewed = principal(
        access_expires_at=now + timedelta(minutes=30),
        roles=["USER"],
        effective_permissions=["knowledge:analysis:read"],
    )
    events: list[str] = []

    def refresh(path: str, body: Any, **kwargs: Any) -> tuple[int, object]:
        assert path == http._REFRESH and kwargs == {}
        assert json.loads(body()) == {"refresh_token": REFRESH_TOKEN}
        events.append("REFRESH")
        return 200, refresh_reply(now)

    def reader(bearer: SecretStr) -> Any:
        assert bearer.get_secret_value() == NEXT_TOKEN

        def read() -> CurrentOperator:
            events.append("NEW_ME")
            return renewed

        return SimpleNamespace(read=read)

    monkeypatch.setattr(http, "_post", refresh)
    monkeypatch.setattr(http, "FixedApiControlPrincipalReader", reader)
    tokens, actor = http.rotate_genuine_operator_session(
        current, SecretStr(TOKEN), SecretStr(REFRESH_TOKEN), minimum_access_seconds=1200
    )
    assert isinstance(tokens, TokenPair) and actor == renewed
    assert actor.authenticated_at == current.authenticated_at == AUTHENTICATED_AT
    assert actor.session_id == current.session_id and actor.operator_id == current.operator_id
    assert actor.roles == ("USER",) and actor.effective_permissions == ("knowledge:analysis:read",)
    assert current.roles == ("ADMIN",) and current.effective_permissions == ("item:read",)
    assert events == ["REFRESH", "NEW_ME"]
    assert tokens.access_token == NEXT_TOKEN and tokens.refresh_token == NEXT_REFRESH


@pytest.mark.parametrize("seconds", [True, False, 0, -1, 3601, 180.0, "180", None])
def test_public_rotation_rejects_invalid_access_windows_before_http(
    monkeypatch: pytest.MonkeyPatch, seconds: Any
) -> None:
    monkeypatch.setattr(http, "_post", lambda *_a, **_kw: pytest.fail("invalid refresh sent"))
    with pytest.raises(ControlPlaneError) as caught:
        http.rotate_genuine_operator_session(
            principal(), SecretStr(TOKEN), SecretStr(REFRESH_TOKEN), minimum_access_seconds=seconds
        )
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert TOKEN not in str(caught.value) and REFRESH_TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_id": "invalid"},
        {"session_id": "invalid"},
        {"authenticated_at": datetime(2100, 1, 1, tzinfo=UTC)},
        {"password_change_required": True},
        {"private_extra": REFRESH_TOKEN},
    ],
)
def test_public_rotation_revalidates_current_before_refresh(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    monkeypatch.setattr(http, "_post", lambda *_a, **_kw: pytest.fail("invalid refresh sent"))
    with pytest.raises(ControlPlaneError) as caught:
        http.rotate_genuine_operator_session(
            principal().model_copy(update=changes), SecretStr(TOKEN), SecretStr(REFRESH_TOKEN)
        )
    assert REFRESH_TOKEN not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize("remaining", [1200, 1201])
def test_public_rotation_requires_strict_requested_access_window(
    monkeypatch: pytest.MonkeyPatch, remaining: int
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(http, "datetime", SimpleNamespace(now=lambda _tz: now))
    expiry = now + timedelta(seconds=remaining)
    monkeypatch.setattr(
        http,
        "_post",
        lambda *_a, **_kw: (200, refresh_reply(now, access_expires_at=expiry.isoformat())),
    )
    renewed = principal(access_expires_at=expiry)
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_a: SimpleNamespace(read=lambda: renewed)
    )
    if remaining == 1200:
        with pytest.raises(ControlPlaneError):
            http.rotate_genuine_operator_session(
                principal(),
                SecretStr(TOKEN),
                SecretStr(REFRESH_TOKEN),
                minimum_access_seconds=1200,
            )
    else:
        tokens, _ = http.rotate_genuine_operator_session(
            principal(), SecretStr(TOKEN), SecretStr(REFRESH_TOKEN), minimum_access_seconds=1200
        )
        assert tokens.access_expires_at == expiry


def test_public_rotation_rechecks_access_window_after_actual_me(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    clock = {"now": now}
    monkeypatch.setattr(http, "datetime", SimpleNamespace(now=lambda _tz: clock["now"]))
    expiry = now + timedelta(seconds=1201)
    monkeypatch.setattr(
        http,
        "_post",
        lambda *_a, **_kw: (200, refresh_reply(now, access_expires_at=expiry.isoformat())),
    )

    def read() -> CurrentOperator:
        clock["now"] += timedelta(seconds=1)
        return principal(access_expires_at=expiry)

    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_a: SimpleNamespace(read=read)
    )
    with pytest.raises(ControlPlaneError):
        http.rotate_genuine_operator_session(
            principal(), SecretStr(TOKEN), SecretStr(REFRESH_TOKEN), minimum_access_seconds=1200
        )


def test_public_rotation_unknown_http_outcome_has_one_attempt_and_redacted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def uncertain(path: str, *_args: Any, **_kwargs: Any) -> tuple[int, object]:
        calls.append(path)
        raise ControlPlaneError("UNTRUSTED_" + REFRESH_TOKEN, TOKEN)

    monkeypatch.setattr(http, "_post", uncertain)
    with pytest.raises(ControlPlaneError) as caught:
        http.rotate_genuine_operator_session(
            principal(), SecretStr(TOKEN), SecretStr(REFRESH_TOKEN)
        )
    assert calls == [http._REFRESH]
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"
    assert TOKEN not in str(caught.value) and REFRESH_TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("expired", [False, True])
def test_proactive_rotation_validates_new_bearer_before_installing_same_session(
    monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    value, clock = refresh_session(monkeypatch)
    if expired:
        clock["now"] += timedelta(seconds=180)
    expiry = clock["now"] + timedelta(minutes=30)
    expected = principal(
        access_expires_at=expiry,
        effective_permissions=["item:read", "knowledge:analysis:read"],
    )
    events: list[str] = []

    def refresh(path: str, body: Any, **kwargs: Any) -> tuple[int, object]:
        assert path == http._REFRESH and kwargs == {}
        assert json.loads(body()) == {"refresh_token": REFRESH_TOKEN}
        assert value._bearer.get_secret_value() == TOKEN
        events.append("REFRESH")
        return 200, refresh_reply(clock["now"])

    def reader(bearer: SecretStr) -> Any:
        assert bearer.get_secret_value() == NEXT_TOKEN

        def read() -> CurrentOperator:
            if not events or events[-1] == "REFRESH":
                assert value._bearer.get_secret_value() == TOKEN
            events.append("NEW_ME")
            return expected

        return SimpleNamespace(read=read)

    monkeypatch.setattr(http, "_post", refresh)
    monkeypatch.setattr(http, "FixedApiControlPrincipalReader", reader)
    assert value.read() == expected
    assert events == ["REFRESH", "NEW_ME"]
    assert value._bearer.get_secret_value() == NEXT_TOKEN
    assert value._refresh is not None and value._refresh.get_secret_value() == NEXT_REFRESH
    assert value._authenticated_at == AUTHENTICATED_AT
    assert value._operator_id == ACTOR and value._session_id == SESSION
    assert value.read() == expected
    assert events == ["REFRESH", "NEW_ME", "NEW_ME"]


def test_long_lived_access_and_bearer_only_session_do_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, clock = refresh_session(monkeypatch, remaining_seconds=181)
    monkeypatch.setattr(http, "_post", lambda *_args, **_kw: pytest.fail("unexpected renewal"))
    value.read()
    bearer_only = session(monkeypatch)
    monkeypatch.setattr(
        bearer_only,
        "_reader",
        SimpleNamespace(read=lambda: principal(access_expires_at=clock["now"])),
    )
    with pytest.raises(ControlPlaneError) as caught:
        bearer_only.read()
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": "apisession_" + "c" * 32},
        {"operator_id": "operator_" + "c" * 32},
        {"username": "other-user"},
        {"authenticated_at": AUTHENTICATED_AT + timedelta(seconds=1)},
        {"password_change_required": True},
        {"access_expires_at": datetime(2100, 1, 1, tzinfo=UTC)},
    ],
)
def test_rotated_me_identity_or_expiry_drift_never_installs_new_tokens(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, clock = refresh_session(monkeypatch)
    posts: list[str] = []

    def refresh(*_args: Any, **_kw: Any) -> tuple[int, object]:
        posts.append("REFRESH")
        return 200, refresh_reply(clock["now"])

    changed = principal(**({"access_expires_at": clock["now"] + timedelta(minutes=30)} | changes))
    monkeypatch.setattr(http, "_post", refresh)
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=lambda: changed)
    )
    for _attempt in range(2):
        with pytest.raises(ControlPlaneError):
            value.read()
    assert posts == ["REFRESH"]
    assert value._bearer.get_secret_value() == TOKEN and value._refresh_failed


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": "apisession_" + "c" * 32},
        {"password_change_required": True},
        {"access_token": TOKEN},
        {"refresh_token": REFRESH_TOKEN},
        {"refresh_token": "eom_rt_short"},
        {"access_expires_at": "invalid-expiry"},
        {"access_expires_at": datetime(2000, 1, 1, tzinfo=UTC).isoformat()},
        {"refresh_expires_at": datetime(2000, 1, 1, tzinfo=UTC).isoformat()},
    ],
)
def test_invalid_rotated_token_pair_is_terminal_before_new_reader(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    value, clock = refresh_session(monkeypatch)
    posts: list[str] = []

    def refresh(*_args: Any, **_kw: Any) -> tuple[int, object]:
        posts.append("REFRESH")
        return 200, refresh_reply(clock["now"], **changes)

    monkeypatch.setattr(http, "_post", refresh)
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: pytest.fail("reader called")
    )
    for _attempt in range(2):
        with pytest.raises(ControlPlaneError):
            value.read()
    assert posts == ["REFRESH"] and value._bearer.get_secret_value() == TOKEN


def test_rotated_access_ttl_must_exceed_pre_request_safety_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, clock = refresh_session(monkeypatch, remaining_seconds=180)
    monkeypatch.setattr(
        http,
        "_post",
        lambda *_args, **_kw: (
            200,
            refresh_reply(
                clock["now"],
                access_expires_at=(clock["now"] + timedelta(seconds=180)).isoformat(),
            ),
        ),
    )
    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: pytest.fail("reader called")
    )
    with pytest.raises(ControlPlaneError):
        value.read()
    assert value._refresh_failed and value._bearer.get_secret_value() == TOKEN


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_refresh_denied_or_server_failure_cannot_repeat_consumed_token(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    value, _clock = refresh_session(monkeypatch)
    posts: list[str] = []

    def refresh(*_args: Any, **_kw: Any) -> tuple[int, object]:
        posts.append("REFRESH")
        return status, {"error_code": REFRESH_TOKEN}

    monkeypatch.setattr(http, "_post", refresh)
    for _attempt in range(2):
        with pytest.raises(ControlPlaneError) as caught:
            value.read()
        assert REFRESH_TOKEN not in str(caught.value) and caught.value.__cause__ is None
    assert posts == ["REFRESH"]


def test_unknown_refresh_network_outcome_poisoned_without_replaying_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _clock = refresh_session(monkeypatch)
    paths: list[str] = []

    def uncertain(path: str, *_args: Any, **_kw: Any) -> tuple[int, object]:
        paths.append(path)
        raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", REFRESH_TOKEN)

    monkeypatch.setattr(http, "_post", uncertain)
    for _attempt in range(2):
        with pytest.raises(SnapshotReadFailure):
            value.execute(ACTOR, snapshot_prepare())
    assert paths == [http._REFRESH]


def test_new_me_revocation_blocks_operation_and_never_installs_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, clock = refresh_session(monkeypatch)
    monkeypatch.setattr(http, "_post", lambda *_args, **_kw: (200, refresh_reply(clock["now"])))

    def denied() -> CurrentOperator:
        raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", NEXT_TOKEN)

    monkeypatch.setattr(
        http, "FixedApiControlPrincipalReader", lambda *_args: SimpleNamespace(read=denied)
    )
    with pytest.raises(ControlPlaneError) as caught:
        value.read()
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert NEXT_TOKEN not in str(caught.value) and value._bearer.get_secret_value() == TOKEN


def test_refreshed_permissions_not_old_permission_cache_authorize_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, clock = refresh_session(monkeypatch)
    refreshed = principal(access_expires_at=clock["now"] + timedelta(minutes=30))
    monkeypatch.setattr(http, "_post", lambda *_args, **_kw: (200, refresh_reply(clock["now"])))
    monkeypatch.setattr(
        http,
        "FixedApiControlPrincipalReader",
        lambda *_args: SimpleNamespace(read=lambda: refreshed),
    )
    monkeypatch.setattr(http, "_get", lambda *_args, **_kw: pytest.fail("forbidden read"))
    with pytest.raises(ControlPlaneError) as caught:
        value._require_read_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert value._bearer.get_secret_value() == NEXT_TOKEN


def test_refresh_fixed_peer_precedes_unmasking_refresh_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = connection(monkeypatch, b"{}")
    monkeypatch.setattr(
        http,
        "require_fixed_api_peer_socket",
        lambda _sock: (_ for _ in ()).throw(ValueError("bad")),
    )
    with pytest.raises(ControlPlaneError):
        http._post(http._REFRESH, lambda: pytest.fail("refresh secret materialized"))
    assert transport.requests == [] and transport.events == ["FACTORY", "CONNECT", "CLOSE"]
