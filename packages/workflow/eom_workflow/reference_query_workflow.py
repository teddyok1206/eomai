"""Fixed QUERY definition values; current admission and native launch are separate boundaries."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import FrozenModel
from pydantic import ConfigDict, ValidationError, model_validator

from eom_workflow.models import TerminalStep, WorkflowLimits
from eom_workflow.schemas import (
    ReferenceQueryContractError,
    validate_reference_query_message,
    validate_reference_query_public_message,
)

REFERENCE_QUERY_WORKFLOW_KEY: Final = "local-embedding-reference-query"
REFERENCE_QUERY_WORKFLOW_VERSION: Final = "1.0.0"
REFERENCE_QUERY_EXECUTION_PROTOCOL: Final = "reference-query/1.0"
REFERENCE_QUERY_PUBLIC_EXECUTION_PROTOCOL: Final = "reference-query/2.0"
REFERENCE_QUERY_RESULT_SCHEMA: Final = "embedding-reference-query-result@1.0"
REFERENCE_QUERY_EXECUTION_PROTOCOLS: Final = (
    REFERENCE_QUERY_EXECUTION_PROTOCOL,
    REFERENCE_QUERY_PUBLIC_EXECUTION_PROTOCOL,
)
REFERENCE_QUERY_RESULT_SCHEMAS: Final = (
    REFERENCE_QUERY_RESULT_SCHEMA,
    "embedding-reference-query-result@2.0",
)


class ReferenceQueryStep(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    key: Literal["encode_reference_query"] = "encode_reference_query"
    type: Literal["application"] = "application"
    operation: Literal["BUILD_REFERENCE_QUERY_EMBEDDINGS"] = "BUILD_REFERENCE_QUERY_EMBEDDINGS"
    result_schema: Literal["embedding-reference-query-result@1.0"] = REFERENCE_QUERY_RESULT_SCHEMA
    on_success: Literal["complete"] = "complete"


class ReferenceQueryWorkflowDefinition(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["1.2"] = "1.2"
    definition_key: Literal["local-embedding-reference-query"] = REFERENCE_QUERY_WORKFLOW_KEY
    definition_version: Literal["1.0.0"] = REFERENCE_QUERY_WORKFLOW_VERSION
    start_step: Literal["encode_reference_query"] = "encode_reference_query"
    limits: WorkflowLimits
    steps: tuple[ReferenceQueryStep, TerminalStep]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_message("definition", value)
        return raw_similarity_contract_value(value)


def parse_reference_query_workflow_definition(value: object) -> ReferenceQueryWorkflowDefinition:
    validate_reference_query_message("definition", value)
    try:
        return ReferenceQueryWorkflowDefinition.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


class PublicSolutionReferenceQueryStep(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    key: Literal["encode_reference_query"] = "encode_reference_query"
    type: Literal["application"] = "application"
    operation: Literal["BUILD_REFERENCE_QUERY_EMBEDDINGS"] = "BUILD_REFERENCE_QUERY_EMBEDDINGS"
    result_schema: Literal["embedding-reference-query-result@2.0"] = (
        "embedding-reference-query-result@2.0"
    )
    on_success: Literal["complete"] = "complete"


class PublicSolutionReferenceQueryWorkflowDefinition(FrozenModel):
    """Successor value for the same runner operation, not a separate execution engine."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["1.2"] = "1.2"
    definition_key: Literal["local-embedding-reference-query"] = REFERENCE_QUERY_WORKFLOW_KEY
    definition_version: Literal["2.0.0"] = "2.0.0"
    start_step: Literal["encode_reference_query"] = "encode_reference_query"
    limits: WorkflowLimits
    steps: tuple[PublicSolutionReferenceQueryStep, TerminalStep]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        validate_reference_query_public_message("definition", value)
        return raw_similarity_contract_value(value)


def parse_public_solution_reference_query_workflow_definition(
    value: object,
) -> PublicSolutionReferenceQueryWorkflowDefinition:
    validate_reference_query_public_message("definition", value)
    try:
        return PublicSolutionReferenceQueryWorkflowDefinition.model_validate(value)
    except ValidationError:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


SupportedReferenceQueryWorkflowDefinition: TypeAlias = (  # noqa: UP040 -- runtime dispatch
    ReferenceQueryWorkflowDefinition | PublicSolutionReferenceQueryWorkflowDefinition
)


def parse_supported_reference_query_workflow_definition(
    value: object,
) -> SupportedReferenceQueryWorkflowDefinition:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("definition_version") == "2.0.0":
        return parse_public_solution_reference_query_workflow_definition(document)
    return parse_reference_query_workflow_definition(document)
