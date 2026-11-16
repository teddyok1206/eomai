"""Private question storage wire/DDL invariants; no live source or model execution."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_question import KakaoQuestionConfirm
from eom_catalog_contracts.kakao_question_store import (
    KakaoQuestionChange,
    KakaoQuestionCreate,
    KakaoQuestionMutation,
    KakaoQuestionPage,
    KakaoStoredQuestion,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionCommandRecord,
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService  # noqa: F401
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from tests.unit.test_kakao_question_editing import identity, pointer, source


def create_payload():
    return dict(
        source_binding_id=identity("kakaobinding", 1),
        room_id=identity("kakaoroom", 1),
        source_revision_id=identity("kakaosourcerev", 1),
        candidate_ordinal=1,
        expected_mapping_revision_id=identity("kakaomappingrev", 1),
    )


def stored_payload():
    return dict(
        source_binding_id=identity("kakaobinding", 1),
        room_id=identity("kakaoroom", 1),
        question_id=identity("kakaoquestion", 1),
        question_revision_id=identity("kakaoquestionrev", 1),
        previous_revision_id=None,
        resource_version=1,
        manifest=pointer("eom://schemas/kakao-archive/question-manifest-v1/1.0", b"manifest"),
        review_state="UNREVIEWED",
        first_student_at_utc=None,
        student=None,
        created_at=datetime(2026, 11, 16, tzinfo=UTC),
    )


def test_new_question_contract_is_canonical_mirrored_and_not_an_authority_grant():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["kakao-question-store-v1"]
    assert (root / entry.canonical_path).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    create = KakaoQuestionCreate.model_validate(create_payload())
    change = KakaoQuestionChange(
        source_binding_id=create.source_binding_id,
        room_id=create.room_id,
        question_id=identity("kakaoquestion", 1),
        expected_resource_version=1,
        edit=KakaoQuestionConfirm(
            parent_revision_id=identity("kakaoquestionrev", 1),
            reason="원문 확인",
            boundary_confirmed=True,
        ),
    )
    stored = KakaoStoredQuestion.model_validate(stored_payload())
    for value in (
        create,
        change,
        stored,
        KakaoQuestionMutation(question=stored, replayed=False),
        KakaoQuestionPage(items=(stored,), next_cursor=None),
    ):
        validate_contract("kakao-question-store-v1", value.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_ordinal", True),
        ("candidate_ordinal", 0),
        ("candidate_ordinal", 100001),
        ("source_revision_id", "latest"),
        ("owner_operator_id", identity("operator", 2)),
        ("approved", True),
        ("source_path", "/private/source.csv"),
        ("raw_text", "private"),
        ("expected_mapping_revision_id", "latest"),
    ],
)
def test_create_rejects_authority_paths_and_unbounded_or_coerced_inputs(field, value):
    with pytest.raises(ValueError):
        KakaoQuestionCreate.model_validate(create_payload() | {field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_version": True},
        {"resource_version": 0},
        {"resource_version": 2},
        {"previous_revision_id": identity("kakaoquestionrev", 1)},
        {"review_state": "APPROVED"},
        {"created_at": datetime(2026, 11, 16)},
        {"manifest": pointer("wrong-schema", b"manifest")},
    ],
)
def test_stored_projection_requires_exact_revision_schema_and_utc(changes):
    with pytest.raises(ValueError):
        KakaoStoredQuestion.model_validate(stored_payload() | changes)


def test_page_cursor_and_membership_are_stable_not_latest_or_duplicate():
    one = KakaoStoredQuestion.model_validate(stored_payload())
    two = one.model_copy(update={"question_id": identity("kakaoquestion", 2)})
    for items, cursor in (
        ((two, one), None),
        ((one, one), None),
        ((one,), two.question_id),
        ((), one.question_id),
    ):
        with pytest.raises(ValueError):
            KakaoQuestionPage(items=items, next_cursor=cursor)


def test_question_records_have_only_bounded_small_metadata_and_compiling_constraints():
    for model in (KakaoQuestionRecord, KakaoQuestionCommandRecord, KakaoQuestionRevisionRecord):
        assert all(
            isinstance(column.type, (String, Integer, DateTime))
            for column in model.__table__.columns
        )
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect()))
        assert "JSON" not in ddl and "BYTEA" not in ddl
    names = {index.name for index in KakaoQuestionRecord.__table__.indexes}
    assert names == {"ix_kakao_question_page", "ix_kakao_question_binding_page"}
    constraint = next(
        item
        for item in KakaoQuestionRecord.__table__.foreign_key_constraints
        if item.name == "fk_kakao_question_current"
    )
    assert constraint.deferrable and constraint.initially == "DEFERRED"
    assert tuple(column.name for column in constraint.columns) == (
        "question_id",
        "current_revision_id",
        "resource_version",
    )


def test_source_fixture_keeps_occurrences_distinct_even_if_text_is_the_same():
    value = source(texts=("same", "same"), roles=("student", "student"))
    assert len(set(value.occurrence_ids.values())) == 2
