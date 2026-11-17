"""Frozen local materialization contracts, independent of source authorization."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, field_validator, model_validator

from .execution import FrozenModel as FrozenModel
from .execution import WorkerExecution

RenderExecution = WorkerExecution

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
BindingId = Annotated[str, Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
PacketRevisionId = Annotated[str, Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")]
StudentId = Annotated[str, Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
QuestionRevisionId = Annotated[str, Field(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")]
AttachmentId = Annotated[str, Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")]
AttachmentRevisionId = Annotated[str, Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")]
ExportId = Annotated[str, Field(pattern=r"^kakaoexport_[0-9a-f]{32}$")]
MediaType = Literal[
    "application/json",
    "application/pdf",
    "font/otf",
    "font/ttf",
    "image/png",
    "image/jpeg",
    "image/webp",
]


class LocalMember(FrozenModel):
    relative_path: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9_-]+(?:[/.][A-Za-z0-9_-]+)*$", max_length=240)
    ]
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=64 * 1024 * 1024, strict=True)
    media_type: MediaType


class RenderText(FrozenModel):
    span_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=20000)


class RenderImageCrop(FrozenModel):
    left_ppm: int = Field(ge=0, le=1000000, strict=True)
    top_ppm: int = Field(ge=0, le=1000000, strict=True)
    right_ppm: int = Field(ge=0, le=1000000, strict=True)
    bottom_ppm: int = Field(ge=0, le=1000000, strict=True)

    @model_validator(mode="after")
    def positive_area(self) -> Self:
        if self.left_ppm >= self.right_ppm or self.top_ppm >= self.bottom_ppm:
            raise ValueError("KAKAO_RENDER_CROP_INVALID")
        return self


class RenderImageTransform(FrozenModel):
    transform_revision_id: Annotated[str, Field(pattern=r"^kakaotransformrev_[0-9a-f]{32}$")]
    operation_order: Literal["EXIF_THEN_ROTATE_THEN_CROP"]
    rotate_clockwise: Literal[0, 90, 180, 270]
    crop: RenderImageCrop | None

    @field_validator("rotate_clockwise", mode="before")
    @classmethod
    def strict_rotation(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("KAKAO_RENDER_ROTATION_INVALID")
        return value


class RenderTextReference(FrozenModel):
    kind: Literal["TEXT"]
    span_id: str = Field(min_length=1, max_length=128)


class RenderImageReference(FrozenModel):
    kind: Literal["IMAGE"]
    attachment_occurrence_id: AttachmentId


RenderBlockReference = Annotated[
    RenderTextReference | RenderImageReference, Field(discriminator="kind")
]


class RenderImage(FrozenModel):
    attachment_occurrence_id: AttachmentId
    attachment_revision_id: AttachmentRevisionId
    member: LocalMember | None
    availability: Literal["AVAILABLE", "MISSING", "UNRESOLVED", "EXPIRED"]
    quality_accepted: StrictBool
    transform: RenderImageTransform | None = None

    @model_validator(mode="after")
    def availability_matches_member(self) -> Self:
        if (self.availability == "AVAILABLE") != (self.member is not None):
            raise ValueError("KAKAO_RENDER_ATTACHMENT_STATE_INVALID")
        if self.member is not None and not self.member.media_type.startswith("image/"):
            raise ValueError("KAKAO_RENDER_IMAGE_TYPE_INVALID")
        if self.member is None and self.transform is not None:
            raise ValueError("KAKAO_RENDER_TRANSFORM_SOURCE_MISSING")
        return self


def validate_render_content(
    text_blocks: tuple[RenderText, ...],
    images: tuple[RenderImage, ...],
    ordered_blocks: tuple[RenderBlockReference, ...],
) -> None:
    """Shared content closure; v1 and study source/supplement values use the same rule."""
    if not text_blocks and not images:
        raise ValueError("KAKAO_RENDER_EMPTY_QUESTION")
    spans = [block.span_id for block in text_blocks]
    attachments = [image.attachment_occurrence_id for image in images]
    if len(set(spans)) != len(spans) or len(set(attachments)) != len(attachments):
        raise ValueError("KAKAO_RENDER_DUPLICATE_INPUT")
    if sum(len(block.text) for block in text_blocks) > 20000:
        raise ValueError("KAKAO_RENDER_TEXT_LIMIT")
    ordered_spans = [ref.span_id for ref in ordered_blocks if isinstance(ref, RenderTextReference)]
    ordered_images = [
        ref.attachment_occurrence_id
        for ref in ordered_blocks
        if isinstance(ref, RenderImageReference)
    ]
    if ordered_spans != spans or ordered_images != attachments:
        raise ValueError("KAKAO_RENDER_BLOCK_ORDER_INVALID")


class RenderQuestion(FrozenModel):
    question_revision_id: QuestionRevisionId
    header_date: date | None
    text_blocks: tuple[RenderText, ...] = Field(max_length=200)
    images: tuple[RenderImage, ...] = Field(max_length=30)
    ordered_blocks: tuple[RenderBlockReference, ...] = Field(min_length=1, max_length=230)

    @model_validator(mode="after")
    def content_complete(self) -> Self:
        validate_render_content(self.text_blocks, self.images, self.ordered_blocks)
        return self


class RenderManifest(FrozenModel):
    schema_version: Literal["kakao-question-render-manifest/1.0"]
    source_binding_id: BindingId
    packet_revision_id: PacketRevisionId
    student_id: StudentId
    student_display_name: str = Field(min_length=1, max_length=128)
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    questions: tuple[RenderQuestion, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def subset_matches(self) -> Self:
        revisions = tuple(question.question_revision_id for question in self.questions)
        if len(set(revisions)) != len(revisions) or subset_sha256(revisions) != self.subset_sha256:
            raise ValueError("KAKAO_RENDER_SUBSET_INVALID")
        if self.mode == "FINAL" and any(
            question.header_date is None for question in self.questions
        ):
            raise ValueError("KAKAO_RENDER_DATE_UNVERIFIED")
        return self


class RenderCommand(FrozenModel):
    execution: RenderExecution
    schema_version: Literal["kakao-question-render/1.0"]
    export_id: ExportId
    source_binding_id: BindingId
    packet_revision_id: PacketRevisionId
    student_id: StudentId
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    renderer_release_sha256: Sha256
    layout_policy: Literal["student-question-a4/1.0"]
    manifest: LocalMember
    font: LocalMember

    @model_validator(mode="after")
    def media_matches(self) -> Self:
        if self.manifest.media_type != "application/json" or self.font.media_type not in {
            "font/otf",
            "font/ttf",
        }:
            raise ValueError("KAKAO_RENDER_MEMBER_TYPE_INVALID")
        return self


class RenderResult(FrozenModel):
    execution: RenderExecution
    schema_version: Literal["kakao-question-render-result/1.0"]
    export_id: ExportId
    command_sha256: Sha256
    manifest_sha256: Sha256
    status: Literal["COMPLETED", "NEEDS_LAYOUT_REVIEW", "INVALID_INPUT"]
    page_count: int = Field(ge=0, le=200, strict=True)
    outputs: tuple[LocalMember, ...] = Field(max_length=202)
    error_code: str | None = Field(max_length=80)
    question_revision_id: QuestionRevisionId | None

    @model_validator(mode="after")
    def terminal_shape(self) -> Self:
        validate_render_result_shape(
            self.status, self.page_count, self.outputs, self.error_code, self.question_revision_id
        )
        return self


def validate_render_result_shape(
    status: str,
    page_count: int,
    outputs: tuple[LocalMember, ...],
    error_code: str | None,
    question_revision_id: str | None,
) -> None:
    """Terminal file closure shared across explicitly different render families."""
    if status == "COMPLETED":
        if error_code is not None or question_revision_id is not None or page_count == 0:
            raise ValueError("KAKAO_RENDER_RESULT_INVALID")
        if len(outputs) != page_count + 2:
            raise ValueError("KAKAO_RENDER_RESULT_MEMBERS_INVALID")
        expected = {"report.pdf": "application/pdf", "layout.json": "application/json"}
        expected.update({f"page-{i:04d}.png": "image/png" for i in range(1, page_count + 1)})
        actual = {member.relative_path: member.media_type for member in outputs}
        if len(actual) != len(outputs) or actual != expected:
            raise ValueError("KAKAO_RENDER_RESULT_MEMBERS_INVALID")
    elif outputs or page_count or error_code is None:
        raise ValueError("KAKAO_RENDER_FAILED_OUTPUT_INVALID")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def subset_sha256(question_revision_ids: tuple[str, ...]) -> str:
    return sha256(canonical_bytes(question_revision_ids))


def render_input_members(
    command: RenderCommand, manifest: RenderManifest
) -> tuple[LocalMember, ...]:
    """Exact local closure; shared by worker and owner, with a bounded total byte budget."""
    for field in ("source_binding_id", "packet_revision_id", "student_id", "subset_sha256", "mode"):
        if getattr(command, field) != getattr(manifest, field):
            raise ValueError("KAKAO_RENDER_MANIFEST_IDENTITY_MISMATCH")
    members = {command.manifest.relative_path: command.manifest}
    if members.setdefault(command.font.relative_path, command.font) != command.font:
        raise ValueError("KAKAO_RENDER_MEMBER_COLLISION")
    for question in manifest.questions:
        for image in question.images:
            if (
                image.member is not None
                and members.setdefault(image.member.relative_path, image.member) != image.member
            ):
                raise ValueError("KAKAO_RENDER_MEMBER_COLLISION")
    if sum(member.size_bytes for member in members.values()) > 256 * 1024 * 1024:
        raise ValueError("KAKAO_RENDER_INPUT_BYTES_EXCEEDED")
    return tuple(members.values())
