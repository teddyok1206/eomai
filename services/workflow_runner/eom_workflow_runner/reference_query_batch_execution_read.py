"""Canonical finite CUDA batch proof for one original QUERY; no source grant or execution."""

from __future__ import annotations

import json

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE
from eom_orchestrator.models import JobRecord
from eom_workflow.embedding_batch_execution_receipt import (
    MAX_BATCH_EXECUTION_RECEIPT_BYTES,
    EmbeddingBatchExecutedChild,
    EmbeddingBatchExecutionReceipt,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchPlanRequest
from eom_workflow.native_reference_query_coordinator import NativeQueryBatchExecuted
from eom_workflow.reference_query_execution import ReferenceQueryLaunchAssociation
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_plan_admission import resolve_embedding_batch_plan_controls
from eom_workflow_runner.reference_query_source_read import (
    ResolvedReferenceQuerySources,
    validate_current_reference_query_input,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_EXECUTION_INVALID")


def resolve_reference_query_batch_execution(
    session: Session,
    *,
    reader: PinnedArtifactReadContext,
    sources: ResolvedReferenceQuerySources,
    launch: ReferenceQueryLaunchAssociation,
    native_input: EmbeddingReferenceQueryInputV11,
    executed: NativeQueryBatchExecuted,
) -> EmbeddingBatchExecutedChild:
    """Caller already holds real current child source/command or completed-read authority.

    Resolve the original parent and immutable receipt, never current/latest route
    or a historical systemd unit. Returning metadata is not a source capability.
    The caller revalidates current authority around publication/read as usual.
    """
    reader.require_session(session)
    executed = NativeQueryBatchExecuted.model_validate(executed)
    validate_current_reference_query_input(sources, launch, native_input)
    pointer = executed.batch_receipt
    reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    reader.require_file_set(
        pointer.artifact_id,
        pointer.artifact_revision_id,
        ("receipt.json",),
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
    )
    raw = reader.read_pinned(
        **pointer.model_dump(mode="python"),
        expected_artifact_types=(BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,),
        expected_primary_file="receipt.json",
        max_bytes=MAX_BATCH_EXECUTION_RECEIPT_BYTES,
    ).payload
    receipt = EmbeddingBatchExecutionReceipt.model_validate(json.loads(raw))
    request, context = sources.request, sources.request.context_request
    ordinal = executed.child_ordinal
    _require(
        canonical_json_bytes(receipt.model_dump(mode="json")) == raw
        and receipt.receipt_sha256 == executed.batch_receipt_sha256
        and receipt.purpose == "REFERENCE_QUERY"
        and request.resource_profile.device == "CUDA"
        and receipt.scope.actor_kind == "OPERATOR"
        and receipt.scope.actor_id == request.operator_audit.operator_id
        and receipt.scope.access_policy_sha256 == context.policy_sha256
        and all(
            row.encoding.storage_partition == receipt.scope.storage_partition
            for row in native_input.rows
        )
        and receipt.bound.binding.resource_profile_sha256
        == request.resource_profile.resource_profile_sha256
        and executed.completed_observed_at == receipt.completed.retired_at
        and ordinal < len(receipt.children)
    )
    parent_job = session.get(JobRecord, receipt.parent_plan_job_id, populate_existing=True)
    _require(parent_job is not None)
    assert parent_job is not None
    parent = EmbeddingBatchPlanRequest.model_validate(parent_job.request)
    selection, policy = resolve_embedding_batch_plan_controls(reader, parent)
    history = EmbeddingBatchPlanStore(parent, selection, policy).read(session)
    _require(
        history is not None
        and history.job_id == receipt.parent_plan_job_id
        and history.state == "SUCCEEDED"
        and history.failure is None
        and history.route is not None
        and history.bound == receipt.bound.binding
        and history.allocation.control_request == receipt.allocation
        and parent.scope == receipt.scope
        and selection.purpose == "REFERENCE_QUERY"
        and selection.graph_snapshot == context.graph_snapshot
        and selection.access_policy_revision_id == context.policy_revision_id
        and selection.recipe == native_input.recipe
        and tuple(view.view for view in context.views) == selection.views
        and ordinal < len(selection.anchors)
        and selection.anchors[ordinal] == context.anchor
        and selection.query is not None
        and selection.query.model_dump(mode="json")
        == {
            "consumer_purpose": context.consumer_purpose,
            "topics": list(context.topics),
            "unit_ids": list(context.unit_ids),
            "maximum_sources": context.maximum_sources,
            "top_k": context.top_k,
        }
        and policy.cuda.profile.space == native_input.spaces.document
        and policy.cuda.profile.resource_profile == request.resource_profile
        and policy.cuda.profile.runtime_bundle == request.runtime_bundle
    )
    assert history is not None and history.route is not None
    _require(
        history.route.decision.selected == policy.cuda
        and receipt.completed.grant.routing_decision_sha256
        == history.route.decision.decision_sha256
    )
    bound, child = receipt.bound.binding.children[ordinal], receipt.children[ordinal]
    _require(
        bound.workflow_id == launch.workflow_id
        and bound.step_run_id == launch.step_run_id
        and bound.native_job_id == launch.native_launch_job_id == native_input.job_id
        and bound.workflow_request_sha256 == request.request_sha256
        and bound.launch_association_sha256 == launch.association_sha256
        and bound.native_input_sha256 == native_input.request_sha256
        and bound.selection_sha256 == parent.child_selection_sha256s[ordinal]
        and child.result_sha256 == executed.result_sha256
        and child.row_count == len(native_input.rows)
        and child.dimension == native_input.spaces.query.model_spec.dimension
    )
    reader.revalidate_provenance()
    return child


def validate_reference_query_batch_child_result(
    child: EmbeddingBatchExecutedChild, result: EmbeddingReferenceQueryResult
) -> None:
    """Compare already verified canonical child metadata; do not duplicate vector reads/hashes."""
    shard = result.shard
    _require(
        child.native_job_id == result.job_id
        and child.input_sha256 == result.request_sha256
        and child.result_sha256 == result.result_sha256
        and child.shard_sha256 == shard.shard_sha256
        and child.binary_sha256 == shard.binary.sha256
        and child.vector_byte_count == shard.binary.byte_count
        and child.row_count == shard.row_count
        and child.dimension == shard.dimension
    )
