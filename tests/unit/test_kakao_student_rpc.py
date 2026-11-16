"""Student RPC strict shape/correlation and dispatch through the public owner service."""

import json
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_student_rpc import (
    CommandKakaoStudentReply,
    CommandKakaoStudentRequest,
    CreateKakaoStudentRequest,
    ListKakaoStudentsReply,
    ListKakaoStudentsRequest,
    ReadKakaoStudentRequest,
    check_kakao_student_reply,
    parse_kakao_student_reply,
    parse_kakao_student_request,
)
from eom_catalog_contracts.kakao_students import KakaoStudentMutation, KakaoStudentPage
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_student_dispatch import dispatch_kakao_student
from eom_catalog_service.kakao_student_service import KakaoStudentService
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.kakao_student_fixtures import (
    KEY,
    NOW,
    REVISION_ID,
    STUDENT_ID,
    create_command,
    rename_command,
    retire_command,
    student,
)

IDENTITY = {
    "actor_id": "operator_" + "4" * 32,
    "session_id": "apisession_" + "5" * 32,
    "request_id": "webreq_student_fixture",
    "authentication_time": NOW,
}


def create_request():
    return CreateKakaoStudentRequest(**IDENTITY, idempotency_key=KEY, command=create_command())


@pytest.mark.parametrize("action", ["create", "read", "pinned-read", "list", "rename", "retire"])
def test_dispatch_exact_request_uses_owner_service_with_no_authority_claims(action):
    service = Mock(spec=KakaoStudentService)
    if action == "create":
        request = create_request()
        method = service.create_student
        method.return_value = KakaoStudentMutation(student=student(), replayed=False)
    elif action in {"read", "pinned-read"}:
        request = ReadKakaoStudentRequest(
            **IDENTITY,
            student_id=STUDENT_ID,
            display_revision_id=REVISION_ID if action == "pinned-read" else None,
        )
        method = service.get_student
        method.return_value = student()
    elif action == "list":
        request = ListKakaoStudentsRequest(**IDENTITY)
        method = service.list_students
        method.return_value = KakaoStudentPage(items=(student(),), next_cursor=None)
    else:
        request = CommandKakaoStudentRequest(
            **IDENTITY,
            student_id=STUDENT_ID,
            idempotency_key=KEY,
            command=rename_command() if action == "rename" else retire_command(),
        )
        method = service.command_student
        method.return_value = KakaoStudentMutation(
            student=student(renamed=action == "rename", retired=action == "retire"), replayed=True
        )
    reply = parse_kakao_student_reply(
        json.loads(dispatch_kakao_student(service, request.model_dump(mode="json")))
    )
    assert reply.status == "OK"
    check_kakao_student_reply(request, reply)
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and actor.session_id == IDENTITY["session_id"]
    assert not actor.permissions
    if action in {"create", "rename", "retire"}:
        assert method.call_args.kwargs["idempotency_key"] == KEY
    if action == "pinned-read":
        assert method.call_args.kwargs["display_revision_id"] == REVISION_ID


@pytest.mark.parametrize(
    "field,value", [("roles", ["ADMIN"]), ("permissions", ["WRITE"]), ("profile_path", "/private")]
)
def test_authority_or_source_paths_rejected_before_owner(field, value):
    service = Mock(spec=KakaoStudentService)
    value = {**create_request().model_dump(mode="json"), field: value}
    result = json.loads(dispatch_kakao_student(service, value))
    assert result["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert service.mock_calls == []


@pytest.mark.parametrize("limit", [True, "10", 0, 101])
def test_list_limits_are_strict(limit):
    value = ListKakaoStudentsRequest(**IDENTITY).model_dump(mode="json")
    value["limit"] = limit
    with pytest.raises((ValidationError, SchemaError)):
        parse_kakao_student_request(value)


def test_service_unavailable_and_private_errors_are_redacted():
    value = create_request().model_dump(mode="json")
    assert (
        json.loads(dispatch_kakao_student(None, value))["error_code"]
        == "CATALOG_APPLICATION_UNAVAILABLE"
    )
    service = Mock(spec=KakaoStudentService)
    for error in [KakaoArchiveError("private name secret"), RuntimeError("private name secret")]:
        service.create_student.side_effect = error
        result = dispatch_kakao_student(service, value)
        assert b"private name secret" not in result
        assert json.loads(result)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"


@pytest.mark.parametrize("case", ["student", "revision", "request", "parent", "rename"])
def test_valid_but_unrelated_reply_is_rejected(case):
    service = Mock(spec=KakaoStudentService)
    if case in {"student", "revision", "request"}:
        request = ReadKakaoStudentRequest(
            **IDENTITY,
            student_id=STUDENT_ID,
            display_revision_id="kakaostudentrev_" + "9" * 32 if case == "revision" else None,
        )
        value = student()
        if case == "student":
            value = value.model_copy(update={"student_id": "kakaostudent_" + "9" * 32})
        service.get_student.return_value = value
        reply = parse_kakao_student_reply(
            json.loads(dispatch_kakao_student(service, request.model_dump(mode="json")))
        )
        if case == "request":
            reply = reply.model_copy(update={"request_id": "webreq_other"})
            with pytest.raises(ValueError, match="RESULT_INVALID"):
                check_kakao_student_reply(request, reply)
        else:
            assert reply.error_code == "KAKAO_ARCHIVE_RESULT_INVALID" and reply.result is None
    else:
        command = rename_command()
        if case == "parent":
            command = command.model_copy(
                update={"parent_revision_id": "kakaostudentrev_" + "9" * 32}
            )
        request = CommandKakaoStudentRequest(
            **IDENTITY, student_id=STUDENT_ID, idempotency_key=KEY, command=command
        )
        reply = CommandKakaoStudentReply(
            request_id=request.request_id,
            result=KakaoStudentMutation(student=student(renamed=case != "rename"), replayed=True),
        )
        with pytest.raises(ValueError, match="RESULT_INVALID"):
            check_kakao_student_reply(request, reply)


def test_page_rejects_values_before_cursor_and_wrong_page_length():
    request = ListKakaoStudentsRequest(**IDENTITY, cursor=STUDENT_ID, limit=2)
    page = KakaoStudentPage(items=(student(),), next_cursor=STUDENT_ID)
    reply = ListKakaoStudentsReply(request_id=request.request_id, result=page)
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_student_reply(request, reply)
