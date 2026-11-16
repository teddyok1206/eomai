"""Cookie/CSRF student routes and actual HTTP gateway/API contract round trips."""

import json

import httpx
import pytest
from eom_catalog_contracts.kakao_students import KakaoStudentMutation, KakaoStudentPage
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_student_contracts import (
    Student,
    StudentCreate,
    StudentMutation,
    StudentPage,
    StudentRename,
    StudentRetire,
)

from tests.api.test_kakao_student_routes import student_client as _student_client
from tests.unit.kakao_student_fixtures import (
    KEY,
    REVISION_ID,
    STUDENT_ID,
    create_command,
    rename_command,
    retire_command,
    student,
)
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway

ROOT = "/studio/api/v1/kakao-archive/students"
student_api_fixture = _student_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


class StudentGateway(FakeGateway):
    def __init__(self):
        super().__init__(roles=["VIEWER"])
        self.calls = []

    async def kakao_student_create(self, session, value, idempotency_key):
        self.calls.append(("create", session, value, idempotency_key))
        return StudentMutation.model_validate(
            KakaoStudentMutation(student=student(), replayed=False).model_dump(mode="json")
        )

    async def kakao_student_list(self, session, *, limit=50, cursor=None):
        self.calls.append(("list", session, limit, cursor))
        return StudentPage.model_validate(
            KakaoStudentPage(items=(student(),), next_cursor=None).model_dump(mode="json")
        )

    async def kakao_student_read(self, session, student_id, *, display_revision_id=None):
        self.calls.append(("read", session, student_id, display_revision_id))
        return Student.model_validate(student().model_dump(mode="json"))

    async def kakao_student_command(self, session, student_id, value, idempotency_key, if_match):
        self.calls.append(("command", session, student_id, value, idempotency_key, if_match))
        successor = student(
            retired=isinstance(value, StudentRetire), renamed=isinstance(value, StudentRename)
        )
        return StudentMutation.model_validate(
            KakaoStudentMutation(student=successor, replayed=False).model_dump(mode="json")
        )


def test_student_routes_use_existing_cookie_csrf_without_inventing_admin_requirement():
    gateway = StudentGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(ROOT).status_code == 401
        session = login(client)
        body = create_command().model_dump(mode="json")
        assert client.post(ROOT, json=body).status_code == 403
        assert not gateway.calls
        headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY}
        created = client.post(ROOT, json=body, headers=headers)
        assert created.status_code == 201, created.text
        assert created.headers["etag"] == '"v1"' and created.headers["cache-control"] == "no-store"
        assert gateway.calls[0][2].model_dump(mode="json") == body
        assert gateway.calls[0][3] == KEY
        assert gateway.calls[0][1].operator["operator_id"] == session["operator"]["operator_id"]
        assert client.get(ROOT, params={"limit": 1}).status_code == 200
        read = client.get(ROOT + "/" + STUDENT_ID, params={"display_revision_id": REVISION_ID})
        assert read.status_code == 200 and gateway.calls[-1][-1] == REVISION_ID
        response = client.post(
            ROOT + "/" + STUDENT_ID + "/commands",
            json=rename_command().model_dump(mode="json"),
            headers={**headers, "If-Match": '"v1"'},
        )
        assert response.status_code == 200 and response.headers["etag"] == '"v2"'
        assert gateway.calls[-1][-2:] == (KEY, '"v1"')


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["ADMIN"]),
        ("actor_id", "owner"),
        ("student_id", STUDENT_ID),
        ("display_name", "\n"),
    ],
)
def test_invalid_body_is_denied_before_gateway(field, value):
    gateway = StudentGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        response = client.post(
            ROOT,
            json={**create_command().model_dump(mode="json"), field: value},
            headers={"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY},
        )
        assert response.status_code == 422 and not gateway.calls


def test_mutation_requires_exact_etag_and_safe_revision_shape():
    gateway = StudentGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY}
        path = ROOT + "/" + STUDENT_ID + "/commands"
        body = retire_command().model_dump(mode="json")
        assert client.post(path, json=body, headers=headers).status_code == 422
        assert (
            client.post(path, json=body, headers={**headers, "If-Match": 'W/"v1"'}).status_code
            == 422
        )
        assert (
            client.get(
                ROOT + "/" + STUDENT_ID, params={"display_revision_id": "latest"}
            ).status_code
            == 422
        )
        assert not gateway.calls


@pytest.mark.anyio
async def test_gateway_through_actual_api_preserves_key_parent_identity_and_revision(
    student_api_fixture,
):
    api, owner, _ = student_api_fixture
    requests = []

    def transport(request):
        requests.append(request)
        response = api.request(
            request.method,
            str(request.url.copy_with(scheme="http", host="localhost")),
            headers={
                **{key: value for key, value in request.headers.items() if key != "host"},
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
        create = StudentCreate.model_validate(create_command().model_dump(mode="json"))
        for _ in range(2):
            assert (
                await gateway.kakao_student_create(_session(), create, KEY)
            ).student.student_id == STUDENT_ID
        assert requests[0].content == requests[1].content
        assert (
            requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"] == KEY
        )
        assert json.loads(requests[0].content) == create_command().model_dump(mode="json")
        assert owner.create_kakao_student.call_count == 2
        assert (
            await gateway.kakao_student_read(
                _session(), STUDENT_ID, display_revision_id=REVISION_ID
            )
        ).display_revision_id == REVISION_ID
        assert requests[-1].url.params["display_revision_id"] == REVISION_ID
        assert len((await gateway.kakao_student_list(_session(), limit=1)).items) == 1
        result = await gateway.kakao_student_command(
            _session(),
            STUDENT_ID,
            StudentRetire.model_validate(retire_command().model_dump(mode="json")),
            KEY,
            '"v1"',
        )
        assert result.student.state == "RETIRED" and requests[-1].headers["If-Match"] == '"v1"'
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["identity", "revision", "parent", "state", "page", "cursor"])
async def test_gateway_rejects_other_student_or_revision_or_page(case):
    value = student(retired=case in {"parent", "state"}).model_dump(mode="json")
    if case == "identity":
        value["student_id"] = "kakaostudent_" + "9" * 32
    elif case == "revision":
        value["display_revision_id"] = "kakaostudentrev_" + "9" * 32
    elif case == "parent":
        value["previous_revision_id"] = "kakaostudentrev_" + "9" * 32
    elif case == "state":
        value["state"] = "ACTIVE"
    data = {"student": value, "replayed": False} if case in {"parent", "state"} else value
    if case in {"page", "cursor"}:
        data = {"items": [value, value] if case == "page" else [value], "next_cursor": None}
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(data)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            if case in {"parent", "state"}:
                await gateway.kakao_student_command(
                    _session(),
                    STUDENT_ID,
                    StudentRetire.model_validate(retire_command().model_dump(mode="json")),
                    KEY,
                    '"v1"',
                )
            elif case in {"page", "cursor"}:
                await gateway.kakao_student_list(
                    _session(), cursor=STUDENT_ID if case == "cursor" else None
                )
            else:
                await gateway.kakao_student_read(
                    _session(), STUDENT_ID, display_revision_id=REVISION_ID
                )
    finally:
        await gateway.close()
