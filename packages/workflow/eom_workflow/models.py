"""Immutable workflow definition and placeholder role contracts."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any, Literal

from eom_catalog_contracts import (
    AnchorId,
    AssessmentItemContent,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    EducationalRetrievalRequirement,
    EquationBlock,
    IntegratedScienceCurriculumScope,
    ItemScore,
    ItemSolution,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
    KnowledgeAnalysisWorkerProposalV4,
    KnowledgeAnalysisWorkerProposalV5,
    KnowledgeAnalysisWorkerProposalV6,
    KnowledgeAnalysisWorkerProposalV7,
    LegacyItemEditorialCompatibilityProposal,
    LegacyItemEditorialCompatibilityRequest,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    ParagraphBlock,
    SingleChoiceInteraction,
    StatementSetBlock,
    TableBlock,
    normalize_reviewed_authoring_guidance,
    validate_integrated_science_curriculum_scope,
    validate_item_reference_contract,
    validate_reviewed_authoring_guidance,
)
from eom_catalog_contracts.mock_exam_production_plan import ContentTeamMockExamSlotV1
from eom_image_contracts import sanitize_svg_overlay
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
JobId = Annotated[str, Field(pattern=r"^job_[0-9a-f]{32}$")]
WorkflowId = Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
StepRunId = Annotated[str, Field(pattern=r"^steprun_[0-9a-f]{32}$")]
ArtifactId = Annotated[str, Field(pattern=r"^artifact_[0-9a-f]{32}$")]
RevisionId = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{32}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class StepType(StrEnum):
    AGENT = "agent"
    DECISION = "decision"
    HUMAN_GATE = "human_gate"
    TERMINAL = "terminal"


class DecisionOperator(StrEnum):
    INPUT_EQUALS = "input_equals"
    INPUT_IN = "input_in"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_SKIPPED = "step_skipped"
    APPROVAL_DECISION = "approval_decision"
    STEP_RESULT_IMAGE_COUNT = "step_result_image_count"


class WorkflowLimits(FrozenModel):
    max_rework_cycles: int = Field(ge=0, le=10)
    max_step_attempts: int = Field(ge=1, le=10)


class AgentStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["agent"]
    worker_role: Literal["authoring", "image", "review", "item_management", "support"]
    result_schema: str = Field(pattern=r"^[a-z][a-z-]+-result@[0-9]+\.[0-9]+$")
    on_success: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")


class DecisionStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["decision"]
    operator: DecisionOperator
    field: str = Field(pattern=r"^(?:/(?:[^~/]|~[01])*)+$")
    branches: dict[str, str] = Field(min_length=1, max_length=10)
    source_step: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")

    @model_validator(mode="after")
    def validate_source(self) -> DecisionStep:
        if self.operator == DecisionOperator.STEP_RESULT_IMAGE_COUNT:
            if self.source_step is None:
                raise ValueError("step-result decisions require one source step")
        elif self.source_step is not None:
            raise ValueError("input decisions cannot declare a source step")
        return self


class HumanGateStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["human_gate"]
    allowed_actor_roles: tuple[Literal["reviewer", "admin"], ...] = Field(min_length=1)
    allowed_rework_targets: tuple[str, ...] = Field(min_length=1)
    on_approve: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")


class TerminalStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["terminal"]
    terminal_status: Literal["COMPLETED"]


StepDefinition = Annotated[
    AgentStep | DecisionStep | HumanGateStep | TerminalStep,
    Field(discriminator="type"),
]


class WorkflowDefinition(FrozenModel):
    schema_version: Literal["1.0"]
    definition_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    definition_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    start_step: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    limits: WorkflowLimits
    steps: tuple[StepDefinition, ...] = Field(min_length=2, max_length=64)


class WorkerRequest(FrozenModel):
    request_name: Literal[
        "PLACEHOLDER_REQUEST",
        "KNOWLEDGE_ITEM_REQUEST",
        "GENERATED_KNOWLEDGE_ITEM_REQUEST",
    ]
    image_mode: Literal["skip", "required"]


class KnowledgeAnalysisWorkerRequest(FrozenModel):
    request_name: Literal["KNOWLEDGE_ANALYSIS_REQUEST"] = "KNOWLEDGE_ANALYSIS_REQUEST"
    analysis_request: (
        KnowledgeAnalysisRequestV2
        | KnowledgeAnalysisRequestV3
        | KnowledgeAnalysisRequestV4
        | KnowledgeAnalysisRequestV5
        | KnowledgeAnalysisRequestV6
        | KnowledgeAnalysisRequestV7
        | KnowledgeAnalysisRequestV8
        | KnowledgeAnalysisRequestV9
    )


class LegacyItemExtractionWorkerRequest(FrozenModel):
    request_name: Literal["LEGACY_ITEM_EXTRACTION_REQUEST"] = "LEGACY_ITEM_EXTRACTION_REQUEST"
    extraction_request: LegacyItemExtractionRequest


class LegacyItemEditorialCompatibilityWorkerRequest(FrozenModel):
    request_name: Literal["LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST"] = (
        "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST"
    )
    compatibility_request: LegacyItemEditorialCompatibilityRequest


class ItemBrief(FrozenModel):
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    task_type: Literal["calculation", "conceptual", "data_interpretation"]
    difficulty: Literal["easy", "medium", "hard"]
    choice_count: Literal[5] = 5
    equation_required: Literal[True] = True
    image_required: Literal[True] = True
    quality_profile: Literal["fast", "balanced", "deep"]
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ItemBriefV2(ItemBrief):
    """Reviewed authoring intent plus an optional immutable curriculum breadcrumb."""

    schema_version: Literal["2.0"] = "2.0"
    authoring_guidance: str = Field(min_length=10, max_length=2000)
    authoring_guidance_sha256: Sha256
    curriculum_scope: IntegratedScienceCurriculumScope | None = None

    @field_validator("authoring_guidance")
    @classmethod
    def normalize_authoring_guidance(cls, value: str) -> str:
        return normalize_reviewed_authoring_guidance(value)

    @model_validator(mode="after")
    def validate_authoring_guidance_hash(self) -> ItemBriefV2:
        validate_reviewed_authoring_guidance(
            self.authoring_guidance, self.authoring_guidance_sha256
        )
        if self.curriculum_scope is not None:
            validate_integrated_science_curriculum_scope(self.curriculum_scope)
        return self


class ContentTeamItemBrief(FrozenModel):
    """Reviewed intent without EOM-authored content-shape requirements."""

    schema_version: Literal["3.0"] = "3.0"
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    task_type: str = Field(min_length=1, max_length=80)
    difficulty: str = Field(min_length=1, max_length=80)
    authoring_guidance: str = Field(min_length=10, max_length=2000)
    authoring_guidance_sha256: Sha256
    curriculum_scope: IntegratedScienceCurriculumScope | None = None
    mock_exam_slot: ContentTeamMockExamSlotV1 | None = None
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("authoring_guidance")
    @classmethod
    def normalize_authoring_guidance(cls, value: str) -> str:
        return normalize_reviewed_authoring_guidance(value)

    @model_validator(mode="after")
    def validate_authoring_guidance_hash(self) -> ContentTeamItemBrief:
        validate_reviewed_authoring_guidance(
            self.authoring_guidance, self.authoring_guidance_sha256
        )
        if self.curriculum_scope is not None:
            validate_integrated_science_curriculum_scope(self.curriculum_scope)
        if self.mock_exam_slot is not None:
            if self.curriculum_scope is None:
                raise ValueError("mock-exam slot requires one resolved curriculum scope")
            if (
                self.curriculum_scope.selected_unit_key
                != self.mock_exam_slot.curriculum_selected_unit_key
                or self.curriculum_scope.large_unit_key != self.mock_exam_slot.large_unit_key
                or self.difficulty != self.mock_exam_slot.preferred_difficulty
                or self.task_type != self.mock_exam_slot.preferred_material_profiles[0]
            ):
                raise ValueError("content-team brief differs from its typed mock-exam slot")
        return self


class StimulusAssetSelection(FrozenModel):
    asset_key: Literal["eom-question-template-reference-v1"]


class ContentPackSelection(FrozenModel):
    pack_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    environment: Literal["development", "test"]


class WorkflowProductionOccurrence(FrozenModel):
    """One orchestrator-owned occurrence included only in Workflow identity."""

    schema_version: Literal["workflow-production-occurrence/1.0"] = (
        "workflow-production-occurrence/1.0"
    )
    production_request_id: str = Field(pattern=r"^productionreq_[0-9a-f]{32}$")
    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")


class ExpectedWorkflowResolution(FrozenModel):
    """Exact immutable catalog and control-plane dependencies required at start."""

    schema_version: Literal["workflow-expected-resolution/1.0"] = "workflow-expected-resolution/1.0"
    workflow_definition_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    content_pack_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    content_pack_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    content_pack_bundle_sha256: Sha256
    content_pack_source_tree_sha256: Sha256
    execution_preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    execution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    execution_preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    execution_preset_content_sha256: Sha256


class WorkflowProfiles(FrozenModel):
    authoring: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    review: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    image: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,127}$")
    registration: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")


class SourceIntakeSelection(FrozenModel):
    batch_ids: tuple[Annotated[str, Field(pattern=r"^intake_[0-9a-f]{32}$")], ...] = Field(
        max_length=100
    )


class RegistryIntent(FrozenModel):
    mode: Literal["CREATE_ITEM", "REVISE_ITEM"]
    item_id: str | None = Field(default=None, pattern=r"^item_[0-9a-f]{32}$")
    base_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def validate_revision_pointers(self) -> RegistryIntent:
        has_pointers = self.item_id is not None or self.base_revision_id is not None
        if self.mode == "CREATE_ITEM" and has_pointers:
            raise ValueError("CREATE_ITEM cannot include existing Item pointers")
        if self.mode == "REVISE_ITEM" and (self.item_id is None or self.base_revision_id is None):
            raise ValueError("REVISE_ITEM requires Item and base revision pointers")
        return self


class WorkflowRequest(FrozenModel):
    request_name: Literal[
        "PLACEHOLDER_REQUEST",
        "KNOWLEDGE_ITEM_REQUEST",
        "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "KNOWLEDGE_ANALYSIS_REQUEST",
        "LEGACY_ITEM_EXTRACTION_REQUEST",
        "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST",
    ]
    image_mode: Literal["skip", "required"]
    content_pack: ContentPackSelection | None = None
    profiles: WorkflowProfiles | None = None
    source_intake: SourceIntakeSelection | None = None
    registry_intent: RegistryIntent | None = None
    item_brief: ItemBrief | ItemBriefV2 | ContentTeamItemBrief | None = None
    stimulus_asset: StimulusAssetSelection | None = None
    execution_preset_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,63}$")
    educational_retrieval: EducationalRetrievalRequirement | None = None
    production_occurrence: WorkflowProductionOccurrence | None = None
    expected_resolution: ExpectedWorkflowResolution | None = None
    analysis_request: (
        KnowledgeAnalysisRequestV2
        | KnowledgeAnalysisRequestV3
        | KnowledgeAnalysisRequestV4
        | KnowledgeAnalysisRequestV5
        | KnowledgeAnalysisRequestV6
        | KnowledgeAnalysisRequestV7
        | KnowledgeAnalysisRequestV8
        | KnowledgeAnalysisRequestV9
        | None
    ) = None
    legacy_extraction_request: LegacyItemExtractionRequest | None = None
    legacy_editorial_compatibility_request: LegacyItemEditorialCompatibilityRequest | None = None

    @model_validator(mode="after")
    def validate_catalog_request(self) -> WorkflowRequest:
        if (self.production_occurrence is None) != (self.expected_resolution is None):
            raise ValueError(
                "production occurrence and expected resolution must be supplied together"
            )
        if self.expected_resolution is not None:
            expected = self.expected_resolution
            if (
                self.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
                or self.educational_retrieval is None
                or self.content_pack is None
                or expected.content_pack_key != self.content_pack.pack_key
                or expected.execution_preset_key != self.execution_preset_key
            ):
                raise ValueError("expected resolution differs from the catalog selection")
        required_catalog_values = (self.content_pack, self.profiles, self.registry_intent)
        if any(value is not None for value in required_catalog_values) and not all(
            value is not None for value in required_catalog_values
        ):
            raise ValueError("catalog workflow request fields must be supplied together")
        if self.source_intake is not None and self.content_pack is None:
            raise ValueError("source Intake pointers require a Content Pack")
        if self.execution_preset_key is not None and self.content_pack is None:
            raise ValueError("execution preset requires a pinned Content Pack workflow")
        if self.educational_retrieval is not None and (
            self.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            or self.execution_preset_key is None
        ):
            raise ValueError(
                "educational retrieval requires a generated item request and execution preset"
            )
        if self.educational_retrieval is not None and isinstance(
            self.item_brief, (ItemBriefV2, ContentTeamItemBrief)
        ):
            scope = self.item_brief.curriculum_scope
            if (
                scope is None
                or self.educational_retrieval.curriculum_root_key != scope.graph_root_stable_key
                or self.educational_retrieval.topic_keys
            ):
                raise ValueError(
                    "V2 grounded item requests require only the selected curriculum graph root"
                )
        if self.request_name == "KNOWLEDGE_ITEM_REQUEST":
            if (
                self.content_pack is None
                or self.item_brief is None
                or self.stimulus_asset is None
                or self.image_mode != "required"
                or self.profiles is None
                or self.profiles.image is None
            ):
                raise ValueError(
                    "knowledge item workflow requires pack, brief, fixed stimulus, and image"
                )
        elif self.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST":
            content_team_request = isinstance(self.item_brief, ContentTeamItemBrief)
            if (
                self.content_pack is None
                or self.item_brief is None
                or self.stimulus_asset is not None
            ):
                raise ValueError(
                    "generated knowledge workflow requires a source-free pack and reviewed brief"
                )
            if self.source_intake is not None and self.source_intake.batch_ids:
                raise ValueError("generated knowledge workflow cannot claim source Intake batches")
            if self.profiles is None:
                raise ValueError("generated knowledge workflow requires pinned profiles")
            if content_team_request:
                conditional_image = (
                    self.image_mode == "required" and self.profiles.image is not None
                )
                historical_no_image = self.image_mode == "skip" and self.profiles.image is None
                if not (conditional_image or historical_no_image):
                    raise ValueError(
                        "content-team image mode and profile must describe one coherent release"
                    )
            elif self.image_mode != "required" or self.profiles.image is None:
                raise ValueError(
                    "legacy generated knowledge workflow requires the pinned image role"
                )
        elif self.request_name == "KNOWLEDGE_ANALYSIS_REQUEST":
            analysis_image_mode = (
                "required"
                if isinstance(self.analysis_request, KnowledgeAnalysisRequestV9)
                else "skip"
            )
            if (
                self.analysis_request is None
                or self.image_mode != analysis_image_mode
                or any(
                    value is not None
                    for value in (
                        self.content_pack,
                        self.profiles,
                        self.source_intake,
                        self.registry_intent,
                        self.item_brief,
                        self.stimulus_asset,
                        self.execution_preset_key,
                    )
                )
            ):
                raise ValueError(
                    "knowledge analysis requires one pinned request, matching image mode, "
                    "and no item fields"
                )
            if self.legacy_extraction_request is not None:
                raise ValueError("knowledge analysis cannot include a legacy extraction request")
            if self.legacy_editorial_compatibility_request is not None:
                raise ValueError(
                    "knowledge analysis cannot include an editorial compatibility request"
                )
        elif self.request_name == "LEGACY_ITEM_EXTRACTION_REQUEST":
            if (
                self.legacy_extraction_request is None
                or self.analysis_request is not None
                or self.image_mode != "skip"
                or any(
                    value is not None
                    for value in (
                        self.content_pack,
                        self.profiles,
                        self.source_intake,
                        self.registry_intent,
                        self.item_brief,
                        self.stimulus_asset,
                        self.execution_preset_key,
                        self.educational_retrieval,
                    )
                )
            ):
                raise ValueError(
                    "legacy item extraction requires one pinned request and no item fields"
                )
            if self.legacy_editorial_compatibility_request is not None:
                raise ValueError(
                    "legacy item extraction cannot include an editorial compatibility request"
                )
        elif self.request_name == "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST":
            if (
                self.legacy_editorial_compatibility_request is None
                or self.analysis_request is not None
                or self.legacy_extraction_request is not None
                or self.image_mode != "skip"
                or any(
                    value is not None
                    for value in (
                        self.content_pack,
                        self.profiles,
                        self.source_intake,
                        self.registry_intent,
                        self.item_brief,
                        self.stimulus_asset,
                        self.execution_preset_key,
                        self.educational_retrieval,
                    )
                )
            ):
                raise ValueError(
                    "legacy editorial compatibility requires one pinned request and no item fields"
                )
        else:
            if (
                self.analysis_request is not None
                or self.legacy_extraction_request is not None
                or self.legacy_editorial_compatibility_request is not None
            ):
                raise ValueError("non-analysis workflow cannot include an analysis request")
            if self.item_brief is not None or self.stimulus_asset is not None:
                raise ValueError("placeholder workflow cannot include a knowledge item brief")
            if self.content_pack is not None and (
                self.source_intake is None or not self.source_intake.batch_ids
            ):
                raise ValueError("placeholder Content Pack requires source Intake evidence")
        return self

    def worker_request(
        self,
    ) -> (
        WorkerRequest
        | KnowledgeAnalysisWorkerRequest
        | LegacyItemExtractionWorkerRequest
        | LegacyItemEditorialCompatibilityWorkerRequest
    ):
        if self.legacy_editorial_compatibility_request is not None:
            return LegacyItemEditorialCompatibilityWorkerRequest(
                compatibility_request=self.legacy_editorial_compatibility_request
            )
        if self.legacy_extraction_request is not None:
            return LegacyItemExtractionWorkerRequest(
                extraction_request=self.legacy_extraction_request
            )
        if self.analysis_request is not None:
            return KnowledgeAnalysisWorkerRequest(analysis_request=self.analysis_request)
        if self.request_name == "KNOWLEDGE_ANALYSIS_REQUEST":
            raise ValueError("knowledge analysis worker request is missing its pinned request")
        if self.request_name == "LEGACY_ITEM_EXTRACTION_REQUEST":
            raise ValueError("legacy extraction worker request is missing its pinned request")
        if self.request_name == "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST":
            raise ValueError("editorial compatibility worker request is missing its pinned request")
        return WorkerRequest(request_name=self.request_name, image_mode=self.image_mode)


class ArtifactSpec(FrozenModel):
    logical_artifact_id: ArtifactId
    revision_id: RevisionId
    file_name: Literal["result.json"] = "result.json"
    media_type: Literal["application/json"] = "application/json"


class ArtifactPointer(FrozenModel):
    step_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    attempt: int = Field(ge=1)
    job_id: JobId
    logical_artifact_id: ArtifactId
    revision_id: RevisionId
    content_hash: Sha256
    result_schema: str = Field(min_length=1, max_length=128)


class RoleWorkerInput(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_version: Literal[
        "workflow-role/1.0.1",
        "workflow-role/1.1.0",
        "workflow-role/1.2.0",
        "workflow-role/1.3.0",
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
        "workflow-role/1.8.0",
        "workflow-role/1.9.0",
        "workflow-role/1.10.0",
        "workflow-role/1.11.0",
        "workflow-role/1.12.0",
        "workflow-role/1.13.0",
        "workflow-role/1.14.0",
        "workflow-role/1.15.0",
        "workflow-role/1.16.0",
        "workflow-role/1.17.0",
        "workflow-role/1.18.0",
        "workflow-role/1.19.0",
        "workflow-role/1.20.0",
    ] = "workflow-role/1.0.1"
    job_id: JobId
    workflow_id: WorkflowId
    step_run_id: StepRunId
    attempt: int = Field(ge=1, le=10)
    role: Literal["authoring", "image", "review", "item_management", "support"]
    request: (
        WorkerRequest
        | KnowledgeAnalysisWorkerRequest
        | LegacyItemExtractionWorkerRequest
        | LegacyItemEditorialCompatibilityWorkerRequest
    )
    upstream_artifacts: tuple[ArtifactPointer, ...]
    artifact: ArtifactSpec

    @field_validator("request", mode="before")
    @classmethod
    def normalize_worker_request(
        cls, value: object
    ) -> (
        WorkerRequest
        | KnowledgeAnalysisWorkerRequest
        | LegacyItemExtractionWorkerRequest
        | LegacyItemEditorialCompatibilityWorkerRequest
    ):
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            raise ValueError("worker request must be an object")
        if value.get("request_name") == "KNOWLEDGE_ANALYSIS_REQUEST":
            return KnowledgeAnalysisWorkerRequest.model_validate(value)
        if value.get("request_name") == "LEGACY_ITEM_EXTRACTION_REQUEST":
            return LegacyItemExtractionWorkerRequest.model_validate(value)
        if value.get("request_name") == "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST":
            return LegacyItemEditorialCompatibilityWorkerRequest.model_validate(value)
        return WorkerRequest.model_validate(
            {"request_name": value.get("request_name"), "image_mode": value.get("image_mode")}
        )


class AuthoringDraft(FrozenModel):
    title: Literal["PLACEHOLDER_CONTENT"]
    body: Literal["PLACEHOLDER_CONTENT"]


class AuthoringMetadata(FrozenModel):
    domain: Literal["placeholder"]


class AuthoringOutput(FrozenModel):
    draft: AuthoringDraft
    metadata: AuthoringMetadata


class ImageSpec(FrozenModel):
    kind: Literal["placeholder"]
    description: Literal["PLACEHOLDER_IMAGE_SPEC"]


class ImageOutput(FrozenModel):
    image_spec: ImageSpec


class Review(FrozenModel):
    decision: Literal["ready_for_human"]
    findings: tuple[Any, ...] = Field(max_length=0)
    summary: Literal["PLACEHOLDER_REVIEW"]


class ReviewOutput(FrozenModel):
    review: Review


class Registration(FrozenModel):
    result: Literal["registered_placeholder"]
    summary: Literal["PLACEHOLDER_REGISTRATION"]


class RegistrationOutput(FrozenModel):
    registration: Registration


class RoleResultBase(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_version: Literal[
        "workflow-role/1.0.1",
        "workflow-role/1.1.0",
        "workflow-role/1.2.0",
        "workflow-role/1.3.0",
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
        "workflow-role/1.8.0",
        "workflow-role/1.9.0",
        "workflow-role/1.10.0",
        "workflow-role/1.11.0",
        "workflow-role/1.12.0",
        "workflow-role/1.13.0",
        "workflow-role/1.14.0",
        "workflow-role/1.15.0",
        "workflow-role/1.16.0",
        "workflow-role/1.17.0",
        "workflow-role/1.18.0",
        "workflow-role/1.19.0",
        "workflow-role/1.20.0",
    ] = "workflow-role/1.0.1"
    job_id: JobId
    workflow_id: WorkflowId
    step_run_id: StepRunId
    status: Literal["ok"] = "ok"
    artifact: ArtifactSpec
    completed_at: UtcDatetime


class AuthoringRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
    role: Literal["authoring"]
    output: AuthoringOutput


class ImageRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
    role: Literal["image"]
    output: ImageOutput


class ReviewRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
    role: Literal["review"]
    output: ReviewOutput


class RegistrationRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
    role: Literal["item_management"]
    output: RegistrationOutput


class KnowledgeAuthoringMetadata(FrozenModel):
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    difficulty: Literal["easy", "medium", "hard"]
    knowledge_source_mode: Literal["general_model_knowledge"]


class KnowledgeAuthoringOutput(FrozenModel):
    content: AssessmentItemContent
    metadata: KnowledgeAuthoringMetadata


class KnowledgeAuthoringRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.1.0"] = "workflow-role/1.1.0"
    role: Literal["authoring"]
    output: KnowledgeAuthoringOutput


class KnowledgeImageReview(FrozenModel):
    decision: Literal["asset_approved"]
    artifact_revision_id: RevisionId
    summary: str = Field(min_length=1, max_length=2000)


class KnowledgeImageOutput(FrozenModel):
    image_review: KnowledgeImageReview


class KnowledgeImageRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.1.0"] = "workflow-role/1.1.0"
    role: Literal["image"]
    output: KnowledgeImageOutput


class ReviewFinding(FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: Literal["info", "warning", "blocking"]
    message: str = Field(min_length=1, max_length=2000)


class KnowledgeReview(FrozenModel):
    decision: Literal["ready_for_human"]
    findings: tuple[ReviewFinding, ...] = Field(max_length=20)
    summary: str = Field(min_length=1, max_length=4000)


class KnowledgeReviewOutput(FrozenModel):
    review: KnowledgeReview


class KnowledgeReviewRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.1.0"] = "workflow-role/1.1.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class KnowledgeRegistration(FrozenModel):
    result: Literal["ready_for_registration"]
    summary: str = Field(min_length=1, max_length=2000)


class KnowledgeRegistrationOutput(FrozenModel):
    registration: KnowledgeRegistration


class KnowledgeRegistrationRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.1.0"] = "workflow-role/1.1.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


class GeneratedImageBrief(FrozenModel):
    kind: Literal["line_graph"] = "line_graph"
    block_id: Literal["block_image"] = "block_image"
    alt_text: str = Field(min_length=1, max_length=1000)
    x_axis_label: str = Field(pattern=r"^[A-Za-z0-9 ()/_-]{1,24}$")
    y_axis_label: str = Field(pattern=r"^[A-Za-z0-9 ()/_-]{1,24}$")
    series_label: str = Field(pattern=r"^[A-Za-z0-9 ()/_-]{1,24}$")
    x_values: tuple[int, ...] = Field(min_length=2, max_length=8)
    y_values: tuple[int, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_series(self) -> GeneratedImageBrief:
        if len(self.x_values) != len(self.y_values):
            raise ValueError("generated image coordinates must have equal lengths")
        if any(value < -1000 or value > 1000 for value in (*self.x_values, *self.y_values)):
            raise ValueError("generated image coordinate is outside the bounded range")
        if any(right <= left for left, right in pairwise(self.x_values)):
            raise ValueError("generated image x coordinates must be strictly increasing")
        return self


def _validate_generated_item_template_contract(
    *,
    stem: ParagraphBlock,
    data_table: TableBlock,
    equation: EquationBlock,
    prompt: ParagraphBlock,
    statements: StatementSetBlock,
    interaction: SingleChoiceInteraction,
    score: ItemScore,
) -> None:
    if stem.purpose != "stem" or data_table.purpose != "data":
        raise ValueError("generated item stem or data table purpose is invalid")
    if equation.purpose != "stimulus" or equation.notation != "hancom-equation-script":
        raise ValueError("generated item equation contract is invalid")
    if prompt.purpose != "prompt":
        raise ValueError("generated item prompt purpose is invalid")
    if len(data_table.headers) != 3 or len(data_table.rows) != 1:
        raise ValueError("generated item table must be 3 columns by 1 row")
    if len(statements.statements) != 3 or tuple(item.label for item in statements.statements) != (
        "ㄱ",
        "ㄴ",
        "ㄷ",
    ):
        raise ValueError("generated item statements must be ordered ㄱ/ㄴ/ㄷ")
    if len(interaction.choices) != 5 or score.points not in {2, 3}:
        raise ValueError("generated item choice or score contract is invalid")


class GeneratedItemDraft(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    locale: Literal["ko-KR"] = "ko-KR"
    title: str = Field(min_length=1, max_length=20_000)
    stem: ParagraphBlock
    data_table: TableBlock
    image_brief: GeneratedImageBrief
    equation: EquationBlock
    prompt: ParagraphBlock
    statements: StatementSetBlock
    interaction: SingleChoiceInteraction
    solution: ItemSolution
    score: ItemScore

    @model_validator(mode="after")
    def validate_template_shape(self) -> GeneratedItemDraft:
        _validate_generated_item_template_contract(
            stem=self.stem,
            data_table=self.data_table,
            equation=self.equation,
            prompt=self.prompt,
            statements=self.statements,
            interaction=self.interaction,
            score=self.score,
        )
        return self


class GeneratedAuthoringOutput(FrozenModel):
    draft: GeneratedItemDraft
    metadata: KnowledgeAuthoringMetadata


class GeneratedAuthoringRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.2.0"] = "workflow-role/1.2.0"
    role: Literal["authoring"]
    output: GeneratedAuthoringOutput


class GeneratedLineGraphDrawing(GeneratedImageBrief):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    stroke_color: Literal["blue", "green", "orange"]
    point_style: Literal["circle", "square"]


class GeneratedImageOutput(FrozenModel):
    drawing: GeneratedLineGraphDrawing
    summary: str = Field(min_length=1, max_length=2000)


class GeneratedImageRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.2.0"] = "workflow-role/1.2.0"
    role: Literal["image"]
    output: GeneratedImageOutput


class GeneratedReviewRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.2.0"] = "workflow-role/1.2.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class GeneratedRegistrationRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.2.0"] = "workflow-role/1.2.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


class GeneratedItemDraftV4(GeneratedItemDraft):
    """Generated draft whose references are safe to assemble into canonical item content."""

    @model_validator(mode="after")
    def validate_canonical_references(self) -> GeneratedItemDraftV4:
        validate_item_reference_contract(
            block_ids=(
                self.stem.block_id,
                self.data_table.block_id,
                self.image_brief.block_id,
                self.equation.block_id,
                self.prompt.block_id,
                self.statements.block_id,
            ),
            statement_ids=tuple(statement.statement_id for statement in self.statements.statements),
            interaction=self.interaction,
            solution=self.solution,
        )
        return self


class GeneratedAuthoringOutputV4(FrozenModel):
    draft: GeneratedItemDraftV4
    metadata: KnowledgeAuthoringMetadata


class GeneratedAuthoringRoleResultV4(RoleResultBase):
    protocol_version: Literal["workflow-role/1.3.0"] = "workflow-role/1.3.0"
    role: Literal["authoring"]
    output: GeneratedAuthoringOutputV4


class GeneratedImageRoleResultV4(RoleResultBase):
    protocol_version: Literal["workflow-role/1.3.0"] = "workflow-role/1.3.0"
    role: Literal["image"]
    output: GeneratedImageOutput


class GeneratedReviewRoleResultV4(RoleResultBase):
    protocol_version: Literal["workflow-role/1.3.0"] = "workflow-role/1.3.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class GeneratedRegistrationRoleResultV4(RoleResultBase):
    protocol_version: Literal["workflow-role/1.3.0"] = "workflow-role/1.3.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


class GeneratedLineGraphImageBriefV5(GeneratedImageBrief):
    production_route: Literal["DETERMINISTIC_SVG"] = "DETERMINISTIC_SVG"
    background_style: Literal["WHITE", "GRID", "PAPER"] = "WHITE"


class _GeneratedVectorImageBriefBase(FrozenModel):
    kind: Literal["diagram", "apparatus", "map", "particle_model", "natural_scene", "composite"]
    background_style: Literal["WHITE", "GRID", "PAPER"]
    block_id: Literal["block_image"] = "block_image"
    alt_text: str = Field(min_length=1, max_length=1000)
    scene_description: str = Field(min_length=1, max_length=4000)
    scientific_constraints: tuple[str, ...] = Field(min_length=1, max_length=16)
    required_labels: tuple[str, ...] = Field(max_length=16)

    @field_validator("alt_text", "scene_description", mode="after")
    @classmethod
    def safe_vector_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_safe_generated_vector_text(value, allow_layout=True):
            raise ValueError("generated vector text contains unsafe whitespace or controls")
        return value

    @field_validator("scientific_constraints", mode="after")
    @classmethod
    def safe_scientific_constraints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("generated vector text values must be unique")
        for value in values:
            if (
                not value
                or len(value) > 500
                or not _is_safe_generated_vector_text(value, allow_layout=False)
            ):
                raise ValueError("generated vector text value is unsafe")
        return values

    @field_validator("required_labels", mode="after")
    @classmethod
    def safe_required_labels(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("generated vector labels must be unique")
        if any(
            not value
            or len(value) > 64
            or not _is_safe_generated_vector_text(value, allow_layout=False)
            for value in values
        ):
            raise ValueError("generated vector label is unsafe")
        return values


class GeneratedVectorImageBriefV5(_GeneratedVectorImageBriefBase):
    production_route: Literal[
        "DETERMINISTIC_SVG", "LOCAL_GENERATIVE_BACKGROUND", "HUMAN_REVIEWED_BACKGROUND"
    ]
    generation_prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=2000)

    @field_validator("generation_prompt", "negative_prompt", mode="after")
    @classmethod
    def safe_generation_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_safe_generated_vector_text(value, allow_layout=True):
            raise ValueError("generated vector text contains unsafe whitespace or controls")
        return value


def _is_safe_generated_vector_text(value: str, *, allow_layout: bool) -> bool:
    if value != value.strip() or value != unicodedata.normalize("NFC", value):
        return False
    return all(
        (allow_layout and character in "\n\t")
        or not unicodedata.category(character).startswith("C")
        for character in value
    )


GeneratedImageBriefV5 = Annotated[
    GeneratedLineGraphImageBriefV5 | GeneratedVectorImageBriefV5,
    Field(discriminator="kind"),
]


class GeneratedItemDraftV5(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    locale: Literal["ko-KR"] = "ko-KR"
    title: str = Field(min_length=1, max_length=20_000)
    stem: ParagraphBlock
    data_table: TableBlock
    image_brief: GeneratedImageBriefV5
    equation: EquationBlock
    prompt: ParagraphBlock
    statements: StatementSetBlock
    interaction: SingleChoiceInteraction
    solution: ItemSolution
    score: ItemScore

    @model_validator(mode="after")
    def validate_template_and_references(self) -> GeneratedItemDraftV5:
        _validate_generated_item_template_contract(
            stem=self.stem,
            data_table=self.data_table,
            equation=self.equation,
            prompt=self.prompt,
            statements=self.statements,
            interaction=self.interaction,
            score=self.score,
        )
        validate_item_reference_contract(
            block_ids=(
                self.stem.block_id,
                self.data_table.block_id,
                self.image_brief.block_id,
                self.equation.block_id,
                self.prompt.block_id,
                self.statements.block_id,
            ),
            statement_ids=tuple(statement.statement_id for statement in self.statements.statements),
            interaction=self.interaction,
            solution=self.solution,
        )
        return self


class GeneratedAuthoringOutputV5(FrozenModel):
    draft: GeneratedItemDraftV5
    metadata: KnowledgeAuthoringMetadata


class GeneratedAuthoringRoleResultV5(RoleResultBase):
    protocol_version: Literal["workflow-role/1.12.0"] = "workflow-role/1.12.0"
    role: Literal["authoring"]
    output: GeneratedAuthoringOutputV5


class GeneratedLineGraphDrawingV5(GeneratedLineGraphImageBriefV5):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    stroke_color: Literal["blue", "green", "orange"]
    point_style: Literal["circle", "square"]


class GeneratedVectorDrawingV5(GeneratedVectorImageBriefV5):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    svg_overlay: str = Field(min_length=64, max_length=65_536)


GeneratedDrawingV5 = Annotated[
    GeneratedLineGraphDrawingV5 | GeneratedVectorDrawingV5,
    Field(discriminator="kind"),
]


class GeneratedImageOutputV5(FrozenModel):
    drawing: GeneratedDrawingV5
    summary: str = Field(min_length=1, max_length=2000)


class GeneratedImageRoleResultV5(RoleResultBase):
    protocol_version: Literal["workflow-role/1.12.0"] = "workflow-role/1.12.0"
    role: Literal["image"]
    output: GeneratedImageOutputV5


class GeneratedReviewRoleResultV5(RoleResultBase):
    protocol_version: Literal["workflow-role/1.12.0"] = "workflow-role/1.12.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class GeneratedRegistrationRoleResultV5(RoleResultBase):
    protocol_version: Literal["workflow-role/1.12.0"] = "workflow-role/1.12.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


DeterministicImageRouteReason = Literal[
    "DATA_VISUALIZATION",
    "SCIENTIFIC_SCHEMATIC",
    "GEOMETRIC_DIAGRAM",
    "MAP_OR_SPATIAL_DIAGRAM",
]
HybridImageRouteReason = Literal[
    "HUMAN_OR_ANIMAL_REQUIRED",
    "ORGANIC_OBJECT_REQUIRED",
    "REALISTIC_NATURAL_SCENE_REQUIRED",
    "COMPLEX_NATURAL_TEXTURE_REQUIRED",
]
ImageRouteReason = DeterministicImageRouteReason | HybridImageRouteReason

_DETERMINISTIC_IMAGE_ROUTE_REASONS = frozenset(
    {
        "DATA_VISUALIZATION",
        "SCIENTIFIC_SCHEMATIC",
        "GEOMETRIC_DIAGRAM",
        "MAP_OR_SPATIAL_DIAGRAM",
    }
)
_HYBRID_IMAGE_ROUTE_REASONS = frozenset(
    {
        "HUMAN_OR_ANIMAL_REQUIRED",
        "ORGANIC_OBJECT_REQUIRED",
        "REALISTIC_NATURAL_SCENE_REQUIRED",
        "COMPLEX_NATURAL_TEXTURE_REQUIRED",
    }
)


class GeneratedLineGraphImageBriefV6(GeneratedLineGraphImageBriefV5):
    route_reason: Literal["DATA_VISUALIZATION"] = "DATA_VISUALIZATION"


class GeneratedVectorImageBriefV6(_GeneratedVectorImageBriefBase):
    production_route: Literal["DETERMINISTIC_SVG", "HYBRID_LOCAL_GENERATIVE"]
    route_reason: ImageRouteReason
    generation_prompt: str | None = Field(default=None, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=2000)

    @field_validator("generation_prompt", "negative_prompt", mode="after")
    @classmethod
    def safe_generation_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_safe_generated_vector_text(value, allow_layout=True):
            raise ValueError("generated vector text contains unsafe whitespace or controls")
        return value

    @model_validator(mode="after")
    def validate_route_plan(self) -> GeneratedVectorImageBriefV6:
        if self.production_route == "DETERMINISTIC_SVG":
            if self.route_reason not in _DETERMINISTIC_IMAGE_ROUTE_REASONS:
                raise ValueError("deterministic image route reason is invalid")
            if self.generation_prompt is not None or self.negative_prompt is not None:
                raise ValueError("deterministic image route cannot declare generation prompts")
        else:
            if self.route_reason not in _HYBRID_IMAGE_ROUTE_REASONS:
                raise ValueError("hybrid image route reason is invalid")
            if self.kind not in {"natural_scene", "composite"}:
                raise ValueError("hybrid image route requires a natural scene or composite")
            if self.generation_prompt is None:
                raise ValueError("hybrid image route requires a generation prompt")
        return self


GeneratedImageBriefV6 = Annotated[
    GeneratedLineGraphImageBriefV6 | GeneratedVectorImageBriefV6,
    Field(discriminator="kind"),
]


class GeneratedItemDraftV6(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    locale: Literal["ko-KR"] = "ko-KR"
    title: str = Field(min_length=1, max_length=20_000)
    stem: ParagraphBlock
    data_table: TableBlock
    image_brief: GeneratedImageBriefV6
    equation: EquationBlock
    prompt: ParagraphBlock
    statements: StatementSetBlock
    interaction: SingleChoiceInteraction
    solution: ItemSolution
    score: ItemScore

    @model_validator(mode="after")
    def validate_template_and_references(self) -> GeneratedItemDraftV6:
        _validate_generated_item_template_contract(
            stem=self.stem,
            data_table=self.data_table,
            equation=self.equation,
            prompt=self.prompt,
            statements=self.statements,
            interaction=self.interaction,
            score=self.score,
        )
        validate_item_reference_contract(
            block_ids=(
                self.stem.block_id,
                self.data_table.block_id,
                self.image_brief.block_id,
                self.equation.block_id,
                self.prompt.block_id,
                self.statements.block_id,
            ),
            statement_ids=tuple(statement.statement_id for statement in self.statements.statements),
            interaction=self.interaction,
            solution=self.solution,
        )
        return self


class GeneratedAuthoringOutputV6(FrozenModel):
    draft: GeneratedItemDraftV6
    metadata: KnowledgeAuthoringMetadata


class GeneratedAuthoringRoleResultV6(RoleResultBase):
    protocol_version: Literal["workflow-role/1.13.0"] = "workflow-role/1.13.0"
    role: Literal["authoring"]
    output: GeneratedAuthoringOutputV6


class GeneratedLineGraphDrawingV6(GeneratedLineGraphImageBriefV6):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    stroke_color: Literal["blue", "green", "orange"]
    point_style: Literal["circle", "square"]


class GeneratedVectorDrawingV6(GeneratedVectorImageBriefV6):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    svg_overlay: str = Field(min_length=64, max_length=65_536)


GeneratedDrawingV6 = Annotated[
    GeneratedLineGraphDrawingV6 | GeneratedVectorDrawingV6,
    Field(discriminator="kind"),
]


class GeneratedImageOutputV6(FrozenModel):
    drawing: GeneratedDrawingV6
    summary: str = Field(min_length=1, max_length=2000)


class GeneratedImageRoleResultV6(RoleResultBase):
    protocol_version: Literal["workflow-role/1.13.0"] = "workflow-role/1.13.0"
    role: Literal["image"]
    output: GeneratedImageOutputV6


class GeneratedReviewRoleResultV6(RoleResultBase):
    protocol_version: Literal["workflow-role/1.13.0"] = "workflow-role/1.13.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class GeneratedRegistrationRoleResultV6(RoleResultBase):
    protocol_version: Literal["workflow-role/1.13.0"] = "workflow-role/1.13.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


class ContentTeamAuthoringOutputV7(FrozenModel):
    """No fixed table/image/equation cardinality; the editorial contract owns the shape."""

    draft: AssessmentItemContentV2
    metadata: KnowledgeAuthoringMetadata


class ContentTeamAuthoringRoleResultV7(RoleResultBase):
    protocol_version: Literal["workflow-role/1.15.0"] = "workflow-role/1.15.0"
    role: Literal["authoring"]
    output: ContentTeamAuthoringOutputV7


class ContentTeamReviewRoleResultV7(RoleResultBase):
    protocol_version: Literal["workflow-role/1.15.0"] = "workflow-role/1.15.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class ContentTeamRegistrationRoleResultV7(RoleResultBase):
    protocol_version: Literal["workflow-role/1.15.0"] = "workflow-role/1.15.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX = (
    "아래의 요청사항에 대한 문제의 그림을 그려줘. 내가 소스에 넣어둔 이미지 규칙을 잊지 말고 지켜"
)


class ContentTeamAuthoringRoleResultV8(RoleResultBase):
    protocol_version: Literal["workflow-role/1.17.0"] = "workflow-role/1.17.0"
    role: Literal["authoring"]
    output: ContentTeamAuthoringOutputV7


class ContentTeamIllustrationDrawingV8(FrozenModel):
    visual_ordinal: int = Field(ge=0, le=1)
    label: Literal["", "(가)", "(나)"]
    illustration_prompt: str = Field(min_length=1, max_length=4000)
    drawing: GeneratedDrawingV6

    @field_validator("illustration_prompt", mode="after")
    @classmethod
    def exact_content_team_prefix(cls, value: str) -> str:
        if not value.startswith(CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX):
            raise ValueError("content-team illustration prompt prefix is missing")
        if not value.removeprefix(CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX).strip():
            raise ValueError("content-team illustration prompt details are missing")
        if not _is_safe_generated_vector_text(value, allow_layout=True):
            raise ValueError("content-team illustration prompt is unsafe")
        return value

    @model_validator(mode="after")
    def bind_hybrid_provider_prompt(self) -> ContentTeamIllustrationDrawingV8:
        if (
            isinstance(self.drawing, GeneratedVectorDrawingV6)
            and self.drawing.production_route == "HYBRID_LOCAL_GENERATIVE"
            and self.drawing.generation_prompt != self.illustration_prompt
        ):
            raise ValueError("hybrid generation prompt differs from the content-team prompt")
        return self


class ContentTeamImageOutputV8(FrozenModel):
    drawings: tuple[ContentTeamIllustrationDrawingV8, ...] = Field(min_length=1, max_length=2)
    summary: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered_unique_slots(self) -> ContentTeamImageOutputV8:
        ordinals = tuple(item.visual_ordinal for item in self.drawings)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("content-team image slots must be unique and ordered")
        return self


class ContentTeamImageRoleResultV8(RoleResultBase):
    protocol_version: Literal["workflow-role/1.17.0"] = "workflow-role/1.17.0"
    role: Literal["image"]
    output: ContentTeamImageOutputV8


class ContentTeamReviewRoleResultV8(RoleResultBase):
    protocol_version: Literal["workflow-role/1.17.0"] = "workflow-role/1.17.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class ContentTeamRegistrationRoleResultV8(RoleResultBase):
    protocol_version: Literal["workflow-role/1.17.0"] = "workflow-role/1.17.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


class KnowledgeAuthoringMetadataV2(FrozenModel):
    """Truthful worker provenance for general and Graph-backed generation."""

    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    difficulty: Literal["easy", "medium", "hard"]
    knowledge_source_mode: Literal["general_model_knowledge", "graph_grounded"]


class ContentTeamAuthoringOutputV9(FrozenModel):
    draft: AssessmentItemContentV3
    metadata: KnowledgeAuthoringMetadataV2


class ContentTeamAuthoringRoleResultV9(RoleResultBase):
    protocol_version: Literal["workflow-role/1.19.0"] = "workflow-role/1.19.0"
    role: Literal["authoring"]
    output: ContentTeamAuthoringOutputV9


class GeneratedVectorDrawingV9(GeneratedVectorDrawingV6):
    """Worker-accepted SVG already proven by the renderer's authoritative grammar."""

    svg_overlay: str = Field(
        min_length=64,
        max_length=65_536,
        json_schema_extra={
            "not": {
                "anyOf": [
                    {"pattern": "[Uu][Rr][Ll]\\s*\\("},
                    {"pattern": "<[Ll][Ii][Nn][Ee][Aa][Rr][Gg][Rr][Aa][Dd][Ii][Ee][Nn][Tt]\\b"},
                    {"pattern": "<[Rr][Aa][Dd][Ii][Aa][Ll][Gg][Rr][Aa][Dd][Ii][Ee][Nn][Tt]\\b"},
                    {"pattern": "<[Ss][Cc][Rr][Ii][Pp][Tt]\\b"},
                    {"pattern": "<[Ss][Tt][Yy][Ll][Ee]\\b"},
                    {"pattern": "<[Ff][Oo][Rr][Ee][Ii][Gg][Nn][Oo][Bb][Jj][Ee][Cc][Tt]\\b"},
                    {"pattern": "<[Ii][Mm][Aa][Gg][Ee]\\b"},
                ]
            }
        },
    )

    @model_validator(mode="after")
    def safe_svg_subset(self) -> GeneratedVectorDrawingV9:
        sanitize_svg_overlay(self.svg_overlay, self.required_labels)
        return self


GeneratedDrawingV9 = Annotated[
    GeneratedLineGraphDrawingV6 | GeneratedVectorDrawingV9,
    Field(discriminator="kind"),
]


class ContentTeamIllustrationDrawingV9(ContentTeamIllustrationDrawingV8):
    drawing: GeneratedDrawingV9


class ContentTeamImageOutputV9(FrozenModel):
    drawings: tuple[ContentTeamIllustrationDrawingV9, ...] = Field(min_length=1, max_length=2)
    summary: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered_unique_slots(self) -> ContentTeamImageOutputV9:
        ordinals = tuple(item.visual_ordinal for item in self.drawings)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("content-team image slots must be unique and ordered")
        return self


class ContentTeamImageRoleResultV9(RoleResultBase):
    protocol_version: Literal["workflow-role/1.19.0"] = "workflow-role/1.19.0"
    role: Literal["image"]
    output: ContentTeamImageOutputV9


class ContentTeamReviewRoleResultV9(RoleResultBase):
    protocol_version: Literal["workflow-role/1.19.0"] = "workflow-role/1.19.0"
    role: Literal["review"]
    output: KnowledgeReviewOutput


class ContentTeamRegistrationRoleResultV9(RoleResultBase):
    protocol_version: Literal["workflow-role/1.19.0"] = "workflow-role/1.19.0"
    role: Literal["item_management"]
    output: KnowledgeRegistrationOutput


DraftJsonPointer = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
    ),
]


class EvidenceUsageCitationV1(FrozenModel):
    """One manifest entry and the exact authored draft locations it influenced."""

    evidence_id: str = Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    application: Literal[
        "CONCEPT_GROUNDING",
        "STRUCTURE_PATTERN",
        "AVOID_COPY_CHECK",
    ]
    application_description: str = Field(min_length=1, max_length=2000)
    draft_json_paths: tuple[DraftJsonPointer, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def canonical_members(self) -> EvidenceUsageCitationV1:
        for values, label in (
            (self.anchor_ids, "anchor IDs"),
            (self.draft_json_paths, "draft JSON pointers"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"evidence usage {label} must be sorted and unique")
        return self


class EvidenceUsageV1(FrozenModel):
    """Manifest-visible Graph evidence identity and canonical, bounded citations."""

    schema_version: Literal["evidence-usage/1.0"] = "evidence-usage/1.0"
    evidence_bundle_id: str = Field(pattern=r"^evidence_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    evidence_manifest_sha256: Sha256
    evidence_context_sha256: Sha256
    citations: tuple[EvidenceUsageCitationV1, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_positive_citation_set(self) -> EvidenceUsageV1:
        evidence_ids = tuple(item.evidence_id for item in self.citations)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("evidence usage citations must have sorted unique evidence IDs")
        if not any(
            item.application in {"CONCEPT_GROUNDING", "STRUCTURE_PATTERN"}
            for item in self.citations
        ):
            raise ValueError("Graph-grounded evidence usage requires a positive citation")
        return self


class ContentTeamAuthoringOutputV10(FrozenModel):
    draft: AssessmentItemContentV3
    metadata: KnowledgeAuthoringMetadataV2
    evidence_usage: EvidenceUsageV1 | None

    @model_validator(mode="after")
    def truthful_evidence_mode(self) -> ContentTeamAuthoringOutputV10:
        grounded = self.metadata.knowledge_source_mode == "graph_grounded"
        if grounded != (self.evidence_usage is not None):
            raise ValueError("authoring evidence usage must match knowledge source mode")
        return self


class ContentTeamAuthoringRoleResultV10(RoleResultBase):
    protocol_version: Literal["workflow-role/1.20.0"] = "workflow-role/1.20.0"
    role: Literal["authoring"]
    output: ContentTeamAuthoringOutputV10


class ContentTeamImageRoleResultV10(ContentTeamImageRoleResultV9):
    protocol_version: Literal["workflow-role/1.20.0"] = "workflow-role/1.20.0"  # type: ignore[assignment]


class EvidenceAuthoringArtifactPointerV1(FrozenModel):
    logical_artifact_id: ArtifactId
    revision_id: RevisionId
    content_hash: Sha256
    result_schema: Literal["authoring-result@10.0"] = "authoring-result@10.0"


class EvidenceUsageReviewAttestationV1(FrozenModel):
    schema_version: Literal["evidence-usage-review-attestation/1.0"] = (
        "evidence-usage-review-attestation/1.0"
    )
    decision: Literal["VERIFIED"] = "VERIFIED"
    authoring_artifact: EvidenceAuthoringArtifactPointerV1
    citations: tuple[EvidenceUsageCitationV1, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_citation_receipt(self) -> EvidenceUsageReviewAttestationV1:
        evidence_ids = tuple(item.evidence_id for item in self.citations)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("reviewed citations must have sorted unique evidence IDs")
        return self


class KnowledgeReviewOutputV10(FrozenModel):
    review: KnowledgeReview
    evidence_usage_attestation: EvidenceUsageReviewAttestationV1 | None


class ContentTeamReviewRoleResultV10(RoleResultBase):
    protocol_version: Literal["workflow-role/1.20.0"] = "workflow-role/1.20.0"
    role: Literal["review"]
    output: KnowledgeReviewOutputV10


class ContentTeamRegistrationRoleResultV10(ContentTeamRegistrationRoleResultV9):
    protocol_version: Literal["workflow-role/1.20.0"] = "workflow-role/1.20.0"  # type: ignore[assignment]


class KnowledgeAnalysisProposalOutput(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposal


class KnowledgeAnalysisProposalRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.4.0"] = "workflow-role/1.4.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutput


class KnowledgeAnalysisProposalRoleResultV2(RoleResultBase):
    protocol_version: Literal["workflow-role/1.5.0"] = "workflow-role/1.5.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutput


class KnowledgeAnalysisProposalOutputV2(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV2


class KnowledgeAnalysisProposalRoleResultV3(RoleResultBase):
    protocol_version: Literal["workflow-role/1.6.0"] = "workflow-role/1.6.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV2


class KnowledgeAnalysisProposalOutputV3(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV3


class KnowledgeAnalysisProposalRoleResultV4(RoleResultBase):
    protocol_version: Literal["workflow-role/1.7.0"] = "workflow-role/1.7.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV3


class KnowledgeAnalysisProposalOutputV4(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV4


class KnowledgeAnalysisProposalRoleResultV5(RoleResultBase):
    protocol_version: Literal["workflow-role/1.8.0"] = "workflow-role/1.8.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV4


class KnowledgeAnalysisProposalRoleResultV6(RoleResultBase):
    protocol_version: Literal["workflow-role/1.9.0"] = "workflow-role/1.9.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV4


class KnowledgeAnalysisProposalOutputV5(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV5


class KnowledgeAnalysisProposalRoleResultV7(RoleResultBase):
    protocol_version: Literal["workflow-role/1.10.0"] = "workflow-role/1.10.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV5


class KnowledgeAnalysisProposalOutputV6(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV6


class KnowledgeAnalysisProposalRoleResultV8(RoleResultBase):
    protocol_version: Literal["workflow-role/1.11.0"] = "workflow-role/1.11.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV6


class KnowledgeAnalysisProposalOutputV7(FrozenModel):
    proposal: KnowledgeAnalysisWorkerProposalV7


class KnowledgeAnalysisProposalRoleResultV9(RoleResultBase):
    protocol_version: Literal["workflow-role/1.18.0"] = "workflow-role/1.18.0"
    role: Literal["support"] = "support"
    output: KnowledgeAnalysisProposalOutputV7


class LegacyItemExtractionOutput(FrozenModel):
    extraction_result: LegacyItemExtractionResult


class LegacyItemExtractionRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.14.0"] = "workflow-role/1.14.0"
    role: Literal["support"] = "support"
    output: LegacyItemExtractionOutput


class LegacyItemEditorialCompatibilityOutput(FrozenModel):
    proposal: LegacyItemEditorialCompatibilityProposal


class LegacyItemEditorialCompatibilityRoleResult(RoleResultBase):
    protocol_version: Literal["workflow-role/1.16.0"] = "workflow-role/1.16.0"
    role: Literal["support"] = "support"
    output: LegacyItemEditorialCompatibilityOutput


RoleResult = (
    AuthoringRoleResult
    | ImageRoleResult
    | ReviewRoleResult
    | RegistrationRoleResult
    | KnowledgeAuthoringRoleResult
    | KnowledgeImageRoleResult
    | KnowledgeReviewRoleResult
    | KnowledgeRegistrationRoleResult
    | GeneratedAuthoringRoleResult
    | GeneratedImageRoleResult
    | GeneratedReviewRoleResult
    | GeneratedRegistrationRoleResult
    | GeneratedAuthoringRoleResultV4
    | GeneratedImageRoleResultV4
    | GeneratedReviewRoleResultV4
    | GeneratedRegistrationRoleResultV4
    | GeneratedAuthoringRoleResultV5
    | GeneratedImageRoleResultV5
    | GeneratedReviewRoleResultV5
    | GeneratedRegistrationRoleResultV5
    | GeneratedAuthoringRoleResultV6
    | GeneratedImageRoleResultV6
    | GeneratedReviewRoleResultV6
    | GeneratedRegistrationRoleResultV6
    | ContentTeamAuthoringRoleResultV7
    | ContentTeamReviewRoleResultV7
    | ContentTeamRegistrationRoleResultV7
    | ContentTeamAuthoringRoleResultV8
    | ContentTeamImageRoleResultV8
    | ContentTeamReviewRoleResultV8
    | ContentTeamRegistrationRoleResultV8
    | ContentTeamAuthoringRoleResultV9
    | ContentTeamImageRoleResultV9
    | ContentTeamReviewRoleResultV9
    | ContentTeamRegistrationRoleResultV9
    | ContentTeamAuthoringRoleResultV10
    | ContentTeamImageRoleResultV10
    | ContentTeamReviewRoleResultV10
    | ContentTeamRegistrationRoleResultV10
    | KnowledgeAnalysisProposalRoleResult
    | KnowledgeAnalysisProposalRoleResultV2
    | KnowledgeAnalysisProposalRoleResultV3
    | KnowledgeAnalysisProposalRoleResultV4
    | KnowledgeAnalysisProposalRoleResultV5
    | KnowledgeAnalysisProposalRoleResultV6
    | KnowledgeAnalysisProposalRoleResultV7
    | KnowledgeAnalysisProposalRoleResultV8
    | KnowledgeAnalysisProposalRoleResultV9
    | LegacyItemExtractionRoleResult
    | LegacyItemEditorialCompatibilityRoleResult
)
