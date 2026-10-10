"""Purpose-pinned comparison execution values; no runtime or storage ownership."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    InferenceTransferRubricPointer,
    PairComparisonRequest,
    validate_pair_comparison_request_references,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_workflow.control_plane import (
    ControlArtifactPointer,
    FrozenModel,
    InstructionBundleManifest,
    ResolvedStepExecution,
    Sha256,
    UtcDatetime,
    WorkflowId,
)

TRANSFER_RUBRIC_MEMBER = "instructions/transfer-rubric.md"
TRANSFER_RUBRIC_SCHEMA_REF = "eom://schemas/workflow/instruction-member/1.0"


class ResolvedExecutionPlanV21(FrozenModel):
    """One comparison, exact source-derived profile pins and released controls."""

    schema_version: Literal["resolved-execution-plan/21.0"] = "resolved-execution-plan/21.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["CODEX"] = "CODEX"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["item-inference-transfer-comparison"] = (
        "item-inference-transfer-comparison"
    )
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    workflow_definition_sha256: Sha256
    comparison_request_sha256: Sha256
    left_profile: InferenceTransferProfilePointer
    right_profile: InferenceTransferProfilePointer
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requester_permissions_sha256: Sha256
    rubric: InferenceTransferRubricPointer
    rubric_artifact: ControlArtifactPointer
    core_prompt_sha256: Sha256
    prompt_sha256: Sha256
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: Literal["21.0.0"] = "21.0.0"
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_comparison_purpose_and_hash(self) -> ResolvedExecutionPlanV21:
        step = self.steps[0]
        if (
            step.step_key != "compare_pair"
            or step.role != "support"
            or step.worker_pool_key != "customer-support"
            or step.reference_bundle is not None
            or not 30 <= step.timeout_seconds <= 900
            or step.sandbox != "read-only"
            or step.network != "disabled"
            or step.general_knowledge_mode != "DENIED"
        ):
            raise ValueError("inference-transfer plan requires one isolated comparison step")
        if self.left_profile == self.right_profile:
            raise ValueError("inference-transfer plan profiles must be distinct")
        if (
            self.rubric_artifact.logical_name != TRANSFER_RUBRIC_MEMBER
            or self.rubric_artifact.media_type != "text/markdown"
            or self.rubric_artifact.schema_ref != TRANSFER_RUBRIC_SCHEMA_REF
            or self.rubric_artifact.sha256 != self.rubric.rubric_sha256
        ):
            raise ValueError("inference-transfer rubric Artifact pin differs")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("inference-transfer plan hash differs")
        return self


class ResolvedExecutionPlanV22(ResolvedExecutionPlanV21):
    """Same pinned source boundary, explicit three-axis comparison successor."""

    schema_version: Literal["resolved-execution-plan/22.0"] = "resolved-execution-plan/22.0"  # type: ignore[assignment]
    workflow_definition_version: Literal["1.1.0"] = "1.1.0"  # type: ignore[assignment]
    resolver_version: Literal["22.0.0"] = "22.0.0"  # type: ignore[assignment]


def _checked_plan(
    plan: ResolvedExecutionPlanV21 | ResolvedExecutionPlanV22,
) -> ResolvedExecutionPlanV21:
    model = (
        ResolvedExecutionPlanV22
        if isinstance(plan, ResolvedExecutionPlanV22)
        else ResolvedExecutionPlanV21
    )
    return model.model_validate(plan.model_dump(mode="json"))


def validate_inference_transfer_plan_context(
    plan: ResolvedExecutionPlanV21 | ResolvedExecutionPlanV22,
    *,
    comparison: PairComparisonRequest,
    left_profile: InferenceTransferProfile,
    right_profile: InferenceTransferProfile,
    workflow_id: str,
    core_prompt_sha256: str,
    prompt_sha256: str,
) -> None:
    """Check exact small-value closure; the owner must independently authorize sources."""

    # A copied frozen value is not proof that its validators actually ran.
    checked = _checked_plan(plan)
    validate_pair_comparison_request_references(comparison, left_profile, right_profile)
    if (
        checked.workflow_id != workflow_id
        or checked.comparison_request_sha256 != comparison.request_sha256
        or checked.left_profile != comparison.left_profile
        or checked.right_profile != comparison.right_profile
        or checked.rubric != comparison.rubric
        or checked.graph_snapshot != left_profile.source_basis.graph_snapshot
        or checked.graph_snapshot != right_profile.source_basis.graph_snapshot
        or checked.core_prompt_sha256 != core_prompt_sha256
        or checked.prompt_sha256 != prompt_sha256
    ):
        raise ValueError("inference-transfer plan context differs")


def validate_inference_transfer_rubric_instruction(
    plan: ResolvedExecutionPlanV21 | ResolvedExecutionPlanV22,
    instruction: InstructionBundleManifest,
) -> None:
    """Require the exact rubric member in the already resolved released instruction bundle."""

    checked = _checked_plan(plan)
    pointer = checked.steps[0].instruction_bundle
    if (
        instruction.bundle_id != pointer.bundle_id
        or instruction.bundle_revision_id != pointer.bundle_revision_id
        or instruction.state != "RELEASED"
        or content_sha256(instruction.model_dump(mode="json", exclude={"content_sha256"}))
        != instruction.content_sha256
    ):
        raise ValueError("inference-transfer instruction bundle differs")
    matches = tuple(
        component
        for component in instruction.components
        if component.relative_path == TRANSFER_RUBRIC_MEMBER
    )
    if (
        len(matches) != 1
        or matches[0].layer != "ROLE"
        or matches[0].artifact != checked.rubric_artifact
    ):
        raise ValueError("inference-transfer rubric is absent from the exact instruction bundle")
