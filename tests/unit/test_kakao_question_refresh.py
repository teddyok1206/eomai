"""Additive refresh contract and pure new-review revision; no live collection."""

from datetime import timedelta
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_question import KakaoDisplayOverride, KakaoQuestionEdit
from eom_catalog_contracts.kakao_question_refresh import (
    KakaoQuestionSourceRefresh,
    RefreshKakaoQuestionSourceFailure,
    RefreshKakaoQuestionSourceReply,
    RefreshKakaoQuestionSourceRequest,
    check_refresh_reply,
    parse_refresh_reply,
    parse_refresh_request,
)
from eom_catalog_contracts.kakao_question_store import KakaoQuestionMutation, KakaoStoredQuestion
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_question_editing import (
    edit_question,
    question_from_refreshed_source,
    resolve_question_text,
    validate_question_sources,
)

from tests.unit.test_kakao_question_editing import ACTOR, NOW, identity, question, source
from tests.unit.test_kakao_question_store_contracts import stored_payload


def command_payload():
    return dict(
        source_binding_id=identity("kakaobinding", 1),
        room_id=identity("kakaoroom", 1),
        question_id=identity("kakaoquestion", 1),
        parent_revision_id=identity("kakaoquestionrev", 1),
        expected_resource_version=1,
        expected_mapping_revision_id=identity("kakaomappingrev", 1),
        source_revision_id=identity("kakaosourcerev", 2),
        candidate_ordinal=1,
        replace_display_edits=True,
    )


def test_refresh_schema_is_mirrored_and_explicit_not_a_content_authority():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["kakao-question-source-refresh-v1"]
    assert (root / entry.canonical_path).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    value = KakaoQuestionSourceRefresh.model_validate(command_payload())
    validate_contract("kakao-question-source-refresh-v1", value.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("replace_display_edits", False),
        ("replace_display_edits", 1),
        ("replace_display_edits", "true"),
        ("expected_resource_version", True),
        ("expected_resource_version", 0),
        ("candidate_ordinal", 0),
        ("candidate_ordinal", True),
        ("parent_revision_id", "latest"),
        ("source_revision_id", "latest"),
        ("owner_operator_id", identity("operator", 2)),
        ("source_path", "/private/source.csv"),
        ("source_pointer", {}),
        ("raw_text", "untrusted"),
    ],
)
def test_refresh_rejects_unconfirmed_authority_or_implicit_latest(field, value):
    with pytest.raises(ValueError):
        KakaoQuestionSourceRefresh.model_validate(command_payload() | {field: value})


def test_refresh_acknowledgement_cannot_be_omitted():
    payload = command_payload()
    del payload["replace_display_edits"]
    with pytest.raises(ValueError):
        KakaoQuestionSourceRefresh.model_validate(payload)


def test_refreshed_question_keeps_old_edits_and_links_a_new_unreviewed_revision():
    old = source(texts=("original question",), roles=("student",))
    original = question(old)
    edited = edit_question(
        original,
        KakaoQuestionEdit(
            parent_revision_id=original.question_revision_id,
            student=original.student,
            ordered_blocks=(
                original.ordered_blocks[0].model_copy(
                    update={
                        "display_override": KakaoDisplayOverride(
                            text="manual display", reason="reviewed"
                        ),
                    }
                ),
            ),
            selection_exclusions=(),
        ),
        question_revision_id=identity("kakaoquestionrev", 2),
        actor_id=ACTOR,
        created_at=NOW + timedelta(seconds=1),
        sources=(old,),
    )
    new = source(texts=("original question", "later reply"), roles=("student", "staff"), number=2)
    refreshed = question_from_refreshed_source(
        edited,
        new,
        new.candidates[1],
        question_revision_id=identity("kakaoquestionrev", 3),
        actor_id=ACTOR,
        created_at=NOW + timedelta(seconds=2),
    )
    validate_question_sources(refreshed, (new,))
    assert refreshed.question_id == edited.question_id
    assert refreshed.previous_revision_id == edited.question_revision_id
    assert refreshed.provenance[0].question_revision_id == edited.question_revision_id
    assert refreshed.review_state == "UNREVIEWED" and refreshed.review_decision is None
    assert resolve_question_text(edited.ordered_blocks[0], old) == "manual display"
    assert tuple(resolve_question_text(block, new) for block in refreshed.ordered_blocks) == (
        "original question",
        "later reply",
    )
    assert all(block.display_override is None for block in refreshed.ordered_blocks)


def test_refresh_cannot_reuse_revision_or_cross_room():
    old = question()
    for new_source, revision in (
        (source(number=2), old.question_revision_id),
        (source(number=2, room=2), identity("kakaoquestionrev", 3)),
    ):
        with pytest.raises(ValueError, match="SELECTION_INVALID"):
            question_from_refreshed_source(
                old,
                new_source,
                new_source.candidates[1],
                question_revision_id=revision,
                actor_id=ACTOR,
                created_at=NOW + timedelta(seconds=1),
            )


def request_reply():
    command = KakaoQuestionSourceRefresh.model_validate(command_payload())
    request = parse_refresh_request(
        RefreshKakaoQuestionSourceRequest(
            actor_id=ACTOR,
            session_id=identity("apisession", 1),
            request_id="request-refresh-001",
            authentication_time=NOW,
            command=command,
            idempotency_key="refresh-fixture-001",
        ).model_dump(mode="json")
    )
    result = KakaoStoredQuestion.model_validate(
        stored_payload()
        | {
            "question_revision_id": identity("kakaoquestionrev", 2),
            "previous_revision_id": command.parent_revision_id,
            "resource_version": 2,
        }
    )
    reply = parse_refresh_reply(
        RefreshKakaoQuestionSourceReply(
            request_id=request.request_id,
            result=KakaoQuestionMutation(question=result, replayed=False),
        ).model_dump(mode="json")
    )
    return request, reply


def test_refresh_wire_validates_exact_parent_and_failure_without_content():
    request, reply = request_reply()
    check_refresh_reply(request, reply)
    failure = parse_refresh_reply(
        RefreshKakaoQuestionSourceFailure(
            request_id=request.request_id,
            error_code="KAKAO_ARCHIVE_SOURCE_ORDER_UNVERIFIED",
        ).model_dump(mode="json")
    )
    check_refresh_reply(request, failure)
    assert failure.result is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("room_id", identity("kakaoroom", 2)),
        ("question_id", identity("kakaoquestion", 2)),
        ("previous_revision_id", identity("kakaoquestionrev", 3)),
        ("resource_version", 3),
        ("review_state", "CONFIRMED"),
    ],
)
def test_refresh_reply_cannot_substitute_another_target_or_latest(field, value):
    request, reply = request_reply()
    changed = reply.model_copy(
        update={
            "result": reply.result.model_copy(
                update={
                    "question": reply.result.question.model_copy(update={field: value}),
                }
            ),
        }
    )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_refresh_reply(request, changed)
