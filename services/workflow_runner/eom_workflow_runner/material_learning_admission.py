"""Admit only the exact material/support purpose and the real Catalog source owner."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition_data
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from eom_workflow.models import AgentStep, TerminalStep
from sqlalchemy.orm import Session

from eom_workflow_runner.actor_authorization import OPERATOR_ACTOR_PATTERN
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowDefinitionRecord

MATERIAL_LEARNING_WORKFLOW_KEY = "material-learning"


class MaterialLearningSourceAuthorizer(Protocol):
    def reauthorize(
        self, session: Session, *, operator_id: str, work: MaterialLearningWork
    ) -> MaterialLearningWork:
        """Resolve current caller/source authority without changing an input pin."""
        ...


def validate_material_learning_definition(definition: WorkflowDefinitionRecord) -> None:
    try:
        compiled = compile_definition_data(
            definition.canonical_definition, definition.source_path, {"support"}
        )
        step = compiled.steps_by_key.get("learn")
        terminal = compiled.steps_by_key.get("complete")
        if (
            definition.definition_key != MATERIAL_LEARNING_WORKFLOW_KEY
            or definition.definition_version != "1.0.0"
            or not definition.active
            or compiled.sha256 != definition.definition_hash
            or compiled.definition.definition_key != definition.definition_key
            or compiled.definition.definition_version != definition.definition_version
            or compiled.definition.schema_version != definition.schema_version
            or compiled.definition.start_step != "learn"
            or compiled.definition.limits.max_step_attempts != 1
            or compiled.definition.limits.max_rework_cycles != 0
            or len(compiled.definition.steps) != 2
            or not isinstance(step, AgentStep)
            or step.worker_role != "support"
            or step.result_schema != "material-learning-result@1.0"
            or step.on_success != "complete"
            or not isinstance(terminal, TerminalStep)
            or terminal.terminal_status != "COMPLETED"
        ):
            raise ValueError("material definition differs")
    except ValueError as error:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "material learning requires its exact admitted one-step definition",
        ) from error


def validate_material_learning_submission(
    definition: WorkflowDefinitionRecord,
    request: MaterialLearningWorkflowRequest,
    *,
    actor_type: str,
    actor_id: str,
) -> MaterialLearningWorkflowRequest:
    if actor_type != "human" or OPERATOR_ACTOR_PATTERN.fullmatch(actor_id) is None:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "material learning requires its real Operator",
        )
    validate_material_learning_definition(definition)
    return MaterialLearningWorkflowRequest.model_validate(request.model_dump(mode="json"))


def reauthorize_material_learning_submission(
    session: Session,
    *,
    request: MaterialLearningWorkflowRequest,
    operator_id: str,
    source_authorizer: MaterialLearningSourceAuthorizer,
) -> None:
    try:
        actual = source_authorizer.reauthorize(
            session, operator_id=operator_id, work=request.work_input
        )
        if actual != request.work_input:
            raise ValueError("material source changed")
    except ValueError as error:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "material source authorization must preserve the exact original input",
        ) from error


def material_learning_fingerprint(
    definition: WorkflowDefinitionRecord,
    request: MaterialLearningWorkflowRequest,
    *,
    operator_id: str,
) -> str:
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_sha256": definition.definition_hash,
            "operator_id": operator_id,
            "request": request.model_dump(mode="json"),
        }
    )
