"""Exact source-plan4 service request, not a new numerical execution protocol."""

from typing import ClassVar, Literal

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_operator_identity import LocalIndexingServiceReference

from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_embedding_request_v3 import (
    PublicSolutionWorkflowRequestBody,
    public_solution_request_service,
    validate_public_solution_request_reference_values,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF,
    LocalEmbeddingSourcePlanV4,
    parse_local_embedding_source_plan_v4,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_REQUEST_V4_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-request/4.0"
)


class LocalEmbeddingWorkflowRequestV4(PublicSolutionWorkflowRequestBody):
    _source_plan_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF
    schema_version: Literal["local-embedding-workflow-request/4.0"] = (
        "local-embedding-workflow-request/4.0"
    )


def parse_local_embedding_workflow_request_v4(value: object) -> LocalEmbeddingWorkflowRequestV4:
    try:
        document = raw_public_solution_contract_value(value)
        validate_local_embedding_admission_message("registered-public-request", document)
        return LocalEmbeddingWorkflowRequestV4.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_request_service_v4(
    request: LocalEmbeddingWorkflowRequestV4,
) -> LocalIndexingServiceReference:
    return public_solution_request_service(parse_local_embedding_workflow_request_v4(request))


def validate_local_embedding_request_references_v4(
    request: LocalEmbeddingWorkflowRequestV4,
    plan: LocalEmbeddingSourcePlanV4,
    policy: LocalEmbeddingServiceExecutionPolicy,
) -> None:
    request = parse_local_embedding_workflow_request_v4(request)
    plan = parse_local_embedding_source_plan_v4(plan)
    validate_public_solution_request_reference_values(request, plan, policy)
