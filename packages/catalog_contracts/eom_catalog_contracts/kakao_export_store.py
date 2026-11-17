"""Small student PDF requests; no source bytes, font paths or caller execution authority."""

from typing import Annotated, Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import Field, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_packet_store import PacketId, PacketRevisionId
from .kakao_students import KakaoStudentId
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

ExportId = Annotated[str, Field(pattern=r"^kakaoexport_[0-9a-f]{32}$")]
ExportRevisionId = Annotated[str, Field(pattern=r"^kakaoexportrev_[0-9a-f]{32}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ExportState = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "NEEDS_LAYOUT_REVIEW"]
ExportLayoutPolicy = Literal["student-question-a4/1.0", "student-study-a4/1.0"]


def _validate_export_schema(resource: str, value: dict[str, object]) -> None:
    try:
        validate_contract(resource, value)
    except JsonSchemaError:
        # Schema exceptions include entire inputs; expose the owning boundary's stable code.
        raise ValueError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID") from None


class KakaoExportProfile(FrozenModel):
    renderer_release_sha256: Sha256
    font_sha256: Sha256
    font_size_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    layout_policy: ExportLayoutPolicy = "student-question-a4/1.0"

    @property
    def export_schema_version(self) -> Literal["kakao-export/1.0", "kakao-export/2.0"]:
        return (
            "kakao-export/2.0"
            if self.layout_policy == "student-study-a4/1.0"
            else "kakao-export/1.0"
        )

    @property
    def layout_schema_ref(self) -> str:
        return (
            "eom://schemas/kakao-archive/worker-study-layout/1.0"
            if self.layout_policy == "student-study-a4/1.0"
            else "eom://schemas/kakao-archive/worker-question-layout/1.0"
        )


class KakaoExportCreate(FrozenModel):
    schema_version: Literal["kakao-export-create/1.0"] = "kakao-export-create/1.0"
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: KakaoStudentId

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-export-store-v1", self.model_dump(mode="json"))
        return self


class KakaoExport(FrozenModel):
    schema_version: Literal["kakao-export/1.0", "kakao-export/2.0"] = "kakao-export/1.0"
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: KakaoStudentId
    export_id: ExportId
    profile: KakaoExportProfile
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    state: ExportState
    created_at: UtcDatetime
    completed_at: UtcDatetime | None
    export_revision_id: ExportRevisionId | None
    page_count: int = Field(strict=True, ge=0, le=200)
    pdf: ArtifactMemberPointer | None
    layout: ArtifactMemberPointer | None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,79}$")

    @model_validator(mode="after")
    def terminal_shape(self) -> Self:
        _validate_export_schema(
            "kakao-export-store-v2"
            if self.schema_version == "kakao-export/2.0"
            else "kakao-export-store-v1",
            self.model_dump(mode="json"),
        )
        terminal = self.state in {"COMPLETED", "FAILED", "NEEDS_LAYOUT_REVIEW"}
        if terminal != (self.completed_at is not None) or (
            self.completed_at is not None and self.completed_at < self.created_at
        ):
            raise ValueError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        if self.state == "COMPLETED":
            if (
                self.export_revision_id is None
                or self.page_count == 0
                or self.error_code is not None
                or self.pdf is None
                or self.layout is None
                or self.pdf.schema_ref != "eom://schemas/kakao-archive/question-pdf/1.0"
                or self.pdf.media_type != "application/pdf"
                or self.pdf.member_path != "report.pdf"
                or self.layout.schema_ref != self.profile.layout_schema_ref
                or self.layout.media_type != "application/json"
                or self.layout.member_path != "layout.json"
                or (self.pdf.artifact_id, self.pdf.artifact_revision_id)
                != (self.layout.artifact_id, self.layout.artifact_revision_id)
            ):
                raise ValueError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        elif (
            self.export_revision_id is not None
            or self.pdf is not None
            or self.layout is not None
            or self.page_count != 0
            or terminal != (self.error_code is not None)
        ):
            raise ValueError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        return self


class KakaoExportMutation(FrozenModel):
    schema_version: Literal["kakao-export-mutation/1.0", "kakao-export-mutation/2.0"] = (
        "kakao-export-mutation/1.0"
    )
    export: KakaoExport
    replayed: bool = Field(strict=True)

    @classmethod
    def for_export(cls, export: KakaoExport, *, replayed: bool) -> Self:
        return cls(
            schema_version="kakao-export-mutation/2.0"
            if export.schema_version == "kakao-export/2.0"
            else "kakao-export-mutation/1.0",
            export=export,
            replayed=replayed,
        )

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        _validate_export_schema(
            "kakao-export-store-v2"
            if self.schema_version == "kakao-export-mutation/2.0"
            else "kakao-export-store-v1",
            self.model_dump(mode="json"),
        )
        return self


class KakaoExportPage(FrozenModel):
    schema_version: Literal["kakao-export-page/1.0", "kakao-export-page/2.0"] = (
        "kakao-export-page/1.0"
    )
    items: tuple[KakaoExport, ...] = Field(max_length=100)
    next_cursor: ExportId | None

    @classmethod
    def for_items(cls, items: tuple[KakaoExport, ...], *, next_cursor: str | None) -> Self:
        return cls(
            schema_version="kakao-export-page/2.0"
            if any(item.schema_version == "kakao-export/2.0" for item in items)
            else "kakao-export-page/1.0",
            items=items,
            next_cursor=next_cursor,
        )

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        _validate_export_schema(
            "kakao-export-store-v2"
            if self.schema_version == "kakao-export-page/2.0"
            else "kakao-export-store-v1",
            self.model_dump(mode="json"),
        )
        ids = tuple(item.export_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_ARCHIVE_EXPORT_PAGE_INVALID")
        return self
