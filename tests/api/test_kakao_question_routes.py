"""HTTP authorization, exact parent/version and safe public review surface."""

import json
import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_catalog_contracts.kakao_question_rpc import KAKAO_QUESTION_OPERATIONS
from eom_catalog_contracts.kakao_question_store import KakaoQuestionMutation, KakaoQuestionPage
from eom_catalog_service.kakao_question_composition import KakaoQuestionApplication
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication
from tests.api.test_kakao_room_routes import room_socket
from tests.unit.kakao_binding_fixtures import KEY
from tests.unit.test_kakao_question_rpc import stored_question, view

BASE = "/api/v1/kakao-archive/questions"
QUESTION = stored_question()
PARAMS = {"source_binding_id": QUESTION.source_binding_id, "room_id": QUESTION.room_id}
READ_PATH = BASE + "/" + QUESTION.question_id + "/revisions/" + QUESTION.question_revision_id
REVIEW_PATH = BASE + "/" + QUESTION.question_id + "/review"
REVIEW = dict(
    schema_version="kakao-question-edit/1.0",
    action="CONFIRM",
    parent_revision_id=QUESTION.question_revision_id,
    reason="원문과 경계 확인\n사진도 확인",
    boundary_confirmed=True,
)


def confirmed():
    return QUESTION.model_copy(
        update={
            "question_revision_id": "kakaoquestionrev_" + "2" * 32,
            "previous_revision_id": QUESTION.question_revision_id,
            "resource_version": 2,
            "review_state": "CONFIRMED",
        }
    )


@pytest.fixture
def question_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        list_kakao_questions=Mock(
            return_value=KakaoQuestionPage(items=(QUESTION,), next_cursor=None)
        ),
        read_kakao_question=Mock(return_value=view()),
        change_kakao_question=Mock(
            return_value=KakaoQuestionMutation(question=confirmed(), replayed=True)
        ),
        download_kakao_question_image=Mock(),
    )
    services.catalog_application, services.audit = catalog, Mock()
    app = create_app(services)
    state = SimpleNamespace(
        authentication=replace(_authentication(admin=False), permissions=frozenset(PermissionKey))
    )

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, catalog, state
    services.engine.dispose()


def test_reads_pin_revision_and_reviews_forward_same_parent_and_version(question_client):
    client, catalog, state = question_client
    assert client.get(BASE, params=PARAMS).status_code == 200
    result = client.get(READ_PATH, params={"source_binding_id": QUESTION.source_binding_id})
    assert result.status_code == 200 and result.headers["etag"] == '"v1"'
    assert catalog.read_kakao_question.call_args.args == (
        QUESTION.source_binding_id,
        None,
        QUESTION.question_id,
        QUESTION.question_revision_id,
    )
    headers = {"Idempotency-Key": KEY, "If-Match": '"v1"'}
    for _ in range(2):
        response = client.post(REVIEW_PATH, params=PARAMS, json=REVIEW, headers=headers)
        assert response.status_code == 200 and response.headers["etag"] == '"v2"'
        command = catalog.change_kakao_question.call_args.args[0]
        assert command.edit.reason == REVIEW["reason"] and command.expected_resource_version == 1
        assert catalog.change_kakao_question.call_args.kwargs["idempotency_key"] == KEY
    state.authentication = replace(
        state.authentication, permissions=frozenset({PermissionKey.KAKAO_ARCHIVE_READ})
    )
    count = catalog.change_kakao_question.call_count
    assert client.post(REVIEW_PATH, params=PARAMS, json=REVIEW, headers=headers).status_code == 403
    assert catalog.change_kakao_question.call_count == count
    state.authentication = replace(state.authentication, permissions=frozenset())
    assert client.get(READ_PATH, params=PARAMS).status_code == 403


@pytest.mark.parametrize(
    "case,status",
    [
        ("key", 400),
        ("etag", 428),
        ("weak", 412),
        ("room", 422),
        ("authority", 422),
        ("stamp", 422),
        ("latest", 422),
    ],
)
def test_bad_review_never_reaches_owner(question_client, case, status):
    client, catalog, _state = question_client
    headers, body, params = {"Idempotency-Key": KEY, "If-Match": '"v1"'}, dict(REVIEW), dict(PARAMS)
    if case == "key":
        del headers["Idempotency-Key"]
    elif case == "etag":
        del headers["If-Match"]
    elif case == "weak":
        headers["If-Match"] = 'W/"v1"'
    elif case == "room":
        del params["room_id"]
    elif case == "authority":
        body["actor_id"] = "operator_" + "9" * 32
    elif case == "stamp":
        body["quality_acceptance"] = {"accepted": True}
    else:
        body["parent_revision_id"] = "latest"
    assert client.post(REVIEW_PATH, params=params, json=body, headers=headers).status_code == status
    catalog.change_kakao_question.assert_not_called()


@pytest.mark.parametrize(
    "operation", sorted(KAKAO_QUESTION_OPERATIONS | {"COMPOSE_KAKAO_QUESTIONS"})
)
def test_chat_peer_cannot_read_or_mutate_private_questions(tmp_path, operation):
    with room_socket(tmp_path, api_peer=False) as (server, _room_owner):
        owner, reads = Mock(), Mock()
        server.kakao_questions = KakaoQuestionApplication(owner, reads)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps({"operation": operation}).encode() + b"\n")
            assert connection.recv(1024) == b""
        assert not owner.mock_calls and not reads.mock_calls
