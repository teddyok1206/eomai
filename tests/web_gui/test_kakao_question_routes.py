"""Actual BFF/gateway shapes, CSRF, immutable parent and verified bounded media."""

import httpx
import pytest
from eom_catalog_contracts.kakao_question_composition_result import KakaoQuestionCompositionResult
from eom_catalog_contracts.kakao_question_store import KakaoQuestionMutation, KakaoQuestionPage
from eom_identifiers import sha256_bytes
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_question_contracts import (
    QuestionConfirm,
    QuestionMutation,
    QuestionPage,
    QuestionSplit,
    QuestionView,
)

from tests.api.test_kakao_question_routes import (
    PARAMS,
    QUESTION,
    REVIEW,
    confirmed,
)
from tests.api.test_kakao_question_routes import (
    question_client as question_client,
)
from tests.unit.kakao_binding_fixtures import KEY
from tests.unit.test_kakao_question_compose_rpc import request as composition_request
from tests.unit.test_kakao_question_composition_result import payload as composition_payload
from tests.unit.test_kakao_question_rpc import view
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway

BASE = "/studio/api/v1/kakao-archive/questions"
READ_PATH = BASE + "/" + QUESTION.question_id + "/revisions/" + QUESTION.question_revision_id
REVIEW_PATH = BASE + "/" + QUESTION.question_id + "/review"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault", [None, "binding", "input", "duplicate", "lifecycle", "student", "time"]
)
async def test_compose_gateway_checks_exact_scope_selection_and_output(fault):
    body = KakaoQuestionCompositionResult.model_validate(composition_payload()).model_dump(
        mode="json"
    )
    command = QuestionSplit.model_validate(composition_request().command.model_dump(mode="json"))
    calls = []
    if fault == "binding":
        body["source_binding_id"] = "kakaobinding_" + "9" * 32
    elif fault == "input":
        body["inputs"][0]["resource_version"] = 2
    elif fault == "duplicate":
        body["outputs"][1] = body["outputs"][0]
    elif fault == "lifecycle":
        body["outputs"][1]["review_state"] = "CONFIRMED"
    elif fault == "student":
        body["outputs"][1]["student"] = None
    elif fault == "time":
        body["outputs"][1]["created_at"] = "2026-11-16T00:00:01Z"

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=_single(body))

    gateway = http_gateway(transport)
    try:
        if fault is None:
            result = await gateway.kakao_question_compose(_session(), command, KEY)
            assert result.model_dump(mode="json") == body
        else:
            with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
                await gateway.kakao_question_compose(_session(), command, KEY)
        assert calls[0].headers["Idempotency-Key"] == KEY
        assert calls[0].url.path == "/api/v1/kakao-archive/questions/compose"
    finally:
        await gateway.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"


class QuestionGateway(FakeGateway):
    def __init__(self):
        super().__init__(roles=["VIEWER"])
        self.calls = []

    async def kakao_question_list(self, session, binding, **params):
        self.calls.append(("list", binding, params))
        return QuestionPage.model_validate(
            KakaoQuestionPage(items=(QUESTION,), next_cursor=None).model_dump(mode="json")
        )

    async def kakao_question_read(self, session, binding, room, question, revision):
        self.calls.append(("read", binding, room, question, revision))
        return QuestionView.model_validate(view().model_dump(mode="json"))

    async def kakao_question_review(self, session, binding, room, question, value, key, etag):
        self.calls.append(("review", binding, room, question, value, key, etag))
        return QuestionMutation.model_validate(
            KakaoQuestionMutation(question=confirmed(), replayed=True).model_dump(mode="json")
        )


def test_cookie_csrf_review_etag_and_optional_exact_room():
    gateway = QuestionGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(BASE, params=PARAMS).status_code == 401
        session = login(client)
        assert client.post(REVIEW_PATH, params=PARAMS, json=REVIEW).status_code == 403
        assert not gateway.calls
        result = client.get(READ_PATH, params={"source_binding_id": QUESTION.source_binding_id})
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        assert gateway.calls[-1][2] is None
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": KEY,
            "If-Match": '"v1"',
        }
        result = client.post(REVIEW_PATH, params=PARAMS, json=REVIEW, headers=headers)
        assert result.status_code == 200 and result.headers["etag"] == '"v2"'
        assert gateway.calls[-1][-2:] == (KEY, '"v1"')
        assert gateway.calls[-1][-3].reason == REVIEW["reason"]
        before = len(gateway.calls)
        assert (
            client.post(
                REVIEW_PATH, params=PARAMS, json={**REVIEW, "accepted_by": "ADMIN"}, headers=headers
            ).status_code
            == 422
        )
        assert len(gateway.calls) == before


@pytest.mark.anyio
async def test_real_gateway_to_api_preserves_exact_question_review_and_replay(question_client):
    api, owner, _state = question_client
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
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    gateway = http_gateway(transport)
    try:
        binding, room, question, revision = (
            QUESTION.source_binding_id,
            QUESTION.room_id,
            QUESTION.question_id,
            QUESTION.question_revision_id,
        )
        assert (
            await gateway.kakao_question_read(_session(), binding, None, question, revision)
        ).question.question_revision_id == revision
        assert "room_id" not in requests[-1].url.params
        assert (
            len((await gateway.kakao_question_list(_session(), binding, room_id=room)).items) == 1
        )
        for _ in range(2):
            result = await gateway.kakao_question_review(
                _session(),
                binding,
                room,
                question,
                QuestionConfirm.model_validate(REVIEW),
                KEY,
                '"v1"',
            )
            assert result.question.review_state == "CONFIRMED" and result.replayed
        assert requests[-1].content == requests[-2].content
        assert (
            requests[-1].headers["Idempotency-Key"]
            == requests[-2].headers["Idempotency-Key"]
            == KEY
        )
        assert owner.change_kakao_question.call_count == 2
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        "binding",
        "room",
        "question",
        "revision",
        "duplicate",
        "cursor",
        "review-parent",
        "review-state",
    ],
)
async def test_other_scope_reply_is_never_accepted(case):
    data = view().model_dump(mode="json")
    fields = {
        "binding": ("source_binding_id", "kakaobinding"),
        "room": ("room_id", "kakaoroom"),
        "question": ("question_id", "kakaoquestion"),
        "revision": ("question_revision_id", "kakaoquestionrev"),
    }
    if case in fields:
        field, prefix = fields[case]
        data["question"][field] = prefix + "_" + "9" * 32
    elif case in {"duplicate", "cursor"}:
        data = KakaoQuestionPage(items=(QUESTION,), next_cursor=None).model_dump(mode="json")
        if case == "duplicate":
            data["items"].append(data["items"][0])
    else:
        data = KakaoQuestionMutation(question=confirmed(), replayed=False).model_dump(mode="json")
        data["question"]["previous_revision_id" if case == "review-parent" else "review_state"] = (
            "kakaoquestionrev_" + "9" * 32 if case == "review-parent" else "UNREVIEWED"
        )
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(data)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            if case in {"duplicate", "cursor"}:
                await gateway.kakao_question_list(
                    _session(),
                    QUESTION.source_binding_id,
                    cursor=QUESTION.question_id if case == "cursor" else None,
                )
            elif case.startswith("review-"):
                await gateway.kakao_question_review(
                    _session(),
                    QUESTION.source_binding_id,
                    QUESTION.room_id,
                    QUESTION.question_id,
                    QuestionConfirm.model_validate(REVIEW),
                    KEY,
                    '"v1"',
                )
            else:
                await gateway.kakao_question_read(
                    _session(),
                    QUESTION.source_binding_id,
                    QUESTION.room_id,
                    QUESTION.question_id,
                    QUESTION.question_revision_id,
                )
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["valid", "hash", "length", "magic", "disposition"])
async def test_image_is_verified_before_bff_releases_bytes(case):
    photo = b"\x89PNG\r\n\x1a\nsynthetic"
    headers = {
        "content-type": "image/png",
        "content-length": str(len(photo)),
        "content-disposition": "inline",
        "etag": '"' + sha256_bytes(photo) + '"',
    }
    if case == "hash":
        headers["etag"] = '"sha256:' + "0" * 64 + '"'
    elif case == "length":
        headers["content-length"] = str(len(photo) + 1)
    elif case == "magic":
        photo = b"untrusted bytes"
    elif case == "disposition":
        headers["content-disposition"] = "attachment"
    gateway = http_gateway(lambda _: httpx.Response(200, content=photo, headers=headers))
    try:

        async def read():
            return await gateway.kakao_question_image(
                _session(),
                QUESTION.source_binding_id,
                None,
                QUESTION.question_id,
                QUESTION.question_revision_id,
                "kakaoattachment_" + "1" * 32,
            )

        if case == "valid":
            result = await read()
            assert result.content_type == "image/png"
            assert result.content == photo
        else:
            with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
                await read()
    finally:
        await gateway.close()
