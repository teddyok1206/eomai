"""Closed API-only messages and exact read/image correlation, without private output leaks."""

import io
import json
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_question_rpc import (
    KakaoQuestionDisplayText,
    KakaoQuestionImageDescriptor,
    KakaoQuestionView,
    ListKakaoQuestionsRequest,
    ReadKakaoQuestionImageRequest,
    ReadKakaoQuestionRequest,
    parse_kakao_question_request,
)
from eom_catalog_contracts.kakao_question_store import KakaoQuestionPage, KakaoStoredQuestion
from eom_catalog_service.kakao_question_dispatch import dispatch_kakao_question
from eom_catalog_service.kakao_question_reads import KakaoOpenedQuestionImage
from eom_identifiers import sha256_bytes

from tests.unit.test_kakao_question_store_contracts import stored_payload

IDENTITY = dict(
    actor_id="operator_" + "4" * 32,
    session_id="apisession_" + "5" * 32,
    request_id="webreq_question_fixture",
    authentication_time="2026-11-16T00:00:00Z",
)


def stored_question():
    return KakaoStoredQuestion.model_validate(stored_payload())


def view():
    return KakaoQuestionView(
        question=stored_question(),
        ordered_blocks=(KakaoQuestionDisplayText(block_id="text-1", role="student", text="질문"),),
        review_reasons=(),
        boundary_uncertain=False,
    )


def request(*, image=False, room=True):
    q = stored_question()
    values = dict(
        **IDENTITY,
        source_binding_id=q.source_binding_id,
        room_id=q.room_id if room else None,
        question_id=q.question_id,
        question_revision_id=q.question_revision_id,
    )
    return (
        ReadKakaoQuestionImageRequest(**values, attachment_id="kakaoattachment_" + "1" * 32)
        if image
        else ReadKakaoQuestionRequest(**values)
    )


def dispatch(value, *, reads=None, questions=None):
    output = io.BytesIO()
    dispatch_kakao_question(questions, reads, value, output)
    return output.getvalue()


@pytest.mark.parametrize("room", [True, False])
def test_exact_read_and_optional_room_use_current_operator_without_claimed_permissions(room):
    reads, questions = Mock(), Mock()
    reads.read_question.return_value = view()
    command = request(room=room)
    result = json.loads(dispatch(command.model_dump(mode="json"), reads=reads, questions=questions))
    assert result["status"] == "OK" and result["result"] == view().model_dump(mode="json")
    actor, binding, room_id, question, revision = reads.read_question.call_args.args
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions
    assert (binding, room_id, question, revision) == (
        command.source_binding_id,
        command.room_id,
        command.question_id,
        command.question_revision_id,
    )


@pytest.mark.parametrize(
    "field,value", [("roles", ["ADMIN"]), ("path", "/private"), ("question_revision_id", "latest")]
)
def test_invalid_input_cannot_call_owner(field, value):
    reads, questions = Mock(), Mock()
    value = {**request().model_dump(mode="json"), field: value}
    result = json.loads(dispatch(value, reads=reads, questions=questions))
    assert result["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not reads.mock_calls and not questions.mock_calls


@pytest.mark.parametrize(
    "field,prefix",
    [
        ("source_binding_id", "kakaobinding"),
        ("room_id", "kakaoroom"),
        ("question_id", "kakaoquestion"),
        ("question_revision_id", "kakaoquestionrev"),
    ],
)
def test_other_question_scope_never_leaks_to_wire(field, prefix):
    reads, questions = Mock(), Mock()
    reads.read_question.return_value = view().model_copy(
        update={"question": stored_question().model_copy(update={field: prefix + "_" + "9" * 32})}
    )
    raw = dispatch(request().model_dump(mode="json"), reads=reads, questions=questions)
    assert json.loads(raw)["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID"
    assert "질문".encode() not in raw


def test_native_stream_closes_even_if_output_breaks_and_wrong_attachment_has_no_bytes():
    command, reads, questions = request(image=True), Mock(), Mock()
    photo = b"synthetic photo bytes"
    descriptor = KakaoQuestionImageDescriptor(
        **{
            key: getattr(command, key)
            for key in (
                "source_binding_id",
                "room_id",
                "question_id",
                "question_revision_id",
                "attachment_id",
            )
        },
        media_type="image/png",
        content_length=len(photo),
        sha256=sha256_bytes(photo),
    )
    for wrong in (False, True):
        stream = io.BytesIO(photo)
        member = Mock(stream=stream)
        member.iter_chunks.return_value = iter((photo,))
        reads.open_image.return_value = KakaoOpenedQuestionImage(
            descriptor.model_copy(update={"attachment_id": "kakaoattachment_" + "9" * 32})
            if wrong
            else descriptor,
            member,
        )
        raw = dispatch(command.model_dump(mode="json"), reads=reads, questions=questions)
        assert stream.closed
        if wrong:
            assert (
                photo not in raw and json.loads(raw)["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID"
            )
        else:
            assert raw.split(b"\n", 1)[1] == photo
    stream = io.BytesIO(photo)
    reads.open_image.return_value = KakaoOpenedQuestionImage(descriptor, Mock(stream=stream))
    broken = Mock()
    broken.write.side_effect = BrokenPipeError()
    with pytest.raises(BrokenPipeError):
        dispatch_kakao_question(questions, reads, command.model_dump(mode="json"), broken)
    assert stream.closed


def test_unavailable_owner_and_unexpected_errors_are_sanitized():
    value = request().model_dump(mode="json")
    assert json.loads(dispatch(value))["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
    reads = Mock()
    reads.read_question.side_effect = RuntimeError("private student token")
    raw = dispatch(value, reads=reads, questions=Mock())
    assert b"private student" not in raw
    assert json.loads(raw)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"


def test_page_reply_cannot_ignore_room_limit_or_cursor():
    q, questions, reads = stored_question(), Mock(), Mock()
    command = ListKakaoQuestionsRequest(
        **IDENTITY, source_binding_id=q.source_binding_id, cursor=q.question_id
    )
    questions.list_questions.return_value = KakaoQuestionPage(items=(q,), next_cursor=None)
    assert (
        json.loads(dispatch(command.model_dump(mode="json"), questions=questions, reads=reads))[
            "error_code"
        ]
        == "KAKAO_ARCHIVE_RESULT_INVALID"
    )
    assert parse_kakao_question_request(request(room=False).model_dump(mode="json")).room_id is None
