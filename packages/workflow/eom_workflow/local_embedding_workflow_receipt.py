"""Native completion provenance, not a worker result, current head or recovery grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
    validate_embedding_registration_result,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    IncrementalEmbeddingInput,
    parse_embedding_index,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.local_embedding_encoding_job import (
    LocalEmbeddingLaunchAssociation,
    validate_local_embedding_launch_association,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
from eom_workflow.local_embedding_request import (
    LocalEmbeddingWorkflowRequestV11,
    validate_local_embedding_request_references,
)
from eom_workflow.local_embedding_source_plan import (
    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
    LocalEmbeddingSourcePlan,
)
from eom_workflow.models import JobId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    LocalEmbeddingReceiptSchemaName,
    NativeEmbeddingContract,
    _native_contract_values,
    validate_local_embedding_receipt_message,
)

LOCAL_EMBEDDING_STEP_OUTPUT_SCHEMA_REF = "eom://schemas/workflow/local-embedding-step-output/1.0"
LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-workflow-receipt/1.0"
)
MAX_LOCAL_EMBEDDING_STEP_OUTPUT_BYTES = 8 * 1024
MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ResolvedNativeIndexCoverage:
    """Owner-resolved index/population values; not source or registration authority."""

    index: EmbeddingIndexManifest
    eligible_sources: tuple[PopulationSource, ...]


def _hash(value: NativeEmbeddingContract, field: str, maximum: int) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > maximum:
        raise ValueError("native completion metadata exceeds its byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("native completion metadata canonical hash differs")


class LocalEmbeddingStepOutput(NativeEmbeddingContract):
    """Pointer carrier; result-schema semantics never identify its receipt bytes."""

    schema_version: Literal["local-embedding-step-output/1.0"] = "local-embedding-step-output/1.0"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    receipt_owner_job_id: JobId
    execution_result_schema: Literal["incremental-embedding-result@1.0"] = (
        "incremental-embedding-result@1.0"
    )
    receipt_schema: Literal["eom://schemas/workflow/local-embedding-workflow-receipt/1.0"] = (
        "eom://schemas/workflow/local-embedding-workflow-receipt/1.0"
    )
    receipt: ArtifactMemberPointer
    receipt_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="after")
    def exact_carrier(self) -> LocalEmbeddingStepOutput:
        if (
            self.receipt.member_path != "receipt.json"
            or self.receipt.schema_ref != self.receipt_schema
            or self.receipt.media_type != "application/json"
        ):
            raise ValueError("native completion receipt member differs")
        _hash(self, "output_sha256", MAX_LOCAL_EMBEDDING_STEP_OUTPUT_BYTES)
        return self


class LocalEmbeddingWorkflowReceipt(NativeEmbeddingContract):
    """One immutable registration observation; fresh current authority is never stored."""

    schema_version: Literal["local-embedding-workflow-receipt/1.0"] = (
        "local-embedding-workflow-receipt/1.0"
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
    registration_command: RegisterEmbeddingIndexCommand
    registration_result: EmbeddingIndexRegistrationResult
    registration_observed_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_historical_observation(self) -> LocalEmbeddingWorkflowReceipt:
        if (
            self.source_plan.member_path != "source-plan.json"
            or self.source_plan.schema_ref != LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF
            or self.source_plan.media_type != "application/json"
            or (self.native_launch_job_id is None) != (self.launch_association_sha256 is None)
        ):
            raise ValueError("native completion plan or launch pair differs")
        validate_embedding_registration_result(self.registration_command, self.registration_result)
        if not (
            self.registration_command.requested_at
            <= self.registration_result.registered_at
            <= self.registration_observed_at
        ):
            raise ValueError("native registration observation time precedes its provenance")
        _hash(self, "receipt_sha256", MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES)
        return self


def _parse[ReceiptValue: NativeEmbeddingContract](
    value: object, name: LocalEmbeddingReceiptSchemaName, model: type[ReceiptValue]
) -> ReceiptValue:
    try:
        document = _native_contract_values(value)
        validate_local_embedding_receipt_message(name, document)
        return model.model_validate(document)
    except LocalEmbeddingAdmissionContractError:
        raise
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_step_output(value: object) -> LocalEmbeddingStepOutput:
    return _parse(value, "step-output", LocalEmbeddingStepOutput)


def parse_local_embedding_workflow_receipt(value: object) -> LocalEmbeddingWorkflowReceipt:
    return _parse(value, "workflow-receipt", LocalEmbeddingWorkflowReceipt)


def local_embedding_step_output_bytes(value: LocalEmbeddingStepOutput) -> bytes:
    return canonical_json_bytes(parse_local_embedding_step_output(value).model_dump(mode="json"))


def local_embedding_workflow_receipt_bytes(value: LocalEmbeddingWorkflowReceipt) -> bytes:
    return canonical_json_bytes(
        parse_local_embedding_workflow_receipt(value).model_dump(mode="json")
    )


def validate_local_embedding_step_output(
    output: LocalEmbeddingStepOutput, receipt: LocalEmbeddingWorkflowReceipt
) -> LocalEmbeddingStepOutput:
    """Pure carrier/raw-member closure; actual producer/commit/current access are owner checks."""
    output = parse_local_embedding_step_output(output)
    receipt = parse_local_embedding_workflow_receipt(receipt)
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
        raise ValueError("native completion carrier differs from its exact receipt")
    return output


def validate_local_embedding_workflow_receipt(
    receipt: LocalEmbeddingWorkflowReceipt,
    request: LocalEmbeddingWorkflowRequestV11,
    plan: LocalEmbeddingSourcePlan,
    policy: LocalEmbeddingExecutionPolicy,
    *,
    workflow_id: str,
    step_run_id: str,
    receipt_owner_job_id: str,
    launch_association: LocalEmbeddingLaunchAssociation | None,
    owned_input: IncrementalEmbeddingInput | None,
    index_coverage: ResolvedNativeIndexCoverage | None = None,
) -> LocalEmbeddingWorkflowReceipt:
    """Exact immutable resolved context, not current caller or linked recovery authority.

    An original association may retain a different command generation after reclaim.
    This function pins it as provenance only: current recovery command, token, session,
    source, finite binary and canonical committed Artifact checks belong to actual owners.
    """
    receipt = parse_local_embedding_workflow_receipt(receipt)
    request = LocalEmbeddingWorkflowRequestV11.model_validate(request)
    plan = LocalEmbeddingSourcePlan.model_validate(plan)
    policy = LocalEmbeddingExecutionPolicy.model_validate(policy)
    validate_local_embedding_request_references(request, plan, policy)
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
        raise ValueError("native completion receipt differs from exact resolved Workflow context")
    if index_coverage is None:
        if (
            command.source_set_sha256 != plan.source_set_sha256
            or command.eligible_source_count != len(plan.sources)
            or command.binding_count != len(plan.demands)
        ):
            raise ValueError(
                "native completion receipt differs from exact resolved Workflow context: "
                "requires whole-plan or resolved index coverage"
            )
    else:
        index = parse_embedding_index(index_coverage.index.model_dump(mode="json"))
        source_adapter: TypeAdapter[PopulationSource] = TypeAdapter(PopulationSource)
        sources = {
            s.item_revision_id: source_adapter.validate_python(s.model_dump(mode="json"))
            for s in index_coverage.eligible_sources
        }
        bindings = {b.source.item_revision_id: b for b in index.bindings}
        if (
            len(sources) != len(index_coverage.eligible_sources)
            or command.source_set_sha256 != population_sha256(index_coverage.eligible_sources)
            or command.eligible_source_count != len(sources)
            or command.binding_count != len(bindings)
            or command.binding_set_sha256
            != content_sha256([b.binding_sha256 for b in index.bindings])
            or command.index_id != index.index_id
            or command.index_revision_id != index.index_revision_id
            or command.index_sha256 != index.index_sha256
            or command.index_manifest.sha256
            != sha256_bytes(canonical_json_bytes(index.model_dump(mode="json")))
            or index.space != plan.space
            or index.storage_partition != plan.namespace.storage_partition
            or index.recipe != plan.recipe
            or index.view != plan.namespace.view
            or any(sources.get(s.item_revision_id) != s for s in plan.sources)
            or any(
                sources.get(b.source.item_revision_id) != b.source
                or b.graph_snapshot != plan.graph_snapshot
                or b.policy_revision_id != plan.access_policy_revision_id
                or b.policy_sha256 != plan.access_policy_sha256
                for b in index.bindings
            )
        ):
            raise ValueError("native completion full index or corpus differs")
        for demand in plan.demands:
            binding = bindings.get(demand.source_revision_id)
            if (
                binding is None
                or binding.source != sources[demand.source_revision_id]
                or binding.encoding != demand.encoding
                or binding.profile != demand.profile
                or binding.solution_evidence != demand.solution_evidence
                or binding.graph_snapshot != plan.graph_snapshot
                or binding.policy_revision_id != plan.access_policy_revision_id
                or binding.policy_sha256 != plan.access_policy_sha256
            ):
                raise ValueError("native completion index does not cover an exact selected demand")
    if launch_association is not None:
        assert owned_input is not None
        association = LocalEmbeddingLaunchAssociation.model_validate(launch_association)
        validate_local_embedding_launch_association(
            association, plan, owned_input, request.resource_profile, request.request_sha256
        )
        intent = association.intent
        if (
            receipt.native_launch_job_id != intent.native_launch_job_id
            or receipt.launch_association_sha256 != association.association_sha256
            or receipt.workflow_id != intent.workflow_id
            or receipt.step_run_id != intent.step_run_id
            or receipt.step_key != intent.step_key
            or receipt.attempt != intent.attempt
            or receipt.source_plan != intent.source_plan
        ):
            raise ValueError("native completion receipt differs from original launch association")
    return receipt
