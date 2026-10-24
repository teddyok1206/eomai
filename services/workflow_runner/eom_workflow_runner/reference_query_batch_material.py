"""Protected child publication materialization, never a CPU handoff or numerical launch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_reference_query import (
    EmbeddingReferenceQueryResult,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    write_protected_cpu_owner_member,
)
from eom_orchestrator.native_embedding_query_handoff import OWNER_ROOT
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
)

QUERY_PUBLICATION_ROOT = OWNER_ROOT
_MEMBERS = frozenset({"input.json", "result.json", "vectors.f32", "shard.json"})


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID")


def require_batch_query_publication_layout() -> None:
    owner = fixed_owner_identity()
    _require(os.getresuid() == (owner.owner_uid,) * 3 and os.getresgid() == (owner.owner_gid,) * 3)
    try:
        with protected_cpu_handoff_directory(
            QUERY_PUBLICATION_ROOT,
            owner=owner,
            uid=owner.owner_uid,
            gid=owner.owner_gid,
            mode=0o700,
        ):
            pass
    except CpuHandoffError:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID") from None


@dataclass(frozen=True, slots=True)
class PreparedBatchReferenceQuery:
    """Exact original values for the existing publisher; not a compute capability.

    Reuse the existing protected query publication root, not PreparedNativeQuery:
    its exact CPU guard remains unchanged and cannot launch these CUDA inputs.
    """

    workflow_request: SupportedReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    association: ReferenceQueryLaunchAssociation
    request: EmbeddingReferenceQueryInputV11

    def __post_init__(self) -> None:
        workflow = parse_supported_reference_query_workflow_request(self.workflow_request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        association = parse_reference_query_launch_association(self.association)
        request = parse_embedding_reference_query_input_v11(self.request)
        validate_reference_query_launch_association(association, workflow, policy, bundle, request)
        _require(workflow.resource_profile.device == request.spaces.query.runtime.device == "CUDA")
        for name, value in (
            ("workflow_request", workflow),
            ("policy", policy),
            ("bundle", bundle),
            ("association", association),
            ("request", request),
        ):
            object.__setattr__(self, name, value)

    @property
    def workspace(self) -> Path:
        return QUERY_PUBLICATION_ROOT / self.association.native_launch_job_id.removeprefix("job_")


def stage_batch_query_publication(
    prepared: PreparedBatchReferenceQuery,
    result: EmbeddingReferenceQueryResult,
    vectors: memoryview,
) -> None:
    """Caller retains current canonical receipt/source fences; no NAS or DB writes.

    The only binary copy is this explicit aggregate→child commit boundary. Exact
    replay never truncates an existing or partially written publication member.
    """
    _require(type(prepared) is PreparedBatchReferenceQuery)
    require_batch_query_publication_layout()
    validate_reference_query_result_v11(prepared.request, result)
    _require(
        type(vectors) is memoryview
        and vectors.readonly
        and vectors.ndim == 1
        and vectors.c_contiguous
        and vectors.format == "B"
    )
    binary = vectors.tobytes()
    read_unit_vectors(
        binary,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    owner = fixed_owner_identity()
    try:
        path = ensure_protected_cpu_owner_workspace(
            QUERY_PUBLICATION_ROOT,
            prepared.association.native_launch_job_id.removeprefix("job_"),
            owner=owner,
        )
        with protected_cpu_handoff_directory(
            path, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ) as directory:
            _require(set(os.listdir(directory)).issubset(_MEMBERS))
            for name, raw in (
                ("input.json", canonical_json_bytes(prepared.request.model_dump(mode="json"))),
                ("result.json", canonical_json_bytes(result.model_dump(mode="json"))),
                ("vectors.f32", binary),
            ):
                write_protected_cpu_owner_member(directory, name, raw, owner=owner)
    except CpuHandoffError:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID") from None
