"""Immutable workflow definition and placeholder role contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

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
    request_name: Literal["PLACEHOLDER_REQUEST"]
    image_mode: Literal["skip", "required"]


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
        min_length=1, max_length=100
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


class WorkflowRequest(WorkerRequest):
    content_pack: ContentPackSelection | None = None
    profiles: WorkflowProfiles | None = None
    source_intake: SourceIntakeSelection | None = None
    registry_intent: RegistryIntent | None = None

    @model_validator(mode="after")
    def validate_catalog_request(self) -> WorkflowRequest:
        values = (
            self.content_pack,
            self.profiles,
            self.source_intake,
            self.registry_intent,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("catalog workflow request fields must be supplied together")
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
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
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
    protocol_version: Literal["workflow-role/1.0.1"] = "workflow-role/1.0.1"
    job_id: JobId
    workflow_id: WorkflowId
    step_run_id: StepRunId
    status: Literal["ok"] = "ok"
    artifact: ArtifactSpec
    completed_at: UtcDatetime


class AuthoringRoleResult(RoleResultBase):
    role: Literal["authoring"]
    output: AuthoringOutput


class ImageRoleResult(RoleResultBase):
    role: Literal["image"]
    output: ImageOutput


class ReviewRoleResult(RoleResultBase):
    role: Literal["review"]
    output: ReviewOutput


class RegistrationRoleResult(RoleResultBase):
    role: Literal["item_management"]
    output: RegistrationOutput


RoleResult = AuthoringRoleResult | ImageRoleResult | ReviewRoleResult | RegistrationRoleResult
