"""Shared read-only QUERY checkpoint/receipt/member closure; never execution authority."""

from __future__ import annotations

from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_reference_query_completion,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.reference_query_artifact_read import (
    CatalogReferenceQueryArtifacts,
    ResolvedReferenceQueryArtifacts,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    NativeReferenceQueryHistory,
    read_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryBatchExecuted,
    NativeQueryCompleted,
    NativeQueryExecuted,
    NativeQueryExecutedV11,
    NativeQueryPublished,
    reference_query_checkpoint_receipt,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    parse_reference_query_step_output,
    validate_reference_query_launch_association,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_batch_execution_read import (
    resolve_reference_query_batch_execution,
    validate_reference_query_batch_child_result,
)
from eom_workflow_runner.reference_query_source_read import (
    ResolvedReferenceQuerySources,
    build_reference_query_native_input,
)


def resolve_reference_query_publication(
    settings: CatalogSettings,
    *,
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    sources: ResolvedReferenceQuerySources,
    output: ReferenceQueryStepOutput,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> tuple[ResolvedReferenceQueryArtifacts, NativeReferenceQueryHistory]:
    """Shared canonical closure; caller retains actual current owner root and late fence.

    This alone is not the consumer read capability. Before publication the
    history may legitimately have only three checkpoints; a completed reader
    additionally requires the exact successful terminal Workflow and fourth
    checkpoint under freshly resolved read authority.
    """
    reader = (
        PinnedArtifactReadContext(session, settings) if artifact_reader is None else artifact_reader
    )
    reader.require_session(session)
    if reader.settings != settings:
        raise ValueError("REFERENCE_QUERY_READ_SETTINGS_MISMATCH")
    output = parse_reference_query_step_output(output)
    request = sources.request
    launch = read_native_reference_query_launch(
        session,
        request=request,
        workflow_id=workflow.workflow_id,
        step_run_id=step.step_run_id,
    )
    if launch is None:
        raise ValueError("REFERENCE_QUERY_COMPLETION_COORDINATOR_MISSING")
    history = NativeReferenceQueryCoordinator(request, launch).read(session)
    if len(history.records) < 3 or history.state in {"FAILED", "CANCELLED"}:
        raise ValueError("REFERENCE_QUERY_COMPLETION_NOT_PUBLISHED")
    allocation, executed, published = (r.payload for r in history.records[:3])
    assert isinstance(allocation, NativeQueryAllocation)
    assert isinstance(
        executed, (NativeQueryExecuted, NativeQueryExecutedV11, NativeQueryBatchExecuted)
    )
    assert isinstance(published, NativeQueryPublished)
    # Read the current step row, never trust a detached caller's producer field.
    current_step = session.get(WorkflowStepRunRecord, step.step_run_id, populate_existing=True)
    if (
        current_step is None
        or output.receipt.artifact_id != allocation.receipt_producer.artifact_id
        or output.receipt.artifact_revision_id != allocation.receipt_producer.artifact_revision_id
        or (
            current_step.platform_job_id is not None
            and current_step.platform_job_id != allocation.receipt_producer.job_id
        )
        or (
            len(history.records) == 4
            and history.records[3].payload != NativeQueryCompleted(output=output)
        )
    ):
        raise ValueError("REFERENCE_QUERY_COMPLETION_PRODUCER_MISMATCH")
    receipt = resolve_native_reference_query_completion(
        session, settings, output, artifact_reader=reader
    )
    expected = reference_query_checkpoint_receipt(request, launch, allocation, executed, published)
    if receipt != expected:
        raise ValueError("REFERENCE_QUERY_COMPLETION_HISTORY_MISMATCH")
    resolved = CatalogReferenceQueryArtifacts(
        session, settings, artifact_reader=reader
    ).resolve_publication(
        workflow_request=request,
        policy=sources.policy,
        bundle=sources.bundle,
        launch=launch,
        receipt=receipt,
        workflow_id=workflow.workflow_id,
        step_run_id=step.step_run_id,
        receipt_owner_job_id=allocation.receipt_producer.job_id,
        manifest_sha256=published.manifest_sha256,
    )
    native_input = build_reference_query_native_input(
        sources, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
    )
    validate_reference_query_launch_association(
        launch, request, sources.policy, sources.bundle, native_input
    )
    if native_input != resolved.request or executed.result_sha256 != resolved.result.result_sha256:
        raise ValueError("REFERENCE_QUERY_COMPLETION_CURRENT_INPUT_MISMATCH")
    if isinstance(executed, NativeQueryBatchExecuted):
        child = resolve_reference_query_batch_execution(
            session,
            reader=reader,
            sources=sources,
            launch=launch,
            native_input=native_input,
            executed=executed,
        )
        validate_reference_query_batch_child_result(child, resolved.result)
    reader.revalidate_provenance()
    return resolved, history
