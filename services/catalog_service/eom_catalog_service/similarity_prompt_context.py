"""Derive auxiliary-reference availability from one exact persisted plan, never user input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow.control_plane import ResolvedExecutionPlanV19, ResolvedExecutionPlanV20
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.similarity_control import (
    MAX_SIMILARITY_EXECUTION_PLAN_BYTES,
    SupportedSimilarityExecutionPlan,
    parse_post_registration_grounded_plan,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

SIMILARITY_REFERENCE_PACK_VERSION = "1.20.17"
SimilarityReferenceMode = Literal["NOT_OFFERED", "PINNED_REFERENCE_CONTEXT"]
_PLAN_PIN_KEYS = frozenset({"plan_id", "plan_sha256", "preset_id", "preset_revision_id"})


@dataclass(frozen=True, slots=True)
class SimilarityPromptContext:
    """Small immutable render value; the plan pin also participates in context hashing."""

    reference_mode: SimilarityReferenceMode
    plan_id: str
    plan_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "reference_mode": self.reference_mode,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
        }


def requires_similarity_prompt_context(
    workflow: WorkflowInstanceRecord, step: WorkflowStepRunRecord
) -> bool:
    snapshot = workflow.runtime_context.get("content_pack")
    return (
        isinstance(snapshot, dict)
        and snapshot.get("pack_key") == "generated-knowledge-item"
        and snapshot.get("version") == SIMILARITY_REFERENCE_PACK_VERSION
        and getattr(step, "worker_role", None) in {"authoring", "review"}
    )


def read_similarity_prompt_context(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    pack_release_id: str,
) -> SimilarityPromptContext:
    """Metadata declaration only: source permission and actual files are checked at staging."""
    snapshot = workflow.runtime_context.get("content_pack")
    pin = workflow.runtime_context.get("execution_plan")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("pack_key") != "generated-knowledge-item"
        or snapshot.get("version") != SIMILARITY_REFERENCE_PACK_VERSION
        or snapshot.get("release_id") != pack_release_id
        or step.worker_role not in {"authoring", "review"}
        or not isinstance(pin, dict)
        or set(pin) != _PLAN_PIN_KEYS
        or any(type(value) is not str for value in pin.values())
    ):
        raise ValueError("SIMILARITY_PROMPT_BINDING_INVALID")
    record = session.get(ResolvedExecutionPlanRecord, pin["plan_id"])
    if record is None:
        raise ValueError("SIMILARITY_PROMPT_PLAN_MISSING")
    try:
        document = record.canonical_document
        if not isinstance(document, dict) or (
            len(canonical_json_bytes(document)) > MAX_SIMILARITY_EXECUTION_PLAN_BYTES
        ):
            raise ValueError("SIMILARITY_PROMPT_PLAN_TOO_LARGE")
        plan: ResolvedExecutionPlanV19 | ResolvedExecutionPlanV20 | SupportedSimilarityExecutionPlan
        if document.get("schema_version") == "resolved-execution-plan/20.0":
            validate_control_contract("resolved-execution-plan-v20", document)
            plan = ResolvedExecutionPlanV20.model_validate(document)
        else:
            plan = parse_post_registration_grounded_plan(document)
    except (ValueError, TypeError, SchemaError):
        raise ValueError("SIMILARITY_PROMPT_PLAN_INVALID") from None
    if (
        plan.plan_id != record.plan_id
        or plan.plan_id != pin["plan_id"]
        or plan.workflow_id != record.workflow_id
        or plan.workflow_id != workflow.workflow_id
        or plan.workflow_definition_key != workflow.definition_key
        or plan.workflow_definition_version != workflow.definition_version
        or plan.plan_sha256 != record.plan_sha256
        or plan.plan_sha256 != pin["plan_sha256"]
        or plan.preset_id != record.preset_id
        or plan.preset_id != pin["preset_id"]
        or plan.preset_revision_id != record.preset_revision_id
        or plan.preset_revision_id != pin["preset_revision_id"]
        or plan.content_pack_release_id != pack_release_id
        or plan.content_pack_sha256 != snapshot.get("release_sha256")
    ):
        raise ValueError("SIMILARITY_PROMPT_PLAN_MISMATCH")
    matching = tuple(item for item in plan.steps if item.step_key == step.step_key)
    if len(matching) != 1 or matching[0].role != step.worker_role:
        raise ValueError("SIMILARITY_PROMPT_STEP_MISMATCH")
    return SimilarityPromptContext(
        reference_mode=(
            "PINNED_REFERENCE_CONTEXT"
            if isinstance(plan, SupportedSimilarityExecutionPlan)
            else "NOT_OFFERED"
        ),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
    )
