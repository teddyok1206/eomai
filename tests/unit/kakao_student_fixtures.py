"""Synthetic stable identities for the private student transport tests."""

from datetime import UTC, datetime

from eom_catalog_contracts.kakao_students import (
    KakaoStudent,
    KakaoStudentCreate,
    KakaoStudentRename,
    KakaoStudentRetire,
    student_display_sha256,
)

NOW = datetime(2026, 11, 16, tzinfo=UTC)
STUDENT_ID = "kakaostudent_" + "1" * 32
REVISION_ID = "kakaostudentrev_" + "2" * 32
NEXT_REVISION_ID = "kakaostudentrev_" + "3" * 32
KEY = "student-fixture-intent-0001"


def student(*, retired=False, renamed=False):
    name = "합성 학생 새 이름" if renamed else "합성 학생"
    state = "RETIRED" if retired else "ACTIVE"
    changed = renamed or retired
    return KakaoStudent(
        student_id=STUDENT_ID,
        display_revision_id=NEXT_REVISION_ID if changed else REVISION_ID,
        previous_revision_id=REVISION_ID if changed else None,
        resource_version=2 if changed else 1,
        display_name=name,
        state=state,
        sha256=student_display_sha256(name, state),
        created_at=NOW,
        updated_at=NOW,
    )


def create_command():
    return KakaoStudentCreate(display_name="합성 학생")


def rename_command():
    return KakaoStudentRename(
        parent_revision_id=REVISION_ID,
        expected_resource_version=1,
        display_name="합성 학생 새 이름",
    )


def retire_command():
    return KakaoStudentRetire(parent_revision_id=REVISION_ID, expected_resource_version=1)
