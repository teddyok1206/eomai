"""Private manual-session transport uses existing admin cookie, CSRF and identity."""

import json

import httpx
import pytest
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_manual_contracts import (
    ManualEnd,
    ManualMutation,
    ManualRenew,
    ManualSession,
    ManualStart,
)

from tests.unit.kakao_manual_fixtures import BINDING, KEY, LEASE, start
from tests.unit.kakao_manual_fixtures import session as manual_session
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway

ROOT = "/studio/api/v1/kakao-archive/manual-sessions"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def result(phase="PREPARING", version=1, grant=0):
    return ManualMutation(
        session=ManualSession.model_validate(
            manual_session(phase, version, grant).model_dump(mode="json")
        ),
        replayed=False,
    )


class ManualGateway(FakeGateway):
    def __init__(self, roles=None):
        super().__init__(roles=roles or ["ADMIN"])
        self.calls = []

    async def kakao_manual_start(self, session, value, key):
        self.calls.append(("start", session, value, key))
        return result()

    async def kakao_manual_read(self, session, lease):
        self.calls.append(("read", session, lease))
        return result().session

    async def kakao_manual_command(self, session, lease, value, key, etag):
        self.calls.append(("command", session, lease, value, key, etag))
        return result("STOPPING", 2) if isinstance(value, ManualEnd) else result("ACTIVE", 4, 2)


def test_admin_cookie_csrf_and_start_accepted_not_ready():
    gateway = ManualGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(ROOT + "/" + LEASE).status_code == 401
        auth = login(client)
        assert client.post(ROOT, json=start().model_dump(mode="json")).status_code == 403
        headers = {"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": KEY}
        response = client.post(ROOT, json=start().model_dump(mode="json"), headers=headers)
        assert response.status_code == 202, response.text
        assert (
            response.headers["cache-control"] == "no-store" and response.headers["etag"] == '"v1"'
        )
        assert response.json()["session"]["ready"] is False
        assert client.get(ROOT + "/" + LEASE).status_code == 200
        assert [call[0] for call in gateway.calls] == ["start", "read"]
        end = {
            "schema_version": "kakao-manual-command/1.0",
            "action": "END",
            "expected_resource_version": 1,
        }
        assert (
            client.post(ROOT + "/" + LEASE + "/commands", json=end, headers=headers).status_code
            == 412
        )
        response = client.post(
            ROOT + "/" + LEASE + "/commands", json=end, headers=headers | {"If-Match": '"v1"'}
        )
        assert response.status_code == 200 and gateway.calls[-1][-2:] == (KEY, '"v1"')
        renew = {
            "schema_version": "kakao-manual-command/1.0",
            "action": "RENEW",
            "expected_grant_revision": 1,
        }
        assert (
            client.post(ROOT + "/" + LEASE + "/commands", json=renew, headers=headers).status_code
            == 200
        )
        assert gateway.calls[-1][-1] is None


def test_non_admin_cannot_start_read_or_end():
    gateway = ManualGateway(roles=["VIEWER"])
    client, _ = make_client(gateway=gateway)
    with client:
        auth = login(client)
        assert client.get(ROOT + "/" + LEASE).status_code == 403
        assert (
            client.post(
                ROOT,
                json=start().model_dump(mode="json"),
                headers={"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": KEY},
            ).status_code
            == 403
        )
        assert not gateway.calls


@pytest.mark.parametrize(
    "field", ["profile_id", "owner_operator_id", "ready", "remote_url", "duration"]
)
def test_start_rejects_runtime_and_authority_fields(field):
    gateway = ManualGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        auth = login(client)
        assert (
            client.post(
                ROOT,
                json=start().model_dump(mode="json") | {field: True},
                headers={"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": KEY},
            ).status_code
            == 422
        )
        assert not gateway.calls


@pytest.mark.anyio
async def test_gateway_exact_key_body_and_only_end_etag():
    calls = []

    def transport(request):
        calls.append(request)
        if request.method == "GET":
            data = result().session.model_dump(mode="json")
        elif request.url.path.endswith("/commands"):
            command = json.loads(request.content)
            data = (
                result("STOPPING", 2) if command["action"] == "END" else result("ACTIVE", 4, 2)
            ).model_dump(mode="json")
        else:
            data = result().model_dump(mode="json")
        return httpx.Response(200, json=_single(data))

    gateway = http_gateway(transport)
    try:
        command = ManualStart.model_validate(start().model_dump(mode="json"))
        for _ in range(2):
            assert not (await gateway.kakao_manual_start(_session(), command, KEY)).session.ready
        assert (
            calls[0].content == calls[1].content
            and calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"] == KEY
        )
        assert (await gateway.kakao_manual_read(_session(), LEASE)).lease_id == LEASE
        await gateway.kakao_manual_command(
            _session(),
            LEASE,
            ManualEnd(
                schema_version="kakao-manual-command/1.0", action="END", expected_resource_version=1
            ),
            KEY,
            '"v1"',
        )
        assert calls[-1].headers["If-Match"] == '"v1"'
        await gateway.kakao_manual_command(
            _session(),
            LEASE,
            ManualRenew(
                schema_version="kakao-manual-command/1.0", action="RENEW", expected_grant_revision=1
            ),
            KEY,
            None,
        )
        assert "If-Match" not in calls[-1].headers
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["binding", "ready", "lease", "grant", "end-version"])
async def test_gateway_rejects_cross_identity_and_invalid_reply(case):
    data = (
        result("ACTIVE", 4, 2).model_dump(mode="json")
        if case == "grant"
        else result("STOPPING", 9).model_dump(mode="json")
        if case == "end-version"
        else result().model_dump(mode="json")
    )
    if case == "binding":
        data["session"]["source_binding_id"] = "kakaobinding_" + "9" * 32
    elif case == "ready":
        data["session"]["ready"] = True
    elif case == "lease":
        data = data["session"] | {"lease_id": "kakaoremotelease_" + "9" * 32}
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(data)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            if case == "lease":
                await gateway.kakao_manual_read(_session(), LEASE)
            elif case == "grant":
                await gateway.kakao_manual_command(
                    _session(),
                    LEASE,
                    ManualRenew(
                        schema_version="kakao-manual-command/1.0",
                        action="RENEW",
                        expected_grant_revision=2,
                    ),
                    KEY,
                    None,
                )
            elif case == "end-version":
                await gateway.kakao_manual_command(
                    _session(),
                    LEASE,
                    ManualEnd(
                        schema_version="kakao-manual-command/1.0",
                        action="END",
                        expected_resource_version=1,
                    ),
                    KEY,
                    '"v1"',
                )
            else:
                await gateway.kakao_manual_start(
                    _session(),
                    ManualStart(schema_version="kakao-manual-start/1.0", source_binding_id=BINDING),
                    KEY,
                )
    finally:
        await gateway.close()
