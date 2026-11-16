"""Synthetic sessions and actual HTTP routes; no browser login or private runtime."""

import asyncio
import base64
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from eom_kakao_archive_contracts.kakao_remote import RemoteTransportPolicy, validate_remote_contract
from eom_web_gui.app import create_app
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_manual_contracts import ManualMutation, ManualSession
from eom_web_gui.sessions import ApiTokens, KakaoManualPointer, SessionStore
from eom_web_gui.settings import SessionSettings
from fastapi.testclient import TestClient

from tests.unit.kakao_manual_fixtures import KEY, LEASE, start
from tests.web_gui.helpers import login, make_services
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway
from tests.web_gui.test_kakao_manual_routes import ROOT, ManualGateway, result

AUTHORIZE = "/studio/api/v1/kakao-archive/remote/authorize"
POLICY = RemoteTransportPolicy(
    expected_origin="https://testserver.local",
    static_paths=frozenset({"/studio/admin/remote/vnc.html", "/studio/admin/remote/app/ui.js"}),
)
FORWARDED = {
    "X-Forwarded-Method": "GET",
    "X-Forwarded-Uri": "/studio/admin/remote/vnc.html",
    "X-EOM-Remote-Protocol": "HTTP/2.0",
}
WS = FORWARDED | {
    "X-Forwarded-Uri": "/studio/admin/remote/websockify",
    "X-EOM-Remote-Protocol": "HTTP/1.1",
    "X-EOM-Remote-Origin": POLICY.expected_origin,
    "X-EOM-Remote-Upgrade": "websocket",
    "X-EOM-Remote-Connection": "keep-alive, Upgrade",
    "X-EOM-Remote-Version": "13",
    "X-EOM-Remote-Key": base64.b64encode(b"0123456789abcdef").decode(),
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RemoteGateway(ManualGateway):
    async def kakao_manual_authorize(self, session, lease_id):
        self.calls.append(("authorize", session, lease_id))


def client_for(gateway, policy=POLICY):
    services, _ = make_services(gateway=gateway)
    settings = services.settings.model_copy(
        update={"sessions": SessionSettings(cookie_secure=True)}
    )
    return (
        TestClient(
            create_app(services, settings=settings, remote_transport_policy=policy),
            base_url="https://testserver.local",
        ),
        services,
    )


def begin(client):
    auth = login(client)
    headers = {"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": KEY}
    assert (
        client.post(ROOT, json=start().model_dump(mode="json"), headers=headers).status_code == 202
    )
    return headers


@pytest.mark.parametrize("headers", [FORWARDED, WS])
def test_proxy_requires_exact_api_authorization_for_each_static_or_ws_request(headers):
    gateway = RemoteGateway()
    client, _ = client_for(gateway)
    with client:
        assert client.get(AUTHORIZE, headers=headers).status_code == 401
        begin(client)
        for _ in range(2):
            response = client.get(AUTHORIZE, headers=headers)
            assert response.status_code == 204 and response.content == b""
            assert response.headers["cache-control"] == "no-store"
        session = gateway.calls[0][1]
        assert session.kakao_manual.lease_id == LEASE
        with pytest.raises(FrozenInstanceError):
            session.kakao_manual.lease_id = "other"
        assert [call[0] for call in gateway.calls] == ["start", "authorize", "authorize"]


def test_default_uninstalled_transport_and_missing_pointer_are_not_authorization():
    gateway = RemoteGateway()
    client, _ = client_for(gateway, policy=None)
    with client:
        begin(client)
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code == 503
        assert [call[0] for call in gateway.calls] == ["start"]
    client, _ = client_for(RemoteGateway())
    with client:
        login(client)
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code == 403


@pytest.mark.parametrize("policy", [None, POLICY])
def test_presentation_reports_only_installed_configuration_not_readiness(policy):
    gateway = RemoteGateway()
    client, _ = client_for(gateway, policy=policy)
    path = "/studio/api/v1/kakao-archive/remote/configuration"
    with client:
        assert client.get(path).status_code == 401
        login(client)
        response = client.get(path)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "schema_version": "kakao-remote-presentation/1.0",
            "remote_view_enabled": policy is not None,
        }
        validate_remote_contract("presentation", response.json())
        assert gateway.calls == []
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code != 204


def test_installed_web_configuration_supplies_same_policy_to_presentation_and_admission():
    gateway = RemoteGateway()
    services, _ = make_services(gateway=gateway)
    settings = services.settings.model_copy(
        update={"sessions": SessionSettings(cookie_secure=True), "kakao_remote_transport": POLICY}
    )
    with TestClient(
        create_app(services, settings=settings), base_url="https://testserver.local"
    ) as client:
        begin(client)
        assert (
            client.get("/studio/api/v1/kakao-archive/remote/configuration").json()[
                "remote_view_enabled"
            ]
            is True
        )
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code == 204


def test_direct_policy_injection_obeys_same_secure_cookie_and_host_configuration():
    from pydantic import ValidationError

    services, _ = make_services(gateway=RemoteGateway())
    with pytest.raises(ValidationError, match="Secure cookies"):
        create_app(services, remote_transport_policy=POLICY)


@pytest.mark.parametrize(
    "extra", [{"remote_view_enabled": "true"}, {"origin": "https://example.invalid"}]
)
def test_presentation_contract_rejects_coercion_and_unneeded_inventory(extra):
    value = {"schema_version": "kakao-remote-presentation/1.0", "remote_view_enabled": True}
    with pytest.raises(ValueError, match="KAKAO_REMOTE_SCHEMA_INVALID"):
        validate_remote_contract("presentation", value | extra)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        FORWARDED | {"X-Forwarded-Method": "POST"},
        FORWARDED | {"X-Forwarded-Uri": "/studio/admin/remote/"},
        FORWARDED | {"X-Forwarded-Uri": "/studio/admin/remote/vnc.html?token=synthetic"},
        FORWARDED | {"X-Forwarded-Uri": "/studio/admin/remote/%2e%2e/profile"},
        FORWARDED | {"X-EOM-Remote-Origin": "https://foreign.invalid"},
        FORWARDED | {"X-EOM-Remote-Upgrade": "websocket"},
        WS | {"X-EOM-Remote-Origin": "https://foreign.invalid"},
        WS | {"X-EOM-Remote-Protocol": "HTTP/2.0"},
        WS | {"X-EOM-Remote-Key": "invalid"},
        WS | {"X-EOM-Remote-Version": "12"},
        WS | {"X-EOM-Remote-Connection": "close"},
    ],
)
def test_invalid_forwarded_transport_never_reaches_lease_authority(headers):
    gateway = RemoteGateway()
    client, _ = client_for(gateway)
    with client:
        begin(client)
        assert client.get(AUTHORIZE, headers=headers).status_code == 403
        assert [call[0] for call in gateway.calls] == ["start"]


def test_duplicate_forwarding_headers_query_and_cross_session_are_denied():
    gateway = RemoteGateway()
    client, services = client_for(gateway)
    with client:
        begin(client)
        duplicated = [*FORWARDED.items(), ("X-Forwarded-Uri", "/studio/admin/remote/app/ui.js")]
        assert client.get(AUTHORIZE, headers=duplicated).status_code == 403
        assert client.get(AUTHORIZE + "?lease=" + LEASE, headers=FORWARDED).status_code == 403
        original = gateway.calls[0][1]
        client.cookies.clear()
        login(client)
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code == 403
        assert original.kakao_manual is not None
        services.sessions.delete(original.session_id)
        assert original.kakao_manual is None
        assert [call[0] for call in gateway.calls] == ["start"]


@pytest.mark.parametrize("status", [401, 403, 404, 503])
def test_api_denial_is_never_200_false(status):
    class Denied(RemoteGateway):
        async def kakao_manual_authorize(self, session, lease_id):
            raise GatewayError(status=status, code="KAKAO_REMOTE_TEST_DENIED")

    client, _ = client_for(Denied())
    with client:
        begin(client)
        assert client.get(AUTHORIZE, headers=FORWARDED).status_code == status


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,body", [(200, b"false"), (200, b""), (202, b""), (204, b"x"), (302, b"")]
)
async def test_gateway_authorize_requires_exact_empty_204(status, body):
    gateway = http_gateway(lambda _: httpx.Response(status, content=body))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.kakao_manual_authorize(_session(), LEASE)
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_gateway_authorize_reuses_normal_token_refresh_and_fixed_get():
    requests = []

    def transport(request):
        requests.append(request)
        if request.url.path == "/api/v1/auth/refresh":
            now = datetime.now(UTC)
            return httpx.Response(
                200,
                json=_single(
                    {
                        "access_token": "eom_at_TEST_ONLY_NEW_ACCESS",
                        "refresh_token": "eom_rt_TEST_ONLY_NEW_REFRESH",
                        "token_type": "Bearer",
                        "access_expires_at": (now + timedelta(minutes=10)).isoformat(),
                        "refresh_expires_at": (now + timedelta(hours=1)).isoformat(),
                    }
                ),
            )
        return httpx.Response(
            204 if request.headers["Authorization"] == "Bearer eom_at_TEST_ONLY_NEW_ACCESS" else 401
        )

    gateway = http_gateway(transport)
    try:
        assert await gateway.kakao_manual_authorize(_session(), LEASE) is None
        assert [request.method for request in requests] == ["GET", "POST", "GET"]
        assert (
            requests[0].url.path
            == requests[2].url.path
            == f"/api/v1/kakao-archive/manual-sessions/{LEASE}/authorize"
        )
        assert not requests[0].url.query and not requests[0].content
    finally:
        await gateway.close()


def changed(original, **updates):
    return ManualSession.model_validate(original.model_dump() | updates)


@pytest.fixture
async def async_http():
    gateway = RemoteGateway()
    services, _ = make_services(gateway=gateway)
    now = datetime.now(UTC)
    session = services.sessions.create(
        operator={"operator_id": "operator_" + "3" * 32, "roles": ["ADMIN"]},
        tokens=ApiTokens(
            "test-access", "test-refresh", now + timedelta(hours=1), now + timedelta(hours=2)
        ),
        now=now,
    )
    settings = services.settings.model_copy(
        update={"sessions": SessionSettings(cookie_secure=True)}
    )
    app = create_app(services, settings=settings, remote_transport_policy=POLICY)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver.local",
        cookies={"eom_studio_session": session.session_id},
        headers={"X-CSRF-Token": session.csrf_token, "Idempotency-Key": KEY},
    ) as client:
        yield client, gateway, session, services


@pytest.mark.anyio
@pytest.mark.parametrize("slow_action", ["read", "start", "end"])
async def test_old_response_cannot_replace_or_clear_new_pointer(async_http, slow_action):
    client, gateway, session, _ = async_http
    assert (await client.post(ROOT, json=start().model_dump(mode="json"))).status_code == 202
    old = result().session
    newer = changed(
        old,
        lease_id="kakaoremotelease_" + "9" * 32,
        created_at=old.created_at + timedelta(seconds=1),
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        entered.set()
        await release.wait()
        return (
            old
            if slow_action == "read"
            else result("STOPPING", 2)
            if slow_action == "end"
            else result()
        )

    method = {
        "read": "kakao_manual_read",
        "start": "kakao_manual_start",
        "end": "kakao_manual_command",
    }[slow_action]
    setattr(gateway, method, delayed)
    if slow_action == "read":
        task = asyncio.create_task(client.get(ROOT + "/" + LEASE))
    elif slow_action == "start":
        task = asyncio.create_task(client.post(ROOT, json=start().model_dump(mode="json")))
    else:
        task = asyncio.create_task(
            client.post(
                ROOT + "/" + LEASE + "/commands",
                headers={"If-Match": '"v1"'},
                json={
                    "schema_version": "kakao-manual-command/1.0",
                    "action": "END",
                    "expected_resource_version": 1,
                },
            )
        )
    await asyncio.wait_for(entered.wait(), timeout=3)

    async def new_start(*args):
        return ManualMutation(session=newer, replayed=False)

    gateway.kakao_manual_start = new_start
    assert (await client.post(ROOT, json=start().model_dump(mode="json"))).status_code == 202
    assert session.kakao_manual.lease_id == newer.lease_id
    release.set()
    assert (await task).status_code in {200, 202}
    assert session.kakao_manual.lease_id == newer.lease_id


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["end", "logout"])
async def test_pointer_change_during_authorization_denies_stale_success(async_http, change):
    client, gateway, session, services = async_http
    await client.post(ROOT, json=start().model_dump(mode="json"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        entered.set()
        await release.wait()

    gateway.kakao_manual_authorize = delayed
    task = asyncio.create_task(client.get(AUTHORIZE, headers=FORWARDED))
    await asyncio.wait_for(entered.wait(), timeout=3)
    if change == "logout":
        services.sessions.delete(session.session_id)
    else:
        response = await client.post(
            ROOT + "/" + LEASE + "/commands",
            headers={"If-Match": '"v1"'},
            json={
                "schema_version": "kakao-manual-command/1.0",
                "action": "END",
                "expected_resource_version": 1,
            },
        )
        assert response.status_code == 200
    release.set()
    assert (await task).status_code == 403 and session.kakao_manual is None


@pytest.mark.anyio
async def test_replayed_start_reads_current_phase_before_rebinding(async_http):
    client, gateway, session, _ = async_http

    async def replay(*args):
        return ManualMutation(session=result().session, replayed=True)

    async def stopped(*args):
        return result("STOPPING", 2).session

    gateway.kakao_manual_start, gateway.kakao_manual_read = replay, stopped
    response = await client.post(ROOT, json=start().model_dump(mode="json"))
    assert response.status_code == 202 and response.json()["replayed"] is True
    assert session.kakao_manual is None


@pytest.mark.anyio
async def test_replayed_start_rejects_other_binding_read(async_http):
    client, gateway, session, _ = async_http

    async def replay(*args):
        return ManualMutation(session=result().session, replayed=True)

    async def different(*args):
        return changed(result().session, source_binding_id="kakaobinding_" + "9" * 32)

    gateway.kakao_manual_start, gateway.kakao_manual_read = replay, different
    response = await client.post(ROOT, json=start().model_dump(mode="json"))
    assert response.status_code == 502 and session.kakao_manual is None


@pytest.mark.anyio
async def test_current_read_can_recover_pointer_but_late_read_after_logout_cannot(async_http):
    client, gateway, session, services = async_http
    assert (await client.get(ROOT + "/" + LEASE)).status_code == 200
    assert session.kakao_manual.lease_id == LEASE
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        entered.set()
        await release.wait()
        return result().session

    gateway.kakao_manual_read = delayed
    task = asyncio.create_task(client.get(ROOT + "/" + LEASE))
    await asyncio.wait_for(entered.wait(), timeout=3)
    await asyncio.to_thread(services.sessions.delete, session.session_id)
    release.set()
    assert (await task).status_code == 200 and session.kakao_manual is None


@pytest.mark.parametrize("removal", ["delete", "expiry", "capacity", "credential-change"])
def test_session_store_removal_invalidates_only_that_sessions_pointer(removal):
    store = SessionStore(ttl_seconds=60, maximum_sessions=2, maximum_drafts=1)
    now = datetime.now(UTC)
    tokens = ApiTokens(
        "synthetic-access",
        "synthetic-refresh",
        now + timedelta(minutes=5),
        now + timedelta(hours=1),
    )

    def make():
        return store.create(
            operator={"operator_id": "operator_" + "3" * 32}, tokens=tokens, now=now
        )

    first, other = make(), make()
    value = result().session
    first.kakao_manual = KakaoManualPointer(LEASE, value.source_binding_id, value.created_at, 1)
    first.kakao_manual_generation = 7
    if removal == "delete":
        store.delete(first.session_id)
    elif removal == "expiry":
        # Only the first session expires during this observation.
        other.expires_at = now + timedelta(minutes=5)
        assert store.get(first.session_id, now=now + timedelta(seconds=61)) is None
    elif removal == "capacity":
        make()
    else:
        assert (
            store.delete_other_operator_sessions(
                first.operator["operator_id"], except_session_id=other.session_id
            )
            == 1
        )
    assert first.kakao_manual is None and first.kakao_manual_generation == 8
    assert other.kakao_manual is None and other.kakao_manual_generation == 0
