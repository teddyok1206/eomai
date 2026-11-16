"""Owner-private student identity independent of names and immutable display revisions."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import validate_kakao_display_name
from eom_catalog_contracts.kakao_archive_binding import KakaoResourceVersion
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

KakaoStudentId = Annotated[str, Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
KakaoStudentRevisionId = Annotated[str, Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")]
StudentState = Literal["ACTIVE", "RETIRED"]


def student_display_sha256(display_name: str, state: StudentState) -> str:
    payload = json.dumps(
        {"display_name": display_name, "state": state},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class KakaoStudentCreate(FrozenModel):
    schema_version: Literal["kakao-student-command/1.0"] = "kakao-student-command/1.0"
    action: Literal["CREATE"] = "CREATE"
    display_name: str = Field(min_length=1, max_length=128)

    _display_name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-student-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoStudentRename(FrozenModel):
    schema_version: Literal["kakao-student-command/1.0"] = "kakao-student-command/1.0"
    action: Literal["RENAME"] = "RENAME"
    parent_revision_id: KakaoStudentRevisionId
    expected_resource_version: KakaoResourceVersion
    display_name: str = Field(min_length=1, max_length=128)

    _display_name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-student-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoStudentRetire(FrozenModel):
    schema_version: Literal["kakao-student-command/1.0"] = "kakao-student-command/1.0"
    action: Literal["RETIRE"] = "RETIRE"
    parent_revision_id: KakaoStudentRevisionId
    expected_resource_version: KakaoResourceVersion

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-student-directory-v1", self.model_dump(mode="json"))
        return self


KakaoStudentCommand = Annotated[
    KakaoStudentRename | KakaoStudentRetire, Field(discriminator="action")
]


class KakaoStudent(FrozenModel):
    schema_version: Literal["kakao-student/1.0"] = "kakao-student/1.0"
    student_id: KakaoStudentId
    display_revision_id: KakaoStudentRevisionId
    previous_revision_id: KakaoStudentRevisionId | None
    resource_version: KakaoResourceVersion
    display_name: str = Field(min_length=1, max_length=128)
    state: StudentState
    sha256: Sha256
    created_at: UtcDatetime
    updated_at: UtcDatetime

    _display_name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-student-directory-v1", self.model_dump(mode="json"))
        if self.sha256 != student_display_sha256(self.display_name, self.state):
            raise ValueError("KAKAO_ARCHIVE_STUDENT_HASH_MISMATCH")
        if (
            (self.resource_version == 1) != (self.previous_revision_id is None)
            or self.previous_revision_id == self.display_revision_id
            or self.updated_at < self.created_at
        ):
            raise ValueError("KAKAO_ARCHIVE_STUDENT_LINEAGE_INVALID")
        return self


class KakaoStudentMutation(FrozenModel):
    student: KakaoStudent
    replayed: bool = Field(strict=True)


class KakaoStudentPage(FrozenModel):
    items: tuple[KakaoStudent, ...] = Field(max_length=100)
    next_cursor: KakaoStudentId | None

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        ids = tuple(item.student_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_ARCHIVE_STUDENT_PAGE_INVALID")
        return self
