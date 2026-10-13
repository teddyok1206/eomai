"""Fixed QUERY definition values; compiler, admission and native launch are unconnected."""

from __future__ import annotations

from typing import Final, Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import FrozenModel
from pydantic import ConfigDict, ValidationError, model_validator

from eom_workflow.models import TerminalStep, WorkflowLimits
from eom_workflow.schemas import ReferenceQueryContractError, validate_reference_query_message

REFERENCE_QUERY_WORKFLOW_KEY: Final = "local-embedding-reference-query"
REFERENCE_QUERY_WORKFLOW_VERSION: Final = "1.0.0"
REFERENCE_QUERY_EXECUTION_PROTOCOL: Final = "reference-query/1.0"
REFERENCE_QUERY_RESULT_SCHEMA: Final = "embedding-reference-query-result@1.0"


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
