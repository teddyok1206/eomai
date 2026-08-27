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
AnalysisRangeId = Annotated[str, Field(pattern=r"^analysisrange_[0-9a-f]{32}$")]
CurriculumUnitKey = Annotated[
    str,
    Field(
        pattern=(
            r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|"
            r"5-\([1-7]\)|6-\([1-4]\))$"
        )
    ),
]


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


class ContentIntakeSourcePointer(WebModel):
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    filename: str = Field(min_length=1, max_length=255)
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_member: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: Literal["image/png", "image/jpeg"]


class KnowledgeAnalysisBatchStatus(WebModel):
    """Bounded read-only projection for the long-running analysis lane."""

    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    state: Literal["QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "CANCELLED"]
    total_range_count: int = Field(ge=1, le=1000)
    accepted_range_count: int = Field(ge=0, le=1000)
    failed_range_count: int = Field(ge=0, le=1000)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_progress(self) -> KnowledgeAnalysisBatchStatus:
        if self.accepted_range_count + self.failed_range_count > self.total_range_count:
            raise ValueError("analysis batch terminal counts exceed total ranges")
        if self.state == "SUCCEEDED" and (
            self.accepted_range_count != self.total_range_count or self.failed_range_count != 0
        ):
            raise ValueError("succeeded analysis batch must accept every range")
        return self


class KnowledgeAnalysisBatchRangeStatus(WebModel):
    """Minimum immutable range projection needed by the quality observer."""

    range_id: str = Field(pattern=r"^analysisrange_[0-9a-f]{32}$")
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    ordinal: int = Field(ge=0, le=999)
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    curriculum_unit_keys: tuple[CurriculumUnitKey, ...] = Field(max_length=32)
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    analysis_schema_ref: Literal[
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0",
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0",
    ]
    analysis_run_id: str | None = Field(default=None, pattern=r"^analysisrun_[0-9a-f]{32}$")
    state: Literal["PENDING", "CLAIMED", "SUBMITTED", "ACCEPTED", "FAILED", "CANCELLED"]
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def ordered_page_interval(self) -> KnowledgeAnalysisBatchRangeStatus:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("analysis range page interval is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("analysis range page interval exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("analysis range curriculum unit keys must be sorted and unique")
        return self


class KnowledgeQualityFindingCode(StrEnum):
    ANALYSIS_REVISION_REUSED = "ANALYSIS_REVISION_REUSED"
    ANALYSIS_RUN_REUSED = "ANALYSIS_RUN_REUSED"
    BATCH_RANGE_COUNT_MISMATCH = "BATCH_RANGE_COUNT_MISMATCH"
    PAGE_COVERAGE_GAP = "PAGE_COVERAGE_GAP"
    PAGE_COVERAGE_OVERLAP = "PAGE_COVERAGE_OVERLAP"
    RANGE_BATCH_POINTER_MISMATCH = "RANGE_BATCH_POINTER_MISMATCH"
    RANGE_ORDINAL_SEQUENCE_INVALID = "RANGE_ORDINAL_SEQUENCE_INVALID"
    SOURCE_POINTER_DRIFT = "SOURCE_POINTER_DRIFT"


class KnowledgeQualityFinding(WebModel):
    code: KnowledgeQualityFindingCode
    severity: Literal["WARNING", "ERROR"]
    document_revision_id: str | None = Field(default=None, pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int | None = Field(default=None, ge=1, le=10000)
    last_physical_page: int | None = Field(default=None, ge=1, le=10000)
    range_ids: tuple[AnalysisRangeId, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def coherent_page_interval(self) -> KnowledgeQualityFinding:
        if (self.first_physical_page is None) != (self.last_physical_page is None):
            raise ValueError("quality finding page interval must be complete")
        if (
            self.first_physical_page is not None
            and self.last_physical_page is not None
            and self.last_physical_page < self.first_physical_page
        ):
            raise ValueError("quality finding page interval is reversed")
        if len(self.range_ids) != len(set(self.range_ids)):
            raise ValueError("quality finding range IDs must be unique")
        return self


class KnowledgeDocumentCoverage(WebModel):
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    range_count: int = Field(ge=1, le=1000)
    unique_page_count: int = Field(ge=1, le=32000)
    accepted_page_count: int = Field(ge=0, le=32000)
    cancelled_page_count: int = Field(ge=0, le=32000)
    failed_page_count: int = Field(ge=0, le=32000)
    in_progress_page_count: int = Field(ge=0, le=32000)
    gap_page_count: int = Field(ge=0, le=32000)
    overlap_page_count: int = Field(ge=0, le=32000)
    curriculum_unit_keys: tuple[CurriculumUnitKey, ...] = Field(max_length=32)


class KnowledgeAnalysisQualityReport(WebModel):
    """Derived, non-persisted quality observation over one batch projection."""

    schema_version: Literal["knowledge-analysis-quality-report/1.0"] = (
        "knowledge-analysis-quality-report/1.0"
    )
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    resource_version: int = Field(ge=1)
    quality_state: Literal["PASS", "WARN", "FAIL"]
    total_range_count: int = Field(ge=1, le=1000)
    observed_range_count: int = Field(ge=0, le=1000)
    selected_page_count: int = Field(ge=0, le=32000)
    unique_page_count: int = Field(ge=0, le=32000)
    accepted_page_count: int = Field(ge=0, le=32000)
    cancelled_page_count: int = Field(ge=0, le=32000)
    failed_page_count: int = Field(ge=0, le=32000)
    in_progress_page_count: int = Field(ge=0, le=32000)
    visual_input_range_count: int = Field(ge=0, le=1000)
    visual_input_page_count: int = Field(ge=0, le=32000)
    gap_page_count: int = Field(ge=0, le=32000)
    overlap_page_count: int = Field(ge=0, le=32000)
    duplicate_analysis_revision_count: int = Field(ge=0, le=1000)
    duplicate_analysis_run_count: int = Field(ge=0, le=1000)
    document_count: int = Field(ge=0, le=1000)
    curriculum_unit_count: int = Field(ge=0, le=32000)
    documents: tuple[KnowledgeDocumentCoverage, ...] = Field(max_length=1000)
    findings: tuple[KnowledgeQualityFinding, ...] = Field(max_length=5008)
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_report(self) -> KnowledgeAnalysisQualityReport:
        if self.document_count != len(self.documents):
            raise ValueError("quality report document count is inconsistent")
        if self.selected_page_count != (
            self.accepted_page_count
            + self.failed_page_count
            + self.cancelled_page_count
            + self.in_progress_page_count
        ):
            raise ValueError("quality report state page counts are inconsistent")
        if self.unique_page_count > self.selected_page_count:
            raise ValueError("quality report unique pages exceed selected pages")
        if self.visual_input_range_count > self.observed_range_count:
            raise ValueError("quality report visual ranges exceed observed ranges")
        if self.visual_input_page_count > self.selected_page_count:
            raise ValueError("quality report visual pages exceed selected pages")
        severities = {finding.severity for finding in self.findings}
        expected = "FAIL" if "ERROR" in severities else "WARN" if severities else "PASS"
        if self.quality_state != expected:
            raise ValueError("quality report state does not match its findings")
        return self


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
    choice_count: Literal[5] = 5
    equation_required: Literal[True] = True
    image_required: Literal[True] = True
    quality_profile: QualityProfile
    source_intake_batch_id: str | None = Field(default=None, pattern=r"^intake_[0-9a-f]{32}$")
    knowledge_grounding: bool = False
    curriculum_root_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")

    @model_validator(mode="after")
    def exact_knowledge_grounding_scope(self) -> RequestDraftUpdate:
        if self.knowledge_grounding != (self.curriculum_root_key is not None):
            raise ValueError(
                "knowledge grounding and a stable curriculum root key must be selected together"
            )
        return self


class RequestDraft(RequestDraftUpdate):
    schema_version: Literal["2.0"] = "2.0"
    request_draft_id: str = Field(pattern=r"^requestdraft_[0-9a-f]{32}$")
    status: Literal["DRAFT"] = "DRAFT"
    language: Literal["ko"] = "ko"
    original_request_text: str = Field(min_length=10, max_length=2000)
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime


class DraftSubmission(WebModel):
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class CodexAccountAdminCommand(WebModel):
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    resource_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_reason(self) -> CodexAccountAdminCommand:
        requires_reason = self.command_type in {"DRAIN", "DISABLE"}
        if requires_reason != (self.reason_code is not None):
            raise ValueError("drain/disable require a reason and observe/enable forbid one")
        return self


class ControlArtifactPointerDraft(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class BundleRevisionPointerDraft(WebModel):
    bundle_id: str = Field(pattern=r"^(?:instrbundle|refbundle)_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^(?:instrrev|refrev)_[0-9a-f]{32}$")
    manifest_artifact: ControlArtifactPointerDraft
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PresetModelCandidateDraft(WebModel):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"]


class PresetRolePolicyDraft(WebModel):
    role: Literal["authoring", "image", "review", "item_management", "support"]
    model_candidates: tuple[PresetModelCandidateDraft, ...] = Field(min_length=1, max_length=4)
    instruction_bundle: BundleRevisionPointerDraft
    reference_bundle: BundleRevisionPointerDraft | None
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    timeout_seconds: int = Field(ge=30, le=7200)
    sandbox: Literal["read-only"] = "read-only"
    network: Literal["disabled"] = "disabled"


class ExecutionPresetDraftSubmission(WebModel):
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    role_policies: tuple[PresetRolePolicyDraft, ...] = Field(min_length=1, max_length=5)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    general_knowledge_policy: Literal["DENY", "ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[str, ...] = Field(min_length=1, max_length=16)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class ExecutionPresetLifecycleCommand(WebModel):
    resource_version: int = Field(ge=1)
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
    revision_etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    revision_state: str
    content_pack_release_id: str
    template_delivery_available: bool = False
    body: str | None = Field(default=None, max_length=20000)
    choices: tuple[PreviewChoice, ...] = Field(default=(), max_length=10)
    answer: str | None = Field(default=None, max_length=4000)
    explanation: str | None = Field(default=None, max_length=20000)
    equations: tuple[str, ...] = Field(default=(), max_length=50)
    tables: tuple[PreviewTable, ...] = Field(default=(), max_length=20)


class StructuredItemImportRequest(WebModel):
    base_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    revision_etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reviewed: Literal[True]
    review_reason: str = Field(min_length=10, max_length=2000)
    content: dict[str, Any]

    @model_validator(mode="after")
    def canonical_api_contract(self) -> StructuredItemImportRequest:
        required = {"schema_version", "locale", "title", "body", "interaction", "solution", "score"}
        if self.content.get("schema_version") != "1.0" or not required.issubset(self.content):
            raise ValueError("structured content envelope is incomplete")
        return self


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
    source_artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
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
    created_by_operator_id: str = Field(pattern=r"^operator_[a-f0-9]{32}$")
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    resource_version: int = Field(ge=1)
