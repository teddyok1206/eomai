"""Immutable BFF contracts paired with JSON Schema 2020-12 documents."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QualityProfile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class ContentIntakeOption(WebModel):
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    batch_name: str = Field(min_length=1, max_length=256)
    state: Literal["ACCEPTED"] = "ACCEPTED"
    purpose: str = Field(max_length=2000)
    updated_at: UtcDatetime


class RequestDraftInput(WebModel):
    original_request_text: str = Field(min_length=10, max_length=2000)

    @field_validator("original_request_text")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("request text must contain at least 10 non-whitespace characters")
        return value


class RequestDraftUpdate(WebModel):
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    item_format: Literal["multiple_choice"] = "multiple_choice"
    task_type: Literal["calculation", "conceptual", "data_interpretation"]
    difficulty: Literal["easy", "medium", "hard"]
    choice_count: int = Field(ge=2, le=5)
    equation_required: bool
    image_required: bool
    quality_profile: QualityProfile
    source_intake_batch_id: str | None = Field(default=None, pattern=r"^intake_[0-9a-f]{32}$")


class RequestDraft(RequestDraftUpdate):
    schema_version: Literal["1.0"] = "1.0"
    request_draft_id: str = Field(pattern=r"^requestdraft_[0-9a-f]{32}$")
    status: Literal["DRAFT"] = "DRAFT"
    language: Literal["ko"] = "ko"
    original_request_text: str = Field(min_length=10, max_length=2000)
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime


class DraftSubmission(WebModel):
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class WorkflowApproval(WebModel):
    etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reason: str | None = Field(default=None, max_length=2000)


class TimelineEvent(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=128)
    timestamp: UtcDatetime
    label: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=40)
    step: str | None = None
    worker_slot: str | None = None
    job_id: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    artifact_id: str | None = None
    validation_result: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")


class PreviewChoice(WebModel):
    label: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=4000)


class PreviewTable(WebModel):
    caption: str | None = Field(default=None, max_length=500)
    headers: tuple[str, ...] = Field(default=(), max_length=20)
    rows: tuple[tuple[str, ...], ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def rectangular(self) -> PreviewTable:
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("preview table rows must match header width")
        return self


class ItemPreview(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    preview_state: Literal["AVAILABLE", "METADATA_ONLY"]
    workflow_id: str
    item_id: str
    item_revision_id: str
    revision_state: str
    content_pack_release_id: str
    template_delivery_available: bool = False
    body: str | None = Field(default=None, max_length=20000)
    choices: tuple[PreviewChoice, ...] = Field(default=(), max_length=10)
    answer: str | None = Field(default=None, max_length=4000)
    explanation: str | None = Field(default=None, max_length=20000)
    equations: tuple[str, ...] = Field(default=(), max_length=50)
    tables: tuple[PreviewTable, ...] = Field(default=(), max_length=20)


class ExplorerEntity(StrEnum):
    WORKFLOWS = "workflows"
    WORKFLOW_COMMANDS = "workflow_commands"
    WORKFLOW_EVENTS = "workflow_events"
    STEP_RUNS = "step_runs"
    JOBS = "jobs"
    ARTIFACTS = "artifacts"
    ARTIFACT_REVISIONS = "artifact_revisions"
    ITEMS = "items"
    ITEM_REVISIONS = "item_revisions"
    CONTENT_PACK_RELEASES = "content_pack_releases"
    USAGE_PLANS = "usage_plans"
    USAGE_RECORDS = "usage_records"
    HWPX_BUILDS = "hwpx_builds"


class ExplorerQuery(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    entity: ExplorerEntity
    exact_id: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    date_from: UtcDatetime | None = None
    date_to: UtcDatetime | None = None
    sort: Literal["created_desc", "created_asc", "updated_desc", "updated_asc"] = "created_desc"
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_range(self) -> ExplorerQuery:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be later than date_to")
        return self


class ExplorerResult(WebModel):
    entity: ExplorerEntity
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    next_cursor: str | None = None
    has_more: bool = False
    capability: Literal["READY", "EXACT_ID_REQUIRED", "PREPARED_NOT_DEPLOYED"] = "READY"


class HwpxCapability(WebModel):
    state: Literal["READY", "PREPARED_NOT_DEPLOYED", "UNAVAILABLE", "DEGRADED"]
    renderer_key: str
    renderer_version: str
    document_profile: Literal["eom-question-template-v1"]
    boundary: Literal["APPLICATION_API_ONLY"] = "APPLICATION_API_ONLY"
    build_available: bool
    native_equations: bool
    native_tables: bool
    detail_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    message: str


class HwpxBuildRequest(WebModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    require_native_equations: Literal[True] = True
    require_native_tables: Literal[True] = True
    item_number: int = Field(default=1, ge=1, le=999)


class HwpxBuildView(WebModel):
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_id: str
    item_revision_id: str
    renderer: Literal["kordoc", "eom-template"]
    renderer_version: Literal["4.9.0", "1.0.0"]
    state: Literal["REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"]
    validation_state: Literal["PENDING", "PASS", "FAIL"]
    native_equation_count: int | None = Field(default=None, ge=0, le=32)
    native_table_count: int | None = Field(default=None, ge=0, le=20)
    output_artifact_id: str | None = None
    output_artifact_revision_id: str | None = None
    output_sha256: str | None = None
    download_available: bool
    failure_code: str | None = None
    failure_detail_sanitized: str | None = None
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
