"""Immutable workflow definition and placeholder role contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any, Literal

from eom_catalog_contracts import (
    AssessmentItemContent,
    EquationBlock,
    ItemScore,
    ItemSolution,
    ParagraphBlock,
    SingleChoiceInteraction,
    StatementSetBlock,
    TableBlock,
    validate_item_reference_contract,
)
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


class WorkflowLimits(FrozenModel):
    max_rework_cycles: int = Field(ge=0, le=10)
    max_step_attempts: int = Field(ge=1, le=10)


class AgentStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["agent"]
    worker_role: Literal["authoring", "image", "review", "item_management"]
    result_schema: str = Field(pattern=r"^[a-z][a-z-]+-result@[0-9]+\.[0-9]+$")
    on_success: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")


class DecisionStep(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["decision"]
    operator: DecisionOperator
    field: str = Field(pattern=r"^(?:/(?:[^~/]|~[01])*)+$")
    branches: dict[str, str] = Field(min_length=1, max_length=10)


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


class StimulusAssetSelection(FrozenModel):
    asset_key: Literal["eom-question-template-reference-v1"]


class ContentPackSelection(FrozenModel):
    pack_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    environment: Literal["development", "test"]


class WorkflowProfiles(FrozenModel):
    authoring: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    review: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    image: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
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
    ]
    image_mode: Literal["skip", "required"]
    content_pack: ContentPackSelection | None = None
    profiles: WorkflowProfiles | None = None
    source_intake: SourceIntakeSelection | None = None
    registry_intent: RegistryIntent | None = None
    item_brief: ItemBrief | None = None
    stimulus_asset: StimulusAssetSelection | None = None

    @model_validator(mode="after")
    def validate_catalog_request(self) -> WorkflowRequest:
        required_catalog_values = (self.content_pack, self.profiles, self.registry_intent)
        if any(value is not None for value in required_catalog_values) and not all(
            value is not None for value in required_catalog_values
        ):
            raise ValueError("catalog workflow request fields must be supplied together")
        if self.source_intake is not None and self.content_pack is None:
            raise ValueError("source Intake pointers require a Content Pack")
        if self.request_name == "KNOWLEDGE_ITEM_REQUEST":
            if (
                self.content_pack is None
                or self.item_brief is None
                or self.stimulus_asset is None
                or self.image_mode != "required"
            ):
                raise ValueError(
                    "knowledge item workflow requires pack, brief, fixed stimulus, and image"
                )
        elif self.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST":
            if (
                self.content_pack is None
                or self.item_brief is None
                or self.stimulus_asset is not None
                or self.image_mode != "required"
                or (self.source_intake is not None and self.source_intake.batch_ids)
            ):
                raise ValueError(
                    "generated knowledge workflow requires source-free pack, brief, and image role"
                )
        else:
            if self.item_brief is not None or self.stimulus_asset is not None:
                raise ValueError("placeholder workflow cannot include a knowledge item brief")
            if self.content_pack is not None and (
                self.source_intake is None or not self.source_intake.batch_ids
            ):
                raise ValueError("placeholder Content Pack requires source Intake evidence")
        return self

    def worker_request(self) -> WorkerRequest:
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
    ] = "workflow-role/1.0.1"
    job_id: JobId
    workflow_id: WorkflowId
    step_run_id: StepRunId
    attempt: int = Field(ge=1, le=10)
    role: Literal["authoring", "image", "review", "item_management"]
    request: WorkerRequest
    upstream_artifacts: tuple[ArtifactPointer, ...]
    artifact: ArtifactSpec

    @field_validator("request", mode="before")
    @classmethod
    def normalize_worker_request(cls, value: object) -> WorkerRequest:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            raise ValueError("worker request must be an object")
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
        if self.stem.purpose != "stem" or self.data_table.purpose != "data":
            raise ValueError("generated item stem or data table purpose is invalid")
        if self.equation.purpose != "stimulus" or self.equation.notation != (
            "hancom-equation-script"
        ):
            raise ValueError("generated item equation contract is invalid")
        if self.prompt.purpose != "prompt":
            raise ValueError("generated item prompt purpose is invalid")
        if len(self.data_table.headers) != 3 or len(self.data_table.rows) != 1:
            raise ValueError("generated item table must be 3 columns by 1 row")
        if len(self.statements.statements) != 3 or tuple(
            item.label for item in self.statements.statements
        ) != ("ㄱ", "ㄴ", "ㄷ"):
            raise ValueError("generated item statements must be ordered ㄱ/ㄴ/ㄷ")
        if len(self.interaction.choices) != 5 or self.score.points not in {2, 3}:
            raise ValueError("generated item choice or score contract is invalid")
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
)
