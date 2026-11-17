"""One pinned concept phase on the existing ordinary support capacity pool."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from .control_plane import FrozenModel, ResolvedStepExecution, Sha256, UtcDatetime, WorkflowId
from .kakao_concept_request import KakaoConceptWork


class KakaoConceptExecutionPlan(FrozenModel):
    schema_version: Literal["resolved-execution-plan/42.0"] = "resolved-execution-plan/42.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_ANALYSIS"] = "KNOWLEDGE_ANALYSIS"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["kakao-concepts"] = "kakao-concepts"
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    workflow_definition_sha256: Sha256
    work_input: KakaoConceptWork
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: Literal["42.0.0"] = "42.0.0"
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_source_only_shared_phase(self) -> Self:
        step = self.steps[0]
        if (
            step.step_key != "assist"
            or step.role != "support"
            or step.worker_pool_key != "support"
            or step.reference_bundle is not None
            or step.sandbox != "read-only"
            or step.network != "disabled"
            or step.general_knowledge_mode != "DENIED"
        ):
            raise ValueError("KAKAO_CONCEPT_PLAN_PURPOSE_INVALID")
        if self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("KAKAO_CONCEPT_PLAN_HASH_MISMATCH")
        return self
