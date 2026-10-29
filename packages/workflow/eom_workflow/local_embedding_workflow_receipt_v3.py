"""Public-report receipt3 and carrier3 preserve exact registration, not authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionEmbeddingIndex
from eom_catalog_contracts.public_solution_embedding_registry import (
    PublicSolutionIndexRegistrationResult,
    RegisterPublicSolutionIndexCommand,
    validate_public_solution_registration_result,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.local_embedding_encoding_ownership_v3 import (
    LocalEmbeddingLaunchAssociationV3,
    parse_local_embedding_launch_association_v3,
    validate_local_embedding_launch_association_v3,
)
from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingServiceExecutionPolicy,
)
from eom_workflow.local_embedding_request_v3 import (
    LocalEmbeddingWorkflowRequestV3,
    parse_local_embedding_workflow_request_v3,
    validate_local_embedding_request_references_v3,
)
from eom_workflow.local_embedding_source_plan_v3 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
    validate_local_embedding_selected_index_coverage_v3,
)
from eom_workflow.local_embedding_workflow_receipt import (
    MAX_LOCAL_EMBEDDING_STEP_OUTPUT_BYTES,
    MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
    validate_local_embedding_completion_metadata,
)
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V3_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-receipt/3.0"
)
LOCAL_EMBEDDING_STEP_OUTPUT_V3_SCHEMA_REF = "eom://schemas/workflow/local-embedding-step-output/3.0"


@dataclass(frozen=True, slots=True)
class ResolvedNativeIndexCoverageV3:
    """Actual owner-resolved values, never source/current-head authority."""

    index: PublicSolutionEmbeddingIndex
    eligible_sources: tuple[PopulationSource, ...]
    previous: tuple[ArtifactMemberPointer, PublicSolutionEmbeddingIndex] | None = None


class LocalEmbeddingStepOutputV3(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-step-output/3.0"] = "local-embedding-step-output/3.0"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["incremental-embedding-result@1.0"] = (
        "incremental-embedding-result@1.0"
    )
    receipt_schema: Literal["eom://schemas/workflow/local-embedding-workflow-receipt/3.0"] = (
        "eom://schemas/workflow/local-embedding-workflow-receipt/3.0"
    )
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="after")
    def exact_carrier(self) -> LocalEmbeddingStepOutputV3:
        if (
            self.receipt.member_path != "receipt.json"
            or self.receipt.schema_ref != self.receipt_schema
            or self.receipt.media_type != "application/json"
        ):
            raise ValueError("native completion receipt member differs")
        validate_local_embedding_completion_metadata(
            self, "output_sha256", MAX_LOCAL_EMBEDDING_STEP_OUTPUT_BYTES
        )
        return self


class LocalEmbeddingWorkflowReceiptV3(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-workflow-receipt/3.0"] = (
        "local-embedding-workflow-receipt/3.0"
    )
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_id: WorkflowId
    workflow_definition_sha256: Sha256
    workflow_request_sha256: Sha256
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["incremental-embedding-result@1.0"] = (
        "incremental-embedding-result@1.0"
    )
    native_launch_job_id: JobId | None
    launch_association_sha256: Sha256 | None
    registration_command: RegisterPublicSolutionIndexCommand
    registration_result: PublicSolutionIndexRegistrationResult
    registration_observed_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_historical_observation(self) -> LocalEmbeddingWorkflowReceiptV3:
        if (
            self.source_plan.member_path != "source-plan.json"
            or self.source_plan.schema_ref != LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF
            or self.source_plan.media_type != "application/json"
            or (self.native_launch_job_id is None) != (self.launch_association_sha256 is None)
        ):
            raise ValueError("public-solution completion plan or launch pair differs")
        validate_public_solution_registration_result(
            self.registration_command, self.registration_result
        )
        if (
            not self.registration_command.requested_at
            <= self.registration_result.registered_at
            <= self.registration_observed_at
        ):
            raise ValueError("public-solution registration observation precedes its provenance")
        validate_local_embedding_completion_metadata(
            self, "receipt_sha256", MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES
        )
        return self


def parse_local_embedding_workflow_receipt_v3(value: object) -> LocalEmbeddingWorkflowReceiptV3:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("public-completion", document)
        return LocalEmbeddingWorkflowReceiptV3.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_step_output_v3(value: object) -> LocalEmbeddingStepOutputV3:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("public-completion", document)
        return LocalEmbeddingStepOutputV3.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_workflow_receipt_v3_bytes(value: LocalEmbeddingWorkflowReceiptV3) -> bytes:
    return canonical_json_bytes(
        parse_local_embedding_workflow_receipt_v3(value).model_dump(mode="json")
    )


def local_embedding_step_output_v3_bytes(value: LocalEmbeddingStepOutputV3) -> bytes:
    return canonical_json_bytes(parse_local_embedding_step_output_v3(value).model_dump(mode="json"))


def validate_local_embedding_step_output_v3(
    output: LocalEmbeddingStepOutputV3, receipt: LocalEmbeddingWorkflowReceiptV3
) -> LocalEmbeddingStepOutputV3:
    output = parse_local_embedding_step_output_v3(output)
    receipt = parse_local_embedding_workflow_receipt_v3(receipt)
    if any(
        getattr(output, field) != getattr(receipt, field)
        for field in (
            "workflow_id",
            "step_run_id",
            "step_key",
            "attempt",
            "receipt_owner_job_id",
            "execution_result_schema",
            "receipt_sha256",
        )
    ) or output.receipt.sha256 != sha256_bytes(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ):
        raise ValueError("public-solution completion carrier differs from its exact receipt")
    return output


def validate_local_embedding_workflow_receipt_v3(
    receipt: LocalEmbeddingWorkflowReceiptV3,
    request: LocalEmbeddingWorkflowRequestV3,
    plan: LocalEmbeddingSourcePlanV3,
    policy: LocalEmbeddingServiceExecutionPolicy,
    *,
    workflow_id: str,
    step_run_id: str,
    receipt_owner_job_id: str,
    launch_association: LocalEmbeddingLaunchAssociationV3 | None,
    owned_input: IncrementalEmbeddingInput | None,
    index_coverage: ResolvedNativeIndexCoverageV3,
) -> LocalEmbeddingWorkflowReceiptV3:
    """Exact historical closure; fresh IAM/physical rows/commit/lease stay with owners."""
    receipt = parse_local_embedding_workflow_receipt_v3(receipt)
    request = parse_local_embedding_workflow_request_v3(request)
    plan = parse_local_embedding_source_plan_v3(plan)
    validate_local_embedding_request_references_v3(request, plan, policy)
    expected_ids = (
        TypeAdapter(WorkflowId).validate_python(workflow_id),
        TypeAdapter(StepRunId).validate_python(step_run_id),
        TypeAdapter(JobId).validate_python(receipt_owner_job_id),
    )
    command = receipt.registration_command
    if (
        (receipt.workflow_id, receipt.step_run_id, receipt.receipt_owner_job_id) != expected_ids
        or receipt.workflow_definition_sha256 != request.workflow_definition_sha256
        or receipt.workflow_request_sha256 != request.request_sha256
        or receipt.source_plan != request.source_plan
        or receipt.source_plan_sha256 != plan.plan_sha256
        or not plan.demands
        or command.corpus_id != plan.corpus_id
        or command.namespace != plan.namespace
        or command.graph_snapshot != plan.graph_snapshot
        or command.policy_revision_id != plan.access_policy_revision_id
        or command.policy_sha256 != plan.access_policy_sha256
        or (launch_association is None) != (owned_input is None)
        or (launch_association is None) != (receipt.native_launch_job_id is None)
    ):
        raise ValueError("public-solution receipt differs from exact resolved Workflow context")
    index = PublicSolutionEmbeddingIndex.model_validate(
        raw_similarity_contract_value(index_coverage.index)
    )
    source_adapter: TypeAdapter[PopulationSource] = TypeAdapter(PopulationSource)
    if (
        type(index_coverage.eligible_sources) is not tuple
        or not 1 <= len(index_coverage.eligible_sources) <= 16384
    ):
        raise ValueError("public-solution completion eligible population is invalid")
    sources = {
        source.item_revision_id: source_adapter.validate_python(
            raw_similarity_contract_value(source)
        )
        for source in index_coverage.eligible_sources
    }
    if (
        len(sources) != len(index_coverage.eligible_sources)
        or command.source_set_sha256 != population_sha256(index_coverage.eligible_sources)
        or command.eligible_source_count != len(sources)
        or command.binding_count != len(index.bindings)
        or command.binding_set_sha256
        != content_sha256([binding.binding_sha256 for binding in index.bindings])
        or command.index_id != index.index_id
        or command.index_revision_id != index.index_revision_id
        or command.index_sha256 != index.index_sha256
        or command.index_manifest.sha256
        != sha256_bytes(canonical_json_bytes(index.model_dump(mode="json")))
        or any(sources.get(source.item_revision_id) != source for source in plan.sources)
        or any(
            sources.get(binding.source.item_revision_id) != binding.source
            or binding.graph_snapshot != plan.graph_snapshot
            or binding.policy_revision_id != plan.access_policy_revision_id
            or binding.policy_sha256 != plan.access_policy_sha256
            for binding in index.bindings
        )
    ):
        raise ValueError("public-solution completion full index or corpus differs")
    validate_local_embedding_selected_index_coverage_v3(plan, index)
    if launch_association is not None:
        assert owned_input is not None
        association = parse_local_embedding_launch_association_v3(launch_association)
        validate_local_embedding_launch_association_v3(
            association, plan, owned_input, request.resource_profile, request.request_sha256
        )
        intent = association.intent
        if (
            receipt.native_launch_job_id != intent.native_launch_job_id
            or receipt.launch_association_sha256 != association.association_sha256
            or any(
                getattr(receipt, field) != getattr(intent, field)
                for field in ("workflow_id", "step_run_id", "step_key", "attempt", "source_plan")
            )
        ):
            raise ValueError("public-solution receipt differs from original launch association")
    return receipt
