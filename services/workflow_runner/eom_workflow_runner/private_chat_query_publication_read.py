"""Original private history/receipt/bytes closure; never current source authority."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_supported_native_private_chat_query_completion,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_query_artifact_read import (
    CatalogPrivateChatQueryArtifacts,
    ResolvedPrivateChatPublicQueryArtifacts,
    ResolvedPrivateChatQueryArtifacts,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCoordinator,
    NativePrivateChatQueryHistory,
)
from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryCompleted,
    NativePrivateQueryCompletedV2,
    NativePrivateQueryExecuted,
    NativePrivateQueryPublished,
    NativePrivateQueryPublishedV2,
    supported_private_chat_query_checkpoint_receipt,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import (
    parse_private_chat_query_submission_context,
    validate_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    SupportedPrivateChatQueryStepOutput,
    parse_supported_private_chat_query_step_output,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_owner_admission import (
    validate_private_chat_query_execution_step,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatPublicQuerySources,
    ResolvedPrivateChatQuerySources,
    build_supported_private_chat_query_native_input,
    require_private_chat_query_source_root,
)


def resolve_private_chat_query_publication(
    settings: CatalogSettings,
    *,
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    sources: ResolvedPrivateChatQuerySources,
    output: PrivateChatQueryStepOutput,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> tuple[ResolvedPrivateChatQueryArtifacts, NativePrivateChatQueryHistory]:
    """Legacy numerical1 publication API remains closed to common QUERY2."""
    try:
        if type(sources) is not ResolvedPrivateChatQuerySources:
            raise ValueError()
        output = PrivateChatQueryStepOutput.model_validate(raw_similarity_contract_value(output))
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_PUBLICATION_INVALID") from None
    resolved, history = resolve_supported_private_chat_query_publication(
        settings,
        session=session,
        workflow=workflow,
        step=step,
        sources=sources,
        output=output,
        artifact_reader=artifact_reader,
    )
    if not isinstance(resolved, ResolvedPrivateChatQueryArtifacts):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_PUBLICATION_INVALID")
    return resolved, history


def resolve_supported_private_chat_query_publication(
    settings: CatalogSettings,
    *,
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    sources: ResolvedPrivateChatQuerySources | ResolvedPrivateChatPublicQuerySources,
    output: SupportedPrivateChatQueryStepOutput,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> tuple[
    ResolvedPrivateChatQueryArtifacts | ResolvedPrivateChatPublicQueryArtifacts,
    NativePrivateChatQueryHistory,
]:
    """Caller holds actual current ownership/lease; no physical unit survival is required."""
    root = require_private_chat_query_source_root(session)
    try:
        output = parse_supported_private_chat_query_step_output(
            raw_similarity_contract_value(output)
        )
        if isinstance(sources, ResolvedPrivateChatPublicQuerySources) != isinstance(
            output, PrivateChatQueryStepOutputV2
        ):
            raise ValueError()
        sources.__post_init__()
        reader = (
            PinnedArtifactReadContext(session, settings)
            if artifact_reader is None
            else artifact_reader
        )
        reader.require_session(session)
        if reader.settings != settings:
            raise ValueError()
        current_workflow = session.get(
            WorkflowInstanceRecord, workflow.workflow_id, populate_existing=True
        )
        current_step = session.get(WorkflowStepRunRecord, step.step_run_id, populate_existing=True)
        if current_workflow is None or current_step is None:
            raise ValueError()
        validate_private_chat_query_execution_step(current_step, current_workflow, sources.request)
        context = validate_private_chat_query_submission_context(
            sources.request,
            parse_private_chat_query_submission_context(current_workflow.runtime_context),
        )
        if context.origin != sources.projection.origin:
            raise ValueError()
        launch = read_native_query_launch(
            session,
            request=sources.request,
            workflow_id=current_workflow.workflow_id,
            step_run_id=current_step.step_run_id,
        )
        if not isinstance(launch, PrivateChatQueryLaunchAssociation):
            raise ValueError()
        history = NativePrivateChatQueryCoordinator(sources.request, launch).read(session)
        if len(history.records) < 3 or history.state in {"FAILED", "CANCELLED"}:
            raise ValueError()
        allocation, executed, published = (r.payload for r in history.records[:3])
        if (
            not isinstance(allocation, NativePrivateQueryAllocation)
            or not isinstance(executed, NativePrivateQueryExecuted)
            or not isinstance(
                published, (NativePrivateQueryPublished, NativePrivateQueryPublishedV2)
            )
        ):
            raise ValueError()
        producer = allocation.allocation.receipt_producer
        completed = history.records[3].payload if len(history.records) == 4 else None
        if (
            allocation.origin != context.origin
            or output.receipt.artifact_id != producer.artifact_id
            or output.receipt.artifact_revision_id != producer.artifact_revision_id
            or (
                current_step.platform_job_id is not None
                and current_step.platform_job_id != producer.job_id
            )
            or (
                completed is not None
                and (
                    not isinstance(
                        completed, (NativePrivateQueryCompleted, NativePrivateQueryCompletedV2)
                    )
                    or completed.output != output
                )
            )
        ):
            raise ValueError()
        receipt = resolve_supported_native_private_chat_query_completion(
            session, settings, output, artifact_reader=reader
        )
        expected = supported_private_chat_query_checkpoint_receipt(
            sources.request, launch, allocation, executed, published
        )
        if receipt != expected:
            raise ValueError()
        native = build_supported_private_chat_query_native_input(
            sources, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
        )
        resolved = CatalogPrivateChatQueryArtifacts(
            session, settings, artifact_reader=reader
        ).resolve_supported_publication(
            workflow_request=sources.request,
            policy=sources.policy,
            bundle=sources.bundle,
            launch=launch,
            native_input=native,
            receipt=receipt,
            origin=context.origin,
            workflow_id=current_workflow.workflow_id,
            step_run_id=current_step.step_run_id,
            receipt_owner_job_id=producer.job_id,
            manifest_sha256=published.manifest_sha256,
        )
        if resolved.result.result_sha256 != executed.result_sha256:
            raise ValueError()
        reader.revalidate_provenance()
        if require_private_chat_query_source_root(session) is not root:
            raise ValueError()
        return resolved, history
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_PUBLICATION_INVALID") from None
