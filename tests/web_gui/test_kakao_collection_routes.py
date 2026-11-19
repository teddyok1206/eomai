"""Studio cookie and CSRF boundary plus exact downstream identity checks."""

import httpx
import pytest
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_collection_contracts import (
    RoomCollectionStart,
    RoomCollectionStatus,
    RoomCollectionStatusView,
)

from tests.unit.kakao_room_fixtures import BINDING_ID, KEY, ROOM_ID
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway

ROOT = "/studio/api/v1/kakao-archive/collections"
RUN = "kakaorun_" + "a" * 32
BODY = dict(
    selection=dict(
        schema_version="kakao-capability-confirmation/1.0",
        source_binding_id=BINDING_ID,
        room_id=ROOM_ID,
        expected_binding_version=1,
    ),
    expected_policy_revision_id="kakaopolicyrev_" + "d" * 32,
)
VALUE = dict(
    schema_version="kakao-collection-status/1.0",
    run_id=RUN,
    source_binding_id=BINDING_ID,
    state="QUEUED",
    resource_version=1,
    created_at="2026-11-18T01:02:03Z",
    updated_at="2026-11-18T01:02:03Z",
)
VIEW = dict(
    schema_version="kakao-collection-status-view/1.0",
    collection=VALUE | {"state": "FAILED"},
    failure_reason="KAKAO_LOGIN_REQUIRED",
)


class CollectionGateway(FakeGateway):
    def __init__(self, *, roles):
        super().__init__(roles=roles)
        self.calls = []

    async def kakao_collection_start(self, session, value, idempotency_key, if_match):
        self.calls.append(("start", value, idempotency_key, if_match))
        return RoomCollectionStatus.model_validate(VALUE)

    async def kakao_collection_status(
        self, session, binding, run_id, *, include_failure_reason=False
    ):
        if include_failure_reason:
            self.calls.append(("get-view", binding, run_id))
            return RoomCollectionStatusView.model_validate(VIEW)
        self.calls.append(("get", binding, run_id))
        return RoomCollectionStatus.model_validate(VALUE)


@pytest.mark.parametrize("roles, expected", [(["ADMIN"], 202), (["VIEWER"], 403)])
def test_studio_collection_post_requires_admin_cookie_csrf_and_original_pins(roles, expected):
    gateway = CollectionGateway(roles=roles)
    client, _ = make_client(gateway=gateway)
    with client:
        assert (
            client.get(ROOT + "/" + RUN, params={"source_binding_id": BINDING_ID}).status_code
            == 401
        )
        session = login(client)
        headers = {"Idempotency-Key": KEY, "If-Match": '"v1"'}
        assert client.post(ROOT, json=BODY, headers=headers).status_code == 403
        assert not gateway.calls
        headers["X-CSRF-Token"] = session["csrf_token"]
        sent = client.post(ROOT, json=BODY, headers=headers)
        assert sent.status_code == expected, sent.text
        if expected == 202:
            assert sent.headers["cache-control"] == "no-store"
            assert sent.json()["run_id"] == RUN
            assert gateway.calls == [
                ("start", RoomCollectionStart.model_validate(BODY), KEY, '"v1"')
            ]
        read = client.get(ROOT + "/" + RUN, params={"source_binding_id": BINDING_ID})
        assert read.status_code == 200 and read.headers["cache-control"] == "no-store"
        assert gateway.calls[-1] == ("get", BINDING_ID, RUN)
        view = client.get(
            ROOT + "/" + RUN,
            params={"source_binding_id": BINDING_ID, "include_failure_reason": "true"},
        )
        assert view.status_code == 200 and view.json() == VIEW
        assert gateway.calls[-1] == ("get-view", BINDING_ID, RUN)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_gateway_rejects_other_run_and_binds_start_headers():
    calls = []

    def handle(request):
        calls.append(request)
        value = VALUE if request.method == "POST" else VALUE | {"run_id": "kakaorun_" + "b" * 32}
        return httpx.Response(200, json=_single(value))

    gateway = http_gateway(handle)
    try:
        reply = await gateway.kakao_collection_start(
            _session(), RoomCollectionStart.model_validate(BODY), KEY, '"v1"'
        )
        assert reply.run_id == RUN
        assert calls[0].headers["Idempotency-Key"] == KEY
        assert calls[0].headers["If-Match"] == '"v1"'
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.kakao_collection_status(_session(), BINDING_ID, RUN)
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_gateway_checks_exact_status_view_identity_and_reason():
    cases = iter(
        (
            VIEW,
            VIEW | {"collection": VALUE},
            VIEW | {"collection": VALUE | {"state": "FAILED", "run_id": "kakaorun_" + "b" * 32}},
        )
    )

    def handle(request):
        assert request.url.params["include_failure_reason"] == "true"
        return httpx.Response(200, json=_single(next(cases)))

    gateway = http_gateway(handle)
    try:
        view = await gateway.kakao_collection_status(
            _session(), BINDING_ID, RUN, include_failure_reason=True
        )
        assert isinstance(view, RoomCollectionStatusView)
        assert view.failure_reason == "KAKAO_LOGIN_REQUIRED"
        for _ in range(2):
            with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
                await gateway.kakao_collection_status(
                    _session(), BINDING_ID, RUN, include_failure_reason=True
                )
    finally:
        await gateway.close()
