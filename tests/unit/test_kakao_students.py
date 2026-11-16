"""Private directory contract and data shape tests, without database or login."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_students import (
    KakaoStudent,
    KakaoStudentCreate,
    KakaoStudentPage,
    KakaoStudentRename,
    student_display_sha256,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_student_models import (
    KakaoStudentCommandRecord,
    KakaoStudentDisplayRevisionRecord,
    KakaoStudentRecord,
)
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint


def student(**changes) -> KakaoStudent:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    value = dict(
        student_id="kakaostudent_" + uuid4().hex,
        display_revision_id="kakaostudentrev_" + uuid4().hex,
        previous_revision_id=None,
        resource_version=1,
        display_name="학생 이름",
        state="ACTIVE",
        sha256=student_display_sha256("학생 이름", "ACTIVE"),
        created_at=now,
        updated_at=now,
    )
    value.update(changes)
    return KakaoStudent.model_validate(value)


@pytest.mark.parametrize("name", ["홍길동", "동명이인", "학생 😀", "e\u0301", " 학생 "])
def test_names_are_display_values_not_identifiers(name: str) -> None:
    command = KakaoStudentCreate(display_name=name)
    validate_contract("kakao-student-directory-v1", command.model_dump(mode="json"))
    assert command.display_name == name
    first = student(display_name=name, sha256=student_display_sha256(name, "ACTIVE"))
    second = student(display_name=name, sha256=first.sha256)
    assert first.student_id != second.student_id
    assert first.display_revision_id != second.display_revision_id


@pytest.mark.parametrize("name", ["", " ", "\n", "x\x00y", "x\x7fy", "x" * 129])
def test_invalid_names_fail_before_side_effects(name: str) -> None:
    with pytest.raises(ValueError):
        KakaoStudentCreate(display_name=name)


@pytest.mark.parametrize("version", [True, 1.5, "1", 0, 2147483648])
def test_revision_cas_is_not_coerced(version: object) -> None:
    with pytest.raises(ValueError):
        KakaoStudentRename.model_validate(
            dict(
                parent_revision_id="kakaostudentrev_" + "a" * 32,
                expected_resource_version=version,
                display_name="학생",
            )
        )


def test_revision_and_content_hash_are_distinct() -> None:
    first = student()
    renamed = student(
        student_id=first.student_id,
        previous_revision_id=first.display_revision_id,
        resource_version=2,
        display_name="다른 표시",
        sha256=student_display_sha256("다른 표시", "ACTIVE"),
    )
    assert first.sha256 != renamed.sha256
    assert first.display_name == "학생 이름"
    assert renamed.previous_revision_id == first.display_revision_id
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        student(sha256="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="LINEAGE_INVALID"):
        student(resource_version=2)
    with pytest.raises(ValueError, match="LINEAGE_INVALID"):
        student(previous_revision_id=first.display_revision_id)


def test_current_page_is_bounded_unique_and_ordered() -> None:
    first, second = sorted((student(), student()), key=lambda x: x.student_id)
    page = KakaoStudentPage(items=(first, second), next_cursor=second.student_id)
    assert len(page.items) == 2
    for values in ((second, first), (first, first)):
        with pytest.raises(ValueError, match="PAGE_INVALID"):
            KakaoStudentPage(items=values, next_cursor=None)
    with pytest.raises(ValueError, match="PAGE_INVALID"):
        KakaoStudentPage(items=(first,), next_cursor=second.student_id)
    with pytest.raises(ValueError):
        KakaoStudentPage(items=(first,) * 101, next_cursor=None)


def test_request_hash_preserves_names_and_intent() -> None:
    first = KakaoStudentCreate(display_name="학생")
    assert kakao_command_sha256(first) == kakao_command_sha256(first)
    assert kakao_command_sha256(first) != kakao_command_sha256(
        KakaoStudentCreate(display_name=" 학생")
    )
    assert validate_kakao_idempotency_key("student-create-123456") == "student-create-123456"
    for invalid in ("short", "key with space 123456", "한글 식별자 테스트합니다", "a" * 129):
        with pytest.raises(ValueError, match="REQUEST_INVALID"):
            validate_kakao_idempotency_key(invalid)


def test_db_rows_only_have_small_metadata_and_composite_revision_guards() -> None:
    tables = (
        KakaoStudentRecord.__table__,
        KakaoStudentDisplayRevisionRecord.__table__,
        KakaoStudentCommandRecord.__table__,
    )
    assert not any(
        str(column.type).startswith(("JSON", "BLOB", "BYTEA", "TEXT"))
        for table in tables
        for column in table.columns
    )
    assert all(
        column.name not in {"body", "messages", "token", "password"}
        for table in tables
        for column in table.columns
    )
    unique_keys = {
        tuple(c.columns.keys()) for c in tables[0].constraints if isinstance(c, UniqueConstraint)
    }
    assert ("owner_operator_id", "student_id") in unique_keys
    revision_fk = next(
        c
        for c in tables[0].constraints
        if isinstance(c, ForeignKeyConstraint) and c.name == "fk_kakao_student_current"
    )
    assert tuple(revision_fk.column_keys) == ("student_id", "current_display_revision_id")
    assert revision_fk.deferrable and revision_fk.initially == "DEFERRED"
