"""Fixed mixed INDEX definition values; static admission is not runtime authority."""

from __future__ import annotations

from typing import Final, Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from pydantic import ValidationError, model_validator

from eom_workflow.local_embedding_workflow import LocalEmbeddingStep
from eom_workflow.models import TerminalStep, WorkflowLimits
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    load_local_embedding_admission_schema,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_WORKFLOW_V2_KEY: Final = "local-embedding-index"
LOCAL_EMBEDDING_WORKFLOW_V2_VERSION: Final = "2.0.0"


class LocalEmbeddingWorkflowDefinitionV2(NativeEmbeddingContract):
    """Independent metadata successor; never an instance of definition1."""

    schema_version: Literal["1.4"] = "1.4"
    definition_key: Literal["local-embedding-index"] = LOCAL_EMBEDDING_WORKFLOW_V2_KEY
    definition_version: Literal["2.0.0"] = LOCAL_EMBEDDING_WORKFLOW_V2_VERSION
    start_step: Literal["encode_batch"] = "encode_batch"
    limits: WorkflowLimits
    steps: tuple[LocalEmbeddingStep, TerminalStep]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("definition-v2", document)
        return document


def load_local_embedding_definition_v2_schema() -> dict[str, object]:
    """Read an isolated copy of the installed, hash-pinned schema resource."""
    return load_local_embedding_admission_schema("definition-v2")


def parse_local_embedding_workflow_definition_v2(
    value: object,
) -> LocalEmbeddingWorkflowDefinitionV2:
    try:
        document = raw_similarity_contract_value(value)
        return LocalEmbeddingWorkflowDefinitionV2.model_validate(document)
    except (ValueError, TypeError, ValidationError):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None
