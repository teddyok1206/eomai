"""Registered full-report completion4, sharing exact historical receipt rules."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingInput
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionEmbeddingIndex
from eom_catalog_contracts.registered_public_solution_index import PublicSolutionEmbeddingIndexV4
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
)
from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_workflow.local_embedding_encoding_ownership_v4 import LocalEmbeddingLaunchAssociationV4
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_embedding_request_v4 import (
    LocalEmbeddingWorkflowRequestV4,
    parse_local_embedding_workflow_request_v4,
    validate_local_embedding_request_references_v4,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF,
    LocalEmbeddingSourcePlanV4,
    parse_local_embedding_source_plan_v4,
)
from eom_workflow.local_embedding_workflow_receipt_v3 import (
    PublicSolutionStepOutputBody,
    PublicSolutionWorkflowReceiptBody,
    validate_public_solution_receipt_context_values,
    validate_public_solution_step_output_values,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V4_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-receipt/4.0"
)
LOCAL_EMBEDDING_STEP_OUTPUT_V4_SCHEMA_REF = "eom://schemas/workflow/local-embedding-step-output/4.0"


@dataclass(frozen=True, slots=True)
class ResolvedNativeIndexCoverageV4:
    index: PublicSolutionEmbeddingIndexV4
    eligible_sources: tuple[PopulationSource, ...]
    previous: (
        tuple[ArtifactMemberPointer, PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4]
        | None
    ) = None


class LocalEmbeddingStepOutputV4(PublicSolutionStepOutputBody):
    _receipt_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V4_SCHEMA_REF
    schema_version: Literal["local-embedding-step-output/4.0"] = "local-embedding-step-output/4.0"
    receipt_schema: Literal["eom://schemas/workflow/local-embedding-workflow-receipt/4.0"] = (
        "eom://schemas/workflow/local-embedding-workflow-receipt/4.0"
    )


class LocalEmbeddingWorkflowReceiptV4(
    PublicSolutionWorkflowReceiptBody[
        RegisterPublicSolutionIndexCommandV4, PublicSolutionIndexRegistrationResultV4
    ]
):
    _source_plan_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF
    schema_version: Literal["local-embedding-workflow-receipt/4.0"] = (
        "local-embedding-workflow-receipt/4.0"
    )


def parse_local_embedding_workflow_receipt_v4(value: object) -> LocalEmbeddingWorkflowReceiptV4:
    try:
        document = raw_public_solution_contract_value(value)
        validate_local_embedding_admission_message("registered-public-completion", document)
        return LocalEmbeddingWorkflowReceiptV4.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_step_output_v4(value: object) -> LocalEmbeddingStepOutputV4:
    try:
        document = raw_public_solution_contract_value(value)
        validate_local_embedding_admission_message("registered-public-completion", document)
        return LocalEmbeddingStepOutputV4.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_workflow_receipt_v4_bytes(value: LocalEmbeddingWorkflowReceiptV4) -> bytes:
    return canonical_json_bytes(
        parse_local_embedding_workflow_receipt_v4(value).model_dump(mode="json")
    )


def local_embedding_step_output_v4_bytes(value: LocalEmbeddingStepOutputV4) -> bytes:
    return canonical_json_bytes(parse_local_embedding_step_output_v4(value).model_dump(mode="json"))


def validate_local_embedding_step_output_v4(
    output: LocalEmbeddingStepOutputV4, receipt: LocalEmbeddingWorkflowReceiptV4
) -> LocalEmbeddingStepOutputV4:
    output = parse_local_embedding_step_output_v4(output)
    receipt = parse_local_embedding_workflow_receipt_v4(receipt)
    validate_public_solution_step_output_values(output, receipt)
    return output


def validate_local_embedding_workflow_receipt_v4(
    receipt: LocalEmbeddingWorkflowReceiptV4,
    request: LocalEmbeddingWorkflowRequestV4,
    plan: LocalEmbeddingSourcePlanV4,
    policy: LocalEmbeddingServiceExecutionPolicy,
    *,
    workflow_id: str,
    step_run_id: str,
    receipt_owner_job_id: str,
    launch_association: LocalEmbeddingLaunchAssociationV4 | None,
    owned_input: IncrementalEmbeddingInput | None,
    index_coverage: ResolvedNativeIndexCoverageV4,
) -> LocalEmbeddingWorkflowReceiptV4:
    receipt = parse_local_embedding_workflow_receipt_v4(receipt)
    request = parse_local_embedding_workflow_request_v4(request)
    plan = parse_local_embedding_source_plan_v4(plan)
    validate_local_embedding_request_references_v4(request, plan, policy)
    index = PublicSolutionEmbeddingIndexV4.model_validate(
        raw_public_solution_contract_value(index_coverage.index)
    )
    validate_public_solution_receipt_context_values(
        receipt,
        request,
        plan,
        index,
        index_coverage.eligible_sources,
        workflow_id=workflow_id,
        step_run_id=step_run_id,
        receipt_owner_job_id=receipt_owner_job_id,
        launch_association=launch_association,
        owned_input=owned_input,
    )
    return receipt
