"""Composition transport validates real actor, exact inputs, outputs and errors."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_question_compose_rpc import (
    ComposeKakaoQuestionsReply,
    ComposeKakaoQuestionsRequest,
    check_kakao_compose_reply,
    parse_kakao_compose_reply,
    parse_kakao_compose_request,
)
from eom_catalog_contracts.kakao_question_composition import KakaoQuestionSplit
from eom_catalog_contracts.kakao_question_composition_result import KakaoQuestionCompositionResult
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_question_compose_dispatch import dispatch_kakao_compose
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_kakao_question_composition_result import payload
from tests.unit.test_kakao_question_rpc import IDENTITY


def request():
    result = payload()
    return ComposeKakaoQuestionsRequest.model_validate(
        {
            **IDENTITY,
            "idempotency_key": "question-compose-fixture-001",
            "command": KakaoQuestionSplit(
                source_binding_id=result["source_binding_id"],
                room_id=result["room_id"],
                input=result["inputs"][0],
                partitions=(
                    ({"kind": "BLOCK", "block_id": "first"},),
                    ({"kind": "BLOCK", "block_id": "second"},),
                ),
            ),
        }
    )


def test_wire_schema_and_actor_dispatch_pin_exact_command():
    entry = CATALOG_SCHEMA_RESOURCES["catalog-kakao-question-compose-v1"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    command, owner = request(), Mock()
    owner.compose_questions.return_value = KakaoQuestionCompositionResult.model_validate(payload())
    reply = parse_kakao_compose_reply(
        json.loads(dispatch_kakao_compose(owner, command.model_dump(mode="json")))
    )
    check_kakao_compose_reply(command, reply)
    actor, selected = owner.compose_questions.call_args.args
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions
    assert actor.session_id == IDENTITY["session_id"] and selected == command.command
    assert parse_kakao_compose_request(command.model_dump(mode="json")) == command
    assert canonical_json_bytes(reply.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault", ["actor", "path", "latest", "version", "text", "empty", "operation"]
)
def test_bad_wire_input_never_reaches_owner(fault):
    body, owner = request().model_dump(mode="json"), Mock()
    if fault == "actor":
        body["permissions"] = ["ADMIN"]
    elif fault == "path":
        body["command"]["source_path"] = "/private"
    elif fault == "latest":
        body["command"]["input"]["question_revision_id"] = "latest"
    elif fault == "version":
        body["command"]["input"]["resource_version"] = True
    elif fault == "text":
        body["command"]["text"] = "not source"
    elif fault == "empty":
        body["command"]["partitions"] = []
    else:
        body["operation"] = "READ_KAKAO_QUESTION"
    value = json.loads(dispatch_kakao_compose(owner, body))
    assert value["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    owner.compose_questions.assert_not_called()


@pytest.mark.parametrize("fault", ["request", "binding", "room", "inputs", "count"])
def test_unrelated_valid_response_cannot_pass_correlation(fault):
    command, body = request(), payload()
    if fault == "request":
        reply = ComposeKakaoQuestionsReply(request_id="other-request", result=body)
    else:
        if fault in {"binding", "room"}:
            field = "source_binding_id" if fault == "binding" else "room_id"
            body[field] = body[field].replace("00000001", "00000009")
            for output in body["outputs"]:
                output[field] = body[field]
        elif fault == "inputs":
            body["inputs"][0]["resource_version"] = 2
        else:
            body["outputs"].append(
                body["outputs"][1]
                | dict(
                    question_id="kakaoquestion_" + "9" * 32,
                    question_revision_id="kakaoquestionrev_" + "9" * 32,
                )
            )
        reply = ComposeKakaoQuestionsReply(request_id=command.request_id, result=body)
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_compose_reply(command, reply)


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("private text"), "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID"),
        (
            KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED"),
            "KAKAO_ARCHIVE_PRECONDITION_FAILED",
        ),
        (RuntimeError("private text"), "CATALOG_APPLICATION_INTERNAL_ERROR"),
    ],
)
def test_private_errors_are_sanitized(error, code):
    owner = Mock()
    owner.compose_questions.side_effect = error
    raw = dispatch_kakao_compose(owner, request().model_dump(mode="json"))
    assert json.loads(raw)["error_code"] == code and b"private text" not in raw


def test_missing_owner_and_unrelated_output_are_explicit_failures():
    body = request().model_dump(mode="json")
    assert (
        json.loads(dispatch_kakao_compose(None, body))["error_code"]
        == "CATALOG_APPLICATION_UNAVAILABLE"
    )
    owner = Mock()
    owner.compose_questions.return_value = KakaoQuestionCompositionResult.model_validate(
        payload()
    ).model_copy(update={"room_id": "kakaoroom_" + "9" * 32})
    assert (
        json.loads(dispatch_kakao_compose(owner, body))["error_code"]
        == "KAKAO_ARCHIVE_RESULT_INVALID"
    )
