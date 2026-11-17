"""Admit one exact concept phase under the actual private-question/source owner."""

from typing import Protocol

from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition_data
from eom_workflow.kakao_concept_request import (
    CONCEPT_RESULT_SCHEMA,
    KakaoConceptWork,
    KakaoConceptWorkflowRequest,
)
from eom_workflow.models import AgentStep, TerminalStep
from sqlalchemy.orm import Session

from .actor_authorization import OPERATOR_ACTOR_PATTERN
from .errors import WorkflowError, WorkflowErrorCode
from .models import WorkflowDefinitionRecord

KAKAO_CONCEPT_WORKFLOW_KEY = "kakao-concepts"


class KakaoConceptSourceAuthorizer(Protocol):
    def reauthorize(
        self, session: Session, *, operator_id: str, work: KakaoConceptWork
    ) -> KakaoConceptWork:
        """Current question/binding/source access and immutable exact input; no worker grant."""
        ...


def validate_kakao_concept_submission(
    definition: WorkflowDefinitionRecord,
    request: KakaoConceptWorkflowRequest,
    *,
    actor_type: str,
    actor_id: str,
) -> KakaoConceptWorkflowRequest:
    if actor_type != "human" or OPERATOR_ACTOR_PATTERN.fullmatch(actor_id) is None:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "concept assistance requires the actual Operator",
        )
    try:
        compiled = compile_definition_data(
            definition.canonical_definition, definition.source_path, {"support"}
        )
        step = compiled.steps_by_key.get("assist")
        terminal = compiled.steps_by_key.get("complete")
        if (
            definition.definition_key != KAKAO_CONCEPT_WORKFLOW_KEY
            or definition.definition_version != "1.0.0"
            or not definition.active
            or compiled.sha256 != definition.definition_hash
            or compiled.definition.definition_key != definition.definition_key
            or compiled.definition.definition_version != definition.definition_version
            or compiled.definition.schema_version != definition.schema_version
            or compiled.definition.start_step != "assist"
            or compiled.definition.limits.max_step_attempts != 1
            or compiled.definition.limits.max_rework_cycles != 0
            or len(compiled.definition.steps) != 2
            or not isinstance(step, AgentStep)
            or step.worker_role != "support"
            or step.result_schema != CONCEPT_RESULT_SCHEMA
            or step.on_success != "complete"
            or not isinstance(terminal, TerminalStep)
            or terminal.terminal_status != "COMPLETED"
        ):
            raise ValueError("concept definition differs")
        return KakaoConceptWorkflowRequest.model_validate(request.model_dump(mode="json"))
    except ValueError as error:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "concept assistance requires its exact admitted one-step definition",
        ) from error


def reauthorize_kakao_concept_submission(
    session: Session,
    *,
    request: KakaoConceptWorkflowRequest,
    operator_id: str,
    source_authorizer: KakaoConceptSourceAuthorizer,
) -> None:
    try:
        actual = source_authorizer.reauthorize(
            session, operator_id=operator_id, work=request.work_input
        )
        if actual != request.work_input:
            raise ValueError("concept source changed")
    except ValueError as error:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "concept source authority must preserve its exact original input",
        ) from error


def kakao_concept_fingerprint(
    definition: WorkflowDefinitionRecord,
    request: KakaoConceptWorkflowRequest,
    *,
    operator_id: str,
) -> str:
    return content_sha256(
        dict(
            definition_key=definition.definition_key,
            definition_version=definition.definition_version,
            definition_sha256=definition.definition_hash,
            operator_id=operator_id,
            request=request.model_dump(mode="json"),
        )
    )
