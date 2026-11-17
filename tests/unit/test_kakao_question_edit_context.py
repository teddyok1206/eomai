"""New metadata family cannot reinterpret v1 reads or supply editing authority."""

import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_question_edit_context import (
    KakaoQuestionEditContext,
    KakaoTextEditRange,
    ReadKakaoQuestionEditContext,
)
from eom_catalog_contracts.kakao_question_rpc import parse_kakao_question_request
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_question_dispatch import dispatch_kakao_question
from eom_identifiers import sha256_bytes
from jsonschema.exceptions import ValidationError

from tests.unit.test_kakao_question_rpc import request, stored_question


def edit_request():
    return ReadKakaoQuestionEditContext.model_validate(
        request().model_dump(mode="json") | {"operation": "READ_KAKAO_QUESTION_EDIT_CONTEXT"}
    )


def context():
    question = stored_question()
    return KakaoQuestionEditContext(
        source_binding_id=question.source_binding_id,
        room_id=question.room_id,
        question_id=question.question_id,
        question_revision_id=question.question_revision_id,
        resource_version=question.resource_version,
        text_blocks=(
            KakaoTextEditRange(
                block_id="text-1", can_split=True, start_codepoint=7, end_codepoint=16
            ),
        ),
    )


def dispatch(value, reads=None):
    output = io.BytesIO()
    dispatch_kakao_question(None, reads, value, output)
    return json.loads(output.getvalue())


def test_new_family_mirror_hash_and_old_parser_rejection():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["kakao-question-edit-context-v1"]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert KakaoQuestionEditContext.model_validate_json(context().model_dump_json()) == context()
    with pytest.raises((ValueError, ValidationError)):
        parse_kakao_question_request(edit_request().model_dump(mode="json"))


def test_exact_metadata_uses_actual_actor_without_asserted_permissions():
    reads = Mock()
    reads.read_edit_context.return_value = context()
    result = dispatch(edit_request().model_dump(mode="json"), reads)
    assert result["status"] == "OK" and result["result"] == context().model_dump(mode="json")
    actor, *_ = reads.read_edit_context.call_args.args
    assert actor.operator_id == edit_request().actor_id and not actor.permissions
    assert "pointer" not in json.dumps(result) and "private question" not in json.dumps(result)


@pytest.mark.parametrize(
    "key,value", [("roles", ["ADMIN"]), ("path", "/private"), ("question_revision_id", "latest")]
)
def test_untrusted_input_does_not_reach_owner(key, value):
    reads = Mock()
    result = dispatch(edit_request().model_dump(mode="json") | {key: value}, reads)
    assert result["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not reads.mock_calls


@pytest.mark.parametrize(
    "field,prefix",
    [
        ("source_binding_id", "kakaobinding"),
        ("room_id", "kakaoroom"),
        ("question_id", "kakaoquestion"),
        ("question_revision_id", "kakaoquestionrev"),
    ],
)
def test_foreign_result_is_not_returned(field, prefix):
    reads = Mock()
    reads.read_edit_context.return_value = context().model_copy(
        update={field: prefix + "_" + "9" * 32}
    )
    result = dispatch(edit_request().model_dump(mode="json"), reads)
    assert result["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and result["result"] is None


@pytest.mark.parametrize(
    "change",
    [dict(start_codepoint=16), dict(can_split=False), dict(can_split=1), dict(end_codepoint=None)],
)
def test_invalid_or_unavailable_ranges_cannot_supply_source_offsets(change):
    item = context().text_blocks[0].model_dump(mode="json") | change
    with pytest.raises(ValueError):
        KakaoTextEditRange.model_validate(item)


def test_optional_runtime_is_explicitly_unavailable():
    result = dispatch(edit_request().model_dump(mode="json"))
    assert result["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
