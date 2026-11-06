"""Browser values only; source authority and execution stay in API/Catalog."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from eom_web_gui.contracts import ItemDbRegistration, StudioIdempotencyKey, UtcDatetime, WebModel

_SHA = r"^sha256:[0-9a-f]{64}$"
MaterialKind = Literal["TEXTBOOK", "REFERENCE_BOOK", "WORKBOOK", "MOCK_EXAM", "OTHER"]
RunState = Literal[
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
TaskState = Literal[
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


class MaterialItemMetadata(WebModel):
    item_type_key: Literal["uploaded-material-item"]
    source_kind: Literal["EXTERNAL"]
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    unit_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    source_filename: str = Field(min_length=1, max_length=255)
    printed_label: str | None = Field(min_length=1, max_length=100)
    section_path: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        max_length=12
    )
    physical_pages: tuple[Annotated[int, Field(strict=True, ge=1, le=2000)], ...] = Field(
        min_length=1, max_length=32
    )
    lineage_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approval_basis: Literal["SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION"]


class MaterialItemDbEntry(WebModel):
    schema_version: Literal["material-item-db-entry/1.0"]
    metadata: MaterialItemMetadata
    material_title: str = Field(min_length=1, max_length=200)
    registration: ItemDbRegistration


class MaterialLearningArtifactMember(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=240)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=_SHA)
    bytes: int = Field(strict=True, ge=1, le=2 * 1024 * 1024 * 1024)


class MaterialLearningSourceReceipt(WebModel):
    schema_version: Literal["material-learning-source-receipt/1.0"]
    manifest: MaterialLearningArtifactMember
    original: MaterialLearningArtifactMember
    uploaded_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    original_filename: str = Field(min_length=1, max_length=255)
    source_format: Literal["PDF", "HWP", "HWPX"]


class MaterialLearningSourceSelection(WebModel):
    source_role: Literal["MAIN", "SOLUTIONS"]
    source_upload: MaterialLearningSourceReceipt


class MaterialLearningUpload(WebModel):
    schema_version: Literal["material-learning-upload/1.0"] = "material-learning-upload/1.0"
    title: str = Field(min_length=1, max_length=200)
    material_kind: MaterialKind
    source_description: str = Field(min_length=1, max_length=2000)
    additional_instructions: str = Field(max_length=8000)
    curriculum_unit_hints: tuple[str, ...] = Field(max_length=16)
    rights_confirmed: Literal[True]


class MaterialLearningSubmission(WebModel):
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=1, max_length=2)
    idempotency_key: StudioIdempotencyKey


class MaterialLearningAcceptance(WebModel):
    schema_version: Literal["material-learning-acceptance/1.0"]
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    request_sha256: str = Field(pattern=_SHA)
    replayed: bool


class MaterialLearningTaskCount(WebModel):
    state: TaskState
    count: int = Field(strict=True, ge=0, le=1_000_000)


class MaterialLearningRun(WebModel):
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=200)
    attempt: int = Field(default=1, strict=True, ge=1, le=32)
    predecessor_run_id: str | None = Field(default=None, pattern=r"^materialrun_[0-9a-f]{32}$")
    material_kind: MaterialKind
    state: RunState
    task_counts: tuple[MaterialLearningTaskCount, ...] = Field(max_length=13)
    error_code: str | None = Field(min_length=3, max_length=128)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MaterialLearningRuns(WebModel):
    schema_version: Literal["material-learning-run-list/1.0"]
    runs: tuple[MaterialLearningRun, ...] = Field(max_length=50)


class MaterialLearningTask(WebModel):
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    ordinal: int = Field(strict=True, ge=1, le=1_000_000)
    task_kind: Literal["PREPARE", "DISCOVER", "EXPLANATION", "QUESTION"]
    state: TaskState
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    item_revision_id: str | None = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    analysis_run_id: str | None = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str | None = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    error_code: str | None = Field(min_length=3, max_length=128)


class MaterialLearningDetail(WebModel):
    schema_version: Literal["material-learning-run-detail/1.0"]
    run: MaterialLearningRun
    tasks: tuple[MaterialLearningTask, ...] = Field(max_length=100)
    next_ordinal: int | None = Field(strict=True, ge=1, le=1_000_000)


class MaterialLearningControl(WebModel):
    action: Literal["PAUSE", "RESUME"]
    expected_updated_at: UtcDatetime


class MaterialLearningControlReply(WebModel):
    schema_version: Literal["material-learning-control-result/1.0"]
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    state: RunState
    updated_at: UtcDatetime
    replayed: bool


class MaterialLearningRetry(WebModel):
    expected_updated_at: UtcDatetime


class MaterialLearningRetryReply(WebModel):
    schema_version: Literal["material-learning-retry-result/1.0"]
    predecessor_run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    state: RunState
    reused_tasks: int = Field(strict=True, ge=0, le=1_000_000)
    retried_tasks: int = Field(strict=True, ge=1, le=1_000_000)
    replayed: bool


class MaterialLearningTaskPage(WebModel):
    source_role: Literal["MAIN", "SOLUTIONS"]
    original_filename: str = Field(min_length=1, max_length=255)
    physical_page: int = Field(strict=True, ge=1, le=2000)


class MaterialLearningTaskDetail(WebModel):
    schema_version: Literal["material-learning-task-detail/1.0"]
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    task: MaterialLearningTask
    attempt: int = Field(strict=True, ge=1, le=32)
    predecessor_task_id: str | None = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    printed_label: str | None = Field(min_length=1, max_length=100)
    section_path: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        max_length=12
    )
    source_pages: tuple[MaterialLearningTaskPage, ...] = Field(max_length=64)
