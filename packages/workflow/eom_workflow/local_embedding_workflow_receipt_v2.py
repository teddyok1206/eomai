"""Mixed receipt2 and carrier2 preserve actual registration, not current authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    IncrementalEmbeddingInput,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_catalog_contracts.mixed_embedding_index import MixedEmbeddingIndexManifest
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
    validate_embedding_registration_result_v2,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.local_embedding_encoding_job import LocalEmbeddingLaunchAssociation
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    LocalEmbeddingLaunchAssociationV2,
    parse_local_embedding_launch_association_v2,
    validate_local_embedding_launch_association_v2,
)
from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingExecutablePolicy,
    LocalEmbeddingServiceExecutionPolicy,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
    parse_local_embedding_workflow_request_v2,
    validate_local_embedding_request_references_v2,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_selected_index_coverage_v2,
)
from eom_workflow.local_embedding_workflow_receipt import (
    MAX_LOCAL_EMBEDDING_STEP_OUTPUT_BYTES,
    MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
    ResolvedNativeIndexCoverage,
    parse_local_embedding_step_output,
    parse_local_embedding_workflow_receipt,
    validate_local_embedding_completion_metadata,
    validate_local_embedding_step_output,
    validate_local_embedding_workflow_receipt,
)
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V2_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-receipt/2.0"
)
LOCAL_EMBEDDING_STEP_OUTPUT_V2_SCHEMA_REF = "eom://schemas/workflow/local-embedding-step-output/2.0"


@dataclass(frozen=True, slots=True)
class ResolvedNativeIndexCoverageV2:
    """Actual owner-resolved values, never source/current-head authority."""

    index: MixedEmbeddingIndexManifest
    eligible_sources: tuple[PopulationSource, ...]
    previous: (
        tuple[ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest] | None
    ) = None


class LocalEmbeddingStepOutputV2(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-step-output/2.0"] = "local-embedding-step-output/2.0"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["incremental-embedding-result@1.0"] = (
        "incremental-embedding-result@1.0"
    )
    receipt_schema: Literal["eom://schemas/workflow/local-embedding-workflow-receipt/2.0"] = (
        "eom://schemas/workflow/local-embedding-workflow-receipt/2.0"
    )
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="after")
    def exact_carrier(self) -> LocalEmbeddingStepOutputV2:
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


class LocalEmbeddingWorkflowReceiptV2(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-workflow-receipt/2.0"] = (
        "local-embedding-workflow-receipt/2.0"
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
    registration_command: RegisterEmbeddingIndexCommandV2
    registration_result: EmbeddingIndexRegistrationResultV2
    registration_observed_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_historical_observation(self) -> LocalEmbeddingWorkflowReceiptV2:
        if (
            self.source_plan.member_path != "source-plan.json"
            or self.source_plan.schema_ref != LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF
            or self.source_plan.media_type != "application/json"
            or (self.native_launch_job_id is None) != (self.launch_association_sha256 is None)
        ):
            raise ValueError("mixed completion plan or launch pair differs")
        validate_embedding_registration_result_v2(
            self.registration_command, self.registration_result
        )
        if (
            not self.registration_command.requested_at
            <= self.registration_result.registered_at
            <= self.registration_observed_at
        ):
            raise ValueError("mixed registration observation precedes its provenance")
        validate_local_embedding_completion_metadata(
            self, "receipt_sha256", MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES
        )
        return self


def parse_local_embedding_workflow_receipt_v2(value: object) -> LocalEmbeddingWorkflowReceiptV2:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("mixed-completion", document)
        return LocalEmbeddingWorkflowReceiptV2.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_step_output_v2(value: object) -> LocalEmbeddingStepOutputV2:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("mixed-completion", document)
        return LocalEmbeddingStepOutputV2.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_workflow_receipt_v2_bytes(value: LocalEmbeddingWorkflowReceiptV2) -> bytes:
    return canonical_json_bytes(
        parse_local_embedding_workflow_receipt_v2(value).model_dump(mode="json")
    )


def local_embedding_step_output_v2_bytes(value: LocalEmbeddingStepOutputV2) -> bytes:
    return canonical_json_bytes(parse_local_embedding_step_output_v2(value).model_dump(mode="json"))


type SupportedLocalEmbeddingStepOutput = LocalEmbeddingStepOutput | LocalEmbeddingStepOutputV2
type SupportedLocalEmbeddingWorkflowReceipt = (
    LocalEmbeddingWorkflowReceipt | LocalEmbeddingWorkflowReceiptV2
)


def parse_supported_local_embedding_step_output(value: object) -> SupportedLocalEmbeddingStepOutput:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "local-embedding-step-output/2.0"
    ):
        return parse_local_embedding_step_output_v2(document)
    return parse_local_embedding_step_output(document)


def parse_supported_local_embedding_workflow_receipt(
    value: object,
) -> SupportedLocalEmbeddingWorkflowReceipt:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "local-embedding-workflow-receipt/2.0"
    ):
        return parse_local_embedding_workflow_receipt_v2(document)
    return parse_local_embedding_workflow_receipt(document)


def validate_supported_local_embedding_step_output(
    output: SupportedLocalEmbeddingStepOutput, receipt: SupportedLocalEmbeddingWorkflowReceipt
) -> SupportedLocalEmbeddingStepOutput:
    if isinstance(output, LocalEmbeddingStepOutputV2) and isinstance(
        receipt, LocalEmbeddingWorkflowReceiptV2
    ):
        return validate_local_embedding_step_output_v2(output, receipt)
    if isinstance(output, LocalEmbeddingStepOutput) and isinstance(
        receipt, LocalEmbeddingWorkflowReceipt
    ):
        return validate_local_embedding_step_output(output, receipt)
    raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")


def validate_supported_local_embedding_workflow_receipt(
    receipt: SupportedLocalEmbeddingWorkflowReceipt,
    request: SupportedLocalEmbeddingRequest,
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2,
    policy: LocalEmbeddingExecutablePolicy,
    *,
    workflow_id: str,
    step_run_id: str,
    receipt_owner_job_id: str,
    launch_association: LocalEmbeddingLaunchAssociation | LocalEmbeddingLaunchAssociationV2 | None,
    owned_input: IncrementalEmbeddingInput | None,
    index_coverage: ResolvedNativeIndexCoverage | ResolvedNativeIndexCoverageV2,
) -> SupportedLocalEmbeddingWorkflowReceipt:
    if (
        isinstance(receipt, LocalEmbeddingWorkflowReceiptV2)
        and isinstance(request, LocalEmbeddingWorkflowRequestV2)
        and isinstance(plan, LocalEmbeddingSourcePlanV2)
        and isinstance(policy, LocalEmbeddingServiceExecutionPolicy)
        and isinstance(index_coverage, ResolvedNativeIndexCoverageV2)
        and (
            launch_association is None
            or isinstance(launch_association, LocalEmbeddingLaunchAssociationV2)
        )
    ):
        return validate_local_embedding_workflow_receipt_v2(
            receipt,
            request,
            plan,
            policy,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            receipt_owner_job_id=receipt_owner_job_id,
            launch_association=launch_association,
            owned_input=owned_input,
            index_coverage=index_coverage,
        )
    if (
        isinstance(receipt, LocalEmbeddingWorkflowReceipt)
        and not isinstance(request, LocalEmbeddingWorkflowRequestV2)
        and isinstance(plan, LocalEmbeddingSourcePlan)
        and isinstance(index_coverage, ResolvedNativeIndexCoverage)
        and (
            launch_association is None
            or isinstance(launch_association, LocalEmbeddingLaunchAssociation)
        )
    ):
        return validate_local_embedding_workflow_receipt(
            receipt,
            request,
            plan,
            policy,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            receipt_owner_job_id=receipt_owner_job_id,
            launch_association=launch_association,
            owned_input=owned_input,
            index_coverage=index_coverage,
        )
    raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")


def validate_local_embedding_step_output_v2(
    output: LocalEmbeddingStepOutputV2, receipt: LocalEmbeddingWorkflowReceiptV2
) -> LocalEmbeddingStepOutputV2:
    output = parse_local_embedding_step_output_v2(output)
    receipt = parse_local_embedding_workflow_receipt_v2(receipt)
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
        raise ValueError("mixed completion carrier differs from its exact receipt")
    return output


def validate_local_embedding_workflow_receipt_v2(
    receipt: LocalEmbeddingWorkflowReceiptV2,
    request: LocalEmbeddingWorkflowRequestV2,
    plan: LocalEmbeddingSourcePlanV2,
    policy: LocalEmbeddingServiceExecutionPolicy,
    *,
    workflow_id: str,
    step_run_id: str,
    receipt_owner_job_id: str,
    launch_association: LocalEmbeddingLaunchAssociationV2 | None,
    owned_input: IncrementalEmbeddingInput | None,
    index_coverage: ResolvedNativeIndexCoverageV2,
) -> LocalEmbeddingWorkflowReceiptV2:
    """Exact historical closure; fresh IAM/physical rows/commit/lease stay with owners."""
    receipt = parse_local_embedding_workflow_receipt_v2(receipt)
    request = parse_local_embedding_workflow_request_v2(request)
    plan = parse_local_embedding_source_plan_v2(plan)
    validate_local_embedding_request_references_v2(request, plan, policy)
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
        raise ValueError("mixed receipt differs from exact resolved Workflow context")
    index = MixedEmbeddingIndexManifest.model_validate(
        raw_similarity_contract_value(index_coverage.index)
    )
    source_adapter: TypeAdapter[PopulationSource] = TypeAdapter(PopulationSource)
    if (
        type(index_coverage.eligible_sources) is not tuple
        or not 1 <= len(index_coverage.eligible_sources) <= 1024
    ):
        raise ValueError("mixed completion eligible population is invalid")
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
        raise ValueError("mixed completion full index or corpus differs")
    validate_local_embedding_selected_index_coverage_v2(plan, index)
    if launch_association is not None:
        assert owned_input is not None
        association = parse_local_embedding_launch_association_v2(launch_association)
        validate_local_embedding_launch_association_v2(
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
            raise ValueError("mixed receipt differs from original launch association")
    return receipt
