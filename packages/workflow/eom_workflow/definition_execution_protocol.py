"""One authoritative protocol calculation for typed Workflow definitions."""

from __future__ import annotations

from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LocalEmbeddingWorkflowDefinition,
)
from eom_workflow.models import AgentStep, WorkflowDefinition
from eom_workflow.reference_query_workflow import (
    REFERENCE_QUERY_EXECUTION_PROTOCOL,
    ReferenceQueryWorkflowDefinition,
    parse_reference_query_workflow_definition,
)
from eom_workflow.schemas import result_schema_protocol

type ExecutionWorkflowDefinition = (
    WorkflowDefinition | LocalEmbeddingWorkflowDefinition | ReferenceQueryWorkflowDefinition
)


class DefinitionExecutionProtocolError(ValueError):
    """A malformed definition cannot select another execution family."""


def definition_execution_protocol(definition: ExecutionWorkflowDefinition) -> str:
    """Calculate protocol identity, not admission, availability or worker authority.

    Native embedding is deliberately not looked up in the Codex role schema map.
    Revalidation also protects repository callers from a forged frozen copy. Old
    definitions keep their exact single-agent-family rule and meaning.
    """
    if isinstance(definition, ReferenceQueryWorkflowDefinition):
        try:
            parse_reference_query_workflow_definition(definition)
        except ValueError:
            raise DefinitionExecutionProtocolError(
                "reference query definition execution protocol is invalid"
            ) from None
        return REFERENCE_QUERY_EXECUTION_PROTOCOL
    if isinstance(definition, LocalEmbeddingWorkflowDefinition):
        try:
            LocalEmbeddingWorkflowDefinition.model_validate(
                definition.model_dump(mode="json", warnings="none")
            )
        except ValueError:
            raise DefinitionExecutionProtocolError(
                "local embedding definition execution protocol is invalid"
            ) from None
        return LOCAL_EMBEDDING_EXECUTION_PROTOCOL
    if not isinstance(definition, WorkflowDefinition):
        raise DefinitionExecutionProtocolError("workflow definition type is unsupported")
    try:
        checked = WorkflowDefinition.model_validate(
            definition.model_dump(mode="json", exclude_none=True, warnings="none")
        )
    except ValueError:
        raise DefinitionExecutionProtocolError(
            "workflow definition role protocol is invalid"
        ) from None
    protocols = {
        result_schema_protocol(step.result_schema)
        for step in checked.steps
        if isinstance(step, AgentStep)
    }
    if len(protocols) != 1:
        raise DefinitionExecutionProtocolError("agent steps must use one role protocol version")
    return next(iter(protocols))
