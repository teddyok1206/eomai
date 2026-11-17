"""Candidate projections are bounded exact source reads, never collection authority."""

import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_question_candidates import (
    KakaoCandidateSummary,
    KakaoQuestionCandidatePage,
    ListKakaoQuestionCandidates,
)
from eom_catalog_contracts.kakao_question_rpc import parse_kakao_question_request
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_question_dispatch import dispatch_kakao_question
from eom_identifiers import sha256_bytes
from jsonschema.exceptions import ValidationError

from tests.unit.test_kakao_question_rpc import request, stored_question


def query():
    old = request().model_dump(mode="json")
    return ListKakaoQuestionCandidates.model_validate(
        {
            key: old[key]
            for key in (
                "actor_id",
                "session_id",
                "request_id",
                "authentication_time",
                "source_binding_id",
                "room_id",
            )
        }
    )


def page():
    stored = stored_question()
    return KakaoQuestionCandidatePage(
        source_binding_id=stored.source_binding_id,
        room_id=stored.room_id,
        source_revision_id="kakaosourcerev_" + "1" * 32,
        source_resolution_sha256="sha256:" + "a" * 64,
        mapping_revision_id="kakaomappingrev_" + "1" * 32,
        total_candidates=1,
        unknown_sender_rows=0,
        items=(
            KakaoCandidateSummary(
                candidate_ordinal=1,
                student_message_count=2,
                reply_message_count=0,
                photo_count=0,
                first_student_at_utc=None,
                preview="Synthetic private preview",
                boundary_uncertain=True,
                review_reasons=("SOURCE_SCOPE_UNVERIFIED",),
                saved_question=None,
                recomposed=False,
            ),
        ),
        next_after_ordinal=None,
    )


def dispatch(value, reads=None):
    output = io.BytesIO()
    dispatch_kakao_question(None, reads, value, output)
    return json.loads(output.getvalue())


def test_schema_mirror_identity_and_released_question_parser_unchanged():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["kakao-question-candidate-page-v1"]
    canonical = (root / resource.canonical_path).read_bytes()
    mirror = root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert sha256_bytes(canonical) == resource.sha256 and canonical == mirror.read_bytes()
    assert KakaoQuestionCandidatePage.model_validate_json(page().model_dump_json()) == page()
    with pytest.raises((ValueError, ValidationError)):
        parse_kakao_question_request(query().model_dump(mode="json"))


def test_actual_actor_without_claimed_permissions_and_one_owner_call():
    reads = Mock()
    reads.list_candidates.return_value = page()
    result = dispatch(query().model_dump(mode="json"), reads)
    assert result["status"] == "OK" and result["result"] == page().model_dump(mode="json")
    assert reads.list_candidates.call_count == 1
    actor = reads.list_candidates.call_args.args[0]
    assert actor.operator_id == query().actor_id and not actor.permissions


@pytest.mark.parametrize(
    "change",
    [
        {"after_ordinal": 1},
        {"limit": 101},
        {"limit": True},
        {"source_revision_id": "latest"},
        {"permissions": ["ADMIN"]},
        {"path": "/private"},
    ],
)
def test_invalid_pagination_or_asserted_authority_never_reaches_owner(change):
    reads = Mock()
    result = dispatch(query().model_dump(mode="json") | change, reads)
    assert result["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID" and not reads.mock_calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_binding_id", "kakaobinding_" + "9" * 32),
        ("room_id", "kakaoroom_" + "9" * 32),
        ("source_revision_id", "kakaosourcerev_" + "9" * 32),
    ],
)
def test_pinned_scope_cannot_be_substituted_in_reply(field, value):
    reads = Mock()
    reads.list_candidates.return_value = page().model_copy(update={field: value})
    pinned = query().model_copy(update={"source_revision_id": page().source_revision_id})
    result = dispatch(pinned.model_dump(mode="json"), reads)
    assert result["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and result["result"] is None


def test_empty_source_is_not_an_implicit_latest_or_ready_claim():
    value = page().model_dump(mode="json")
    value.update(
        source_revision_id=None, source_resolution_sha256=None, items=[], total_candidates=0
    )
    assert KakaoQuestionCandidatePage.model_validate(value).source_revision_id is None
    value["total_candidates"] = 1
    with pytest.raises(ValueError):
        KakaoQuestionCandidatePage.model_validate(value)


def test_superseded_origin_must_still_name_saved_question():
    with pytest.raises(ValueError):
        KakaoCandidateSummary.model_validate(
            page().items[0].model_dump(mode="json") | {"recomposed": True}
        )


def test_optional_runtime_unavailable_is_explicit():
    assert (
        dispatch(query().model_dump(mode="json"))["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
    )
