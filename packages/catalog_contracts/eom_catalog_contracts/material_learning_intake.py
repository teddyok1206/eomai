"""Source-only intake and actual uploader attestations; no model execution grant."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialKind,
    MaterialLearningUpload,
    SourceRole,
    require_material_rights_confirmation,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime, _safe_text
from eom_catalog_contracts.validation import validate_contract

MaterialSourceFormat = Literal["PDF", "HWP", "HWPX"]
MaterialOperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
MaterialIdempotencyKey = Annotated[str, Field(pattern=r"^[!-~]{16,128}$")]


@dataclass(frozen=True, slots=True)
class MaterialSourceFormatDescriptor:
    media_type: str
    suffix: str
    schema_ref: str


MATERIAL_SOURCE_FORMATS: Mapping[str, MaterialSourceFormatDescriptor] = MappingProxyType(
    {
        "PDF": MaterialSourceFormatDescriptor(
            "application/pdf", ".pdf", "eom://schemas/educational-document/pdf-source/1.0"
        ),
        "HWP": MaterialSourceFormatDescriptor(
            "application/vnd.hancom.hwp", ".hwp", "eom://schemas/material-learning/hwp-source/1.0"
        ),
        "HWPX": MaterialSourceFormatDescriptor(
            "application/vnd.hancom.hwpx",
            ".hwpx",
            "eom://schemas/material-learning/hwpx-source/1.0",
        ),
    }
)


class MaterialSourceMember(FrozenModel):
    """Member identity inside its enclosing source Artifact, not a new entity."""

    member_path: str = Field(min_length=1, max_length=128)
    schema_ref: str = Field(pattern=r"^eom://schemas/[A-Za-z0-9._/-]{1,220}$")
    media_type: str
    sha256: Sha256
    bytes: int = Field(strict=True, ge=8, le=256 * 1024 * 1024)


def _require_source_member(
    source_format: MaterialSourceFormat, member: MaterialSourceMember | MaterialArtifactMember
) -> None:
    descriptor = MATERIAL_SOURCE_FORMATS[source_format]
    if (
        member.member_path != "source/original" + descriptor.suffix
        or member.media_type != descriptor.media_type
        or member.schema_ref != descriptor.schema_ref
        or not 8 <= member.bytes <= 256 * 1024 * 1024
    ):
        raise ValueError("MATERIAL_LEARNING_SOURCE_MEMBER_MISMATCH")


class MaterialSourceUploadCommand(FrozenModel):
    schema_version: Literal["material-learning-source-upload/1.0"] = (
        "material-learning-source-upload/1.0"
    )
    operation: Literal["INGEST_MATERIAL_LEARNING_SOURCE"] = "INGEST_MATERIAL_LEARNING_SOURCE"
    actor_id: MaterialOperatorId
    original_filename: str = Field(min_length=1, max_length=255)
    source_format: MaterialSourceFormat
    media_type: str
    content_length: int = Field(strict=True, ge=8, le=256 * 1024 * 1024)
    sha256: Sha256
    rights_confirmed: Literal[True]
    idempotency_key: MaterialIdempotencyKey

    _text = field_validator("original_filename")(_safe_text)
    _rights = field_validator("rights_confirmed", mode="before")(
        require_material_rights_confirmation
    )

    @model_validator(mode="after")
    def exact_source_media(self) -> Self:
        validate_contract("material-learning-source-upload-v1", self.model_dump(mode="json"))
        if self.media_type != MATERIAL_SOURCE_FORMATS[self.source_format].media_type:
            raise ValueError("MATERIAL_LEARNING_SOURCE_MEDIA_MISMATCH")
        return self


class MaterialSourceUploadManifest(FrozenModel):
    schema_version: Literal["material-learning-source-manifest/1.0"] = (
        "material-learning-source-manifest/1.0"
    )
    uploaded_by: MaterialOperatorId
    original_filename: str = Field(min_length=1, max_length=255)
    source_format: MaterialSourceFormat
    rights_confirmed: Literal[True]
    original: MaterialSourceMember

    _text = field_validator("original_filename")(_safe_text)
    _rights = field_validator("rights_confirmed", mode="before")(
        require_material_rights_confirmation
    )

    @model_validator(mode="after")
    def exact_source_member(self) -> Self:
        validate_contract("material-learning-source-manifest-v1", self.model_dump(mode="json"))
        _require_source_member(self.source_format, self.original)
        return self


class MaterialSourceUploadReceipt(FrozenModel):
    schema_version: Literal["material-learning-source-receipt/1.0"] = (
        "material-learning-source-receipt/1.0"
    )
    manifest: MaterialArtifactMember
    original: MaterialArtifactMember
    uploaded_by: MaterialOperatorId
    created_at: UtcDatetime
    original_filename: str = Field(min_length=1, max_length=255)
    source_format: MaterialSourceFormat

    _text = field_validator("original_filename")(_safe_text)

    @model_validator(mode="after")
    def exact_enclosing_artifact(self) -> Self:
        validate_contract("material-learning-source-receipt-v1", self.model_dump(mode="json"))
        _require_source_member(self.source_format, self.original)
        if (
            self.manifest.artifact_id != self.original.artifact_id
            or self.manifest.artifact_revision_id != self.original.artifact_revision_id
            or self.manifest.member_path != "material/source-upload-manifest.json"
            or self.manifest.schema_ref != "eom://schemas/material-learning/source-manifest/1.0"
            or self.manifest.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_SOURCE_RECEIPT_MISMATCH")
        return self


class MaterialLearningSourceSelection(FrozenModel):
    source_role: SourceRole
    source_upload: MaterialSourceUploadReceipt


def _require_source_selections(
    sources: tuple[MaterialLearningSourceSelection, ...], actor_id: str
) -> None:
    roles = tuple(source.source_role for source in sources)
    if roles not in {("MAIN",), ("MAIN", "SOLUTIONS")}:
        raise ValueError("MATERIAL_LEARNING_SOURCE_ROLE_ORDER_INVALID")
    if any(source.source_upload.uploaded_by != actor_id for source in sources):
        raise ValueError("MATERIAL_LEARNING_SOURCE_OWNER_MISMATCH")
    if len({source.source_upload.original.sha256 for source in sources}) != len(sources):
        raise ValueError("MATERIAL_LEARNING_DUPLICATE_SOURCE_FILE")


class CreateMaterialLearningCommand(FrozenModel):
    schema_version: Literal["material-learning-create/1.0"] = "material-learning-create/1.0"
    operation: Literal["CREATE_MATERIAL_LEARNING"] = "CREATE_MATERIAL_LEARNING"
    actor_id: MaterialOperatorId
    idempotency_key: MaterialIdempotencyKey
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def exact_actor_and_sources(self) -> Self:
        validate_contract("material-learning-create-v1", self.model_dump(mode="json"))
        _require_source_selections(self.sources, self.actor_id)
        return self


class MaterialLearningIntakeManifest(FrozenModel):
    schema_version: Literal["material-learning-intake/1.0"] = "material-learning-intake/1.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    requested_by: MaterialOperatorId
    request_sha256: Sha256
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=1, max_length=2)
    rights_attestation: MaterialArtifactMember

    @model_validator(mode="after")
    def closed_intake(self) -> Self:
        validate_contract("material-learning-intake-v1", self.model_dump(mode="json"))
        _require_source_selections(self.sources, self.requested_by)
        if (
            self.rights_attestation.schema_ref != "eom://schemas/material-learning/rights/1.0"
            or self.rights_attestation.member_path != "rights/attestation.json"
            or self.rights_attestation.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_INTAKE_RIGHTS_POINTER_INVALID")
        return self


class MaterialLearningAcceptance(FrozenModel):
    schema_version: Literal["material-learning-acceptance/1.0"] = "material-learning-acceptance/1.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    request_sha256: Sha256
    replayed: bool


class MaterialLearningErrorResponse(FrozenModel):
    schema_version: Literal["material-learning-error/1.0"] = "material-learning-error/1.0"
    status: Literal["ERROR"] = "ERROR"
    error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")


MaterialRunState = Literal[
    "RECEIVED",
    "PREPARING",
    "DISCOVERING",
    "PROCESSING",
    "WAITING_FOR_CAPACITY",
    "PAUSED",
    "COMPLETED",
    "COMPLETED_WITH_EXCEPTIONS",
    "FAILED",
    "CANCELLED",
]
MaterialTaskStateValue = Literal[
    "PENDING",
    "PREPARING",
    "READY",
    "RUNNING",
    "RESULT_READY",
    "REGISTERED",
    "ANALYZING",
    "PUBLISHING",
    "GRAPH_READY",
    "COMPLETED",
    "EXCEPTION",
    "FAILED",
    "CANCELLED",
]


class MaterialTaskCount(FrozenModel):
    state: MaterialTaskStateValue
    count: int = Field(strict=True, ge=0, le=1_000_000)


class MaterialLearningRunSummary(FrozenModel):
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=200)
    material_kind: MaterialKind
    state: MaterialRunState
    task_counts: tuple[MaterialTaskCount, ...] = Field(max_length=13)
    error_code: str | None = Field(min_length=3, max_length=128)
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def unique_counts(self) -> Self:
        if len({counter.state for counter in self.task_counts}) != len(self.task_counts):
            raise ValueError("MATERIAL_LEARNING_DUPLICATE_TASK_COUNTER")
        return self


class MaterialLearningTaskSummary(FrozenModel):
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    ordinal: int = Field(strict=True, ge=1, le=1_000_000)
    task_kind: Literal["PREPARE", "DISCOVER", "EXPLANATION", "QUESTION"]
    state: MaterialTaskStateValue
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    item_revision_id: str | None = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    analysis_run_id: str | None = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str | None = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    error_code: str | None = Field(min_length=3, max_length=128)


class ListMaterialLearningRunsQuery(FrozenModel):
    schema_version: Literal["material-learning-run-query/1.0"] = "material-learning-run-query/1.0"
    operation: Literal["LIST_MATERIAL_LEARNING_RUNS"] = "LIST_MATERIAL_LEARNING_RUNS"
    actor_id: MaterialOperatorId
    limit: int = Field(default=20, strict=True, ge=1, le=50)

    @model_validator(mode="after")
    def closed_query(self) -> Self:
        validate_contract("material-learning-run-query-v1", self.model_dump(mode="json"))
        return self


class GetMaterialLearningRunQuery(FrozenModel):
    schema_version: Literal["material-learning-run-query/1.0"] = "material-learning-run-query/1.0"
    operation: Literal["GET_MATERIAL_LEARNING_RUN"] = "GET_MATERIAL_LEARNING_RUN"
    actor_id: MaterialOperatorId
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    after_ordinal: int = Field(default=0, strict=True, ge=0, le=1_000_000)
    limit: int = Field(default=50, strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def closed_query(self) -> Self:
        validate_contract("material-learning-run-query-v1", self.model_dump(mode="json"))
        return self


class MaterialLearningRunList(FrozenModel):
    schema_version: Literal["material-learning-run-list/1.0"] = "material-learning-run-list/1.0"
    runs: tuple[MaterialLearningRunSummary, ...] = Field(max_length=50)

    @model_validator(mode="after")
    def closed_reply(self) -> Self:
        validate_contract("material-learning-run-list-v1", self.model_dump(mode="json"))
        return self


class MaterialLearningRunDetail(FrozenModel):
    schema_version: Literal["material-learning-run-detail/1.0"] = "material-learning-run-detail/1.0"
    run: MaterialLearningRunSummary
    tasks: tuple[MaterialLearningTaskSummary, ...] = Field(max_length=100)
    next_ordinal: int | None = Field(strict=True, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def closed_reply(self) -> Self:
        validate_contract("material-learning-run-detail-v1", self.model_dump(mode="json"))
        return self


class ControlMaterialLearningRunCommand(FrozenModel):
    schema_version: Literal["material-learning-control/1.0"] = "material-learning-control/1.0"
    operation: Literal["CONTROL_MATERIAL_LEARNING_RUN"] = "CONTROL_MATERIAL_LEARNING_RUN"
    actor_id: MaterialOperatorId
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    action: Literal["PAUSE", "RESUME"]
    expected_updated_at: UtcDatetime

    @model_validator(mode="after")
    def closed_command(self) -> Self:
        validate_contract("material-learning-control-v1", self.model_dump(mode="json"))
        return self


class MaterialLearningControlResult(FrozenModel):
    schema_version: Literal["material-learning-control-result/1.0"] = (
        "material-learning-control-result/1.0"
    )
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    state: MaterialRunState
    updated_at: UtcDatetime
    replayed: bool

    @model_validator(mode="after")
    def closed_reply(self) -> Self:
        validate_contract("material-learning-control-result-v1", self.model_dump(mode="json"))
        return self
