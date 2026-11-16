"""Cookie, CSRF and exact room mapping transport through actual HTTP adapters."""

import json

import httpx
import pytest
from eom_catalog_contracts.kakao_rooms import KakaoRoomMutation, KakaoRoomPage
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_room_contracts import Room, RoomMap, RoomMutation, RoomPage

from tests.api.test_kakao_room_routes import room_client as _room_client
from tests.unit.kakao_room_fixtures import BINDING_ID, KEY, MAPPING_ID, ROOM_ID, map_command, room
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway

ROOT = "/studio/api/v1/kakao-archive/rooms"
PARAMS = {"source_binding_id": BINDING_ID}
room_api_fixture = _room_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RoomGateway(FakeGateway):
    def __init__(self):
        super().__init__(roles=["VIEWER"])
        self.calls = []

    async def kakao_room_list(self, session, source_binding_id, *, limit=50, cursor=None):
        self.calls.append(("list", session, source_binding_id, limit, cursor))
        return RoomPage.model_validate(
            KakaoRoomPage(items=(room(),), next_cursor=None).model_dump(mode="json")
        )

    async def kakao_room_read(
        self, session, source_binding_id, room_id, *, mapping_revision_id=None
    ):
        self.calls.append(("read", session, source_binding_id, room_id, mapping_revision_id))
        return Room.model_validate(room().model_dump(mode="json"))

    async def kakao_room_command(
        self, session, source_binding_id, room_id, value, idempotency_key, if_match
    ):
        self.calls.append(
            ("command", session, source_binding_id, room_id, value, idempotency_key, if_match)
        )
        return RoomMutation.model_validate(
            KakaoRoomMutation(room=room(mapped=True), replayed=False).model_dump(mode="json")
        )


def test_existing_cookie_csrf_and_headers_without_new_authority():
    gateway = RoomGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(ROOT, params=PARAMS).status_code == 401
        session = login(client)
        path = ROOT + "/" + ROOM_ID + "/mapping"
        body = map_command().model_dump(mode="json")
        assert client.post(path, params=PARAMS, json=body).status_code == 403
        assert not gateway.calls
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": KEY,
            "If-Match": '"v1"',
        }
        response = client.post(path, params=PARAMS, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert (
            response.headers["etag"] == '"v2"' and response.headers["cache-control"] == "no-store"
        )
        assert gateway.calls[-1][2:4] == (BINDING_ID, ROOM_ID) and gateway.calls[-1][-2:] == (
            KEY,
            '"v1"',
        )
        assert client.get(ROOT, params=PARAMS).status_code == 200
        assert (
            client.get(
                ROOT + "/" + ROOM_ID, params={**PARAMS, "mapping_revision_id": MAPPING_ID}
            ).status_code
            == 200
        )
        assert gateway.calls[-1][-1] == MAPPING_ID


@pytest.mark.parametrize(
    "case",
    [
        "missing-binding",
        "invalid-binding",
        "missing-etag",
        "weak-etag",
        "name-authority",
        "parent-latest",
    ],
)
def test_invalid_scope_or_mutation_never_reaches_gateway(case):
    gateway = RoomGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": KEY,
            "If-Match": '"v1"',
        }
        params = dict(PARAMS)
        body = map_command().model_dump(mode="json")
        if case == "missing-binding":
            params = {}
        elif case == "invalid-binding":
            params = {"source_binding_id": "latest"}
        elif case == "missing-etag":
            del headers["If-Match"]
        elif case == "weak-etag":
            headers["If-Match"] = 'W/"v1"'
        elif case == "name-authority":
            body["student_display_name"] = "same name"
        else:
            body["parent_revision_id"] = "latest"
        response = client.post(
            ROOT + "/" + ROOM_ID + "/mapping", params=params, json=body, headers=headers
        )
        assert response.status_code == 422 and not gateway.calls


@pytest.mark.anyio
async def test_gateway_through_actual_api_preserves_mapping_and_same_intent(room_api_fixture):
    api, owner, _ = room_api_fixture
    requests = []

    def transport(request):
        requests.append(request)
        response = api.request(
            request.method,
            str(request.url.copy_with(scheme="http", host="localhost")),
            headers={
                **{k: v for k, v in request.headers.items() if k != "host"},
                "Host": "localhost",
            },
            content=request.content,
        )
        assert response.status_code < 400, response.text
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    gateway = http_gateway(transport)
    try:
        command = RoomMap.model_validate(map_command().model_dump(mode="json"))
        for _ in range(2):
            assert (
                await gateway.kakao_room_command(
                    _session(), BINDING_ID, ROOM_ID, command, KEY, '"v1"'
                )
            ).room.mapping.student_id == command.student_id
        assert requests[0].content == requests[1].content
        assert (
            requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"] == KEY
        )
        assert requests[0].url.params["source_binding_id"] == BINDING_ID
        assert (
            json.loads(requests[0].content)["student_display_revision_id"]
            == command.student_display_revision_id
        )
        assert (
            await gateway.kakao_room_read(
                _session(), BINDING_ID, ROOM_ID, mapping_revision_id=MAPPING_ID
            )
        ).mapping.mapping_revision_id == MAPPING_ID
        assert len((await gateway.kakao_room_list(_session(), BINDING_ID)).items) == 1
        assert owner.command_kakao_room.call_count == 2
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    ["binding", "room", "revision", "parent", "student", "display", "page-binding", "duplicate"],
)
async def test_private_reply_correlation_rejects_other_scope(case):
    mutation = case in {"parent", "student", "display"}
    value = room(mapped=mutation).model_dump(mode="json")
    if case in {"binding", "page-binding"}:
        value["source_binding_id"] = "kakaobinding_" + "9" * 32
    elif case == "room":
        value["room_id"] = "kakaoroom_" + "9" * 32
    elif case in {"revision", "parent"}:
        value["mapping"][
            "mapping_revision_id" if case == "revision" else "previous_revision_id"
        ] = "kakaomappingrev_" + "9" * 32
    elif case == "student":
        value["mapping"]["student_id"] = "kakaostudent_" + "9" * 32
    elif case == "display":
        value["mapping"]["student_display_revision_id"] = "kakaostudentrev_" + "9" * 32
    data = (
        {"room": value, "replayed": True}
        if mutation
        else {"items": [value, value] if case == "duplicate" else [value], "next_cursor": None}
        if case in {"duplicate", "page-binding"}
        else value
    )
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(data)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            if mutation:
                await gateway.kakao_room_command(
                    _session(),
                    BINDING_ID,
                    ROOM_ID,
                    RoomMap.model_validate(map_command().model_dump(mode="json")),
                    KEY,
                    '"v1"',
                )
            elif case in {"duplicate", "page-binding"}:
                await gateway.kakao_room_list(_session(), BINDING_ID)
            else:
                await gateway.kakao_room_read(
                    _session(), BINDING_ID, ROOM_ID, mapping_revision_id=MAPPING_ID
                )
    finally:
        await gateway.close()
