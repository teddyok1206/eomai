"""Purpose and current-source admission for a creative learning Workflow.

This boundary persists only an authorized request; it does not enqueue work or
grant a worker access to Catalog, Artifact storage, or the original documents.
"""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.external_item_learning_work import (
    EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition_data
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.models import AgentStep, TerminalStep, WorkflowRequest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy.orm import Session

from eom_workflow_runner.actor_authorization import OPERATOR_ACTOR_PATTERN
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowDefinitionRecord

EXTERNAL_ITEM_LEARNING_WORKFLOW_KEY = "external-item-learning"


class ExternalItemLearningSourceAuthorizer(Protocol):
    def reauthorize(
        self, session: Session, *, operator_id: str, source: ExternalItemLearningSource
    ) -> ExternalItemLearningSource:
        """Resolve current Catalog authority for the exact source, never latest."""
        ...


def validate_external_item_learning_definition(definition: WorkflowDefinitionRecord) -> None:
    """One authoritative rule for control preparation and source submission."""

    try:
        profile = creative_learning_profile(definition.definition_version)
        compiled = compile_definition_data(
            definition.canonical_definition, definition.source_path, {"support"}
        )
        extraction = compiled.steps_by_key.get("extract")
        terminal = compiled.steps_by_key.get("complete")
        if (
            definition.definition_key != EXTERNAL_ITEM_LEARNING_WORKFLOW_KEY
            or not definition.active
            or compiled.sha256 != definition.definition_hash
            or compiled.definition.definition_key != definition.definition_key
            or compiled.definition.definition_version != definition.definition_version
            or compiled.definition.schema_version != definition.schema_version
            or compiled.definition.start_step != "extract"
            or compiled.definition.limits.max_step_attempts != 1
            or compiled.definition.limits.max_rework_cycles != 0
            or len(compiled.definition.steps) != 2
            or not isinstance(extraction, AgentStep)
            or extraction.worker_role != "support"
            or extraction.result_schema != profile.result_schema
            or extraction.on_success != "complete"
            or not isinstance(terminal, TerminalStep)
            or terminal.terminal_status != "COMPLETED"
        ):
            raise ValueError("creative definition differs")
    except ValueError as exc:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "creative exact one-shot definition is required",
        ) from exc


def validate_external_item_learning_submission(
    *,
    definition: WorkflowDefinitionRecord,
    request: WorkflowRequest,
    actor_type: str,
    actor_id: str,
) -> WorkflowRequest:
    """Validate identity and the compiled one-step DAG before any source read."""

    if actor_type != "human" or OPERATOR_ACTOR_PATTERN.fullmatch(actor_id) is None:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "creative learning requires its real Operator owner",
        )
    try:
        profile = creative_learning_profile(definition.definition_version)
    except ValueError as exc:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "unsupported creative learning Workflow version",
        ) from exc
    if (
        definition.definition_key != EXTERNAL_ITEM_LEARNING_WORKFLOW_KEY
        or not definition.active
        or request.request_name != "EXTERNAL_ITEM_LEARNING_REQUEST"
        or request.execution_preset_key != profile.preset_key
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "creative learning request and active definition must match",
        )
    try:
        checked = WorkflowRequest.model_validate(request.model_dump(mode="json"))
        work = checked.external_item_learning_work
        if work is None:
            raise ValueError("missing creative work input")
        validate_contract(EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA, work.model_dump(mode="json"))
        validate_external_item_learning_definition(definition)
    except (ValueError, JsonSchemaValidationError) as exc:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "creative learning requires its exact compiled definition and work input",
        ) from exc
    return checked


def reauthorize_external_item_learning_submission(
    session: Session,
    *,
    request: WorkflowRequest,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
) -> None:
    work = request.external_item_learning_work
    if work is None:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID, "creative work input is missing"
        )
    try:
        current = source_authorizer.reauthorize(
            session, operator_id=operator_id, source=work.source
        )
        if current != work.source:
            raise ValueError("creative source differs from its pinned input")
    except ValueError as exc:
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "creative learning source authorization failed",
        ) from exc


def external_item_learning_fingerprint(
    definition: WorkflowDefinitionRecord, request: WorkflowRequest, *, operator_id: str
) -> str:
    """Owner-scoped identity; historical generic Workflow hashes stay unchanged."""

    work = request.external_item_learning_work
    if work is None:
        raise ValueError("creative fingerprint requires its pinned input")
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "operator_id": operator_id,
            # A caller-generated request ID is audit identity, not another unit
            # of work over the same source/pages. Different IDs cannot multiply
            # active tasks; replay must still match the original stored request.
            "work_input": work.model_dump(mode="json", exclude={"request_id", "request_sha256"}),
        }
    )
