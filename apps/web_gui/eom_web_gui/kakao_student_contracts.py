"""Student-directory browser DTOs; Catalog owns names, lifecycle, hashes and history."""

from typing import Annotated, Literal

from pydantic import Field

from eom_web_gui.contracts import UtcDatetime, WebModel
from eom_web_gui.kakao_archive_contracts import Label, ResourceVersion

StudentId = Annotated[str, Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
StudentRevisionId = Annotated[str, Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")]


class StudentCreate(WebModel):
    schema_version: Literal["kakao-student-command/1.0"]
    action: Literal["CREATE"]
    display_name: Label


class StudentRename(WebModel):
    schema_version: Literal["kakao-student-command/1.0"]
    action: Literal["RENAME"]
    parent_revision_id: StudentRevisionId
    expected_resource_version: ResourceVersion
    display_name: Label


class StudentRetire(WebModel):
    schema_version: Literal["kakao-student-command/1.0"]
    action: Literal["RETIRE"]
    parent_revision_id: StudentRevisionId
    expected_resource_version: ResourceVersion


StudentCommand = Annotated[StudentRename | StudentRetire, Field(discriminator="action")]


class Student(WebModel):
    schema_version: Literal["kakao-student/1.0"]
    student_id: StudentId
    display_revision_id: StudentRevisionId
    previous_revision_id: StudentRevisionId | None
    resource_version: ResourceVersion
    display_name: Label
    state: Literal["ACTIVE", "RETIRED"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StudentPage(WebModel):
    items: tuple[Student, ...] = Field(max_length=100)
    next_cursor: StudentId | None


class StudentMutation(WebModel):
    student: Student
    replayed: bool = Field(strict=True)
