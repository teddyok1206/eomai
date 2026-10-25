"""Existing atomic QUERY/START and Runner claims for one finite same-operator batch."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from eom_catalog_contracts.similarity_context_v2 import (
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context_request,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    embedding_batch_query_key,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    parse_supported_reference_query_workflow_request,
)

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.reference_query_batch_executor import CatalogBatchReferenceQueryExecutor
from eom_workflow_runner.reference_query_consumer_read import (
    read_completed_reference_query_selection,
)
from eom_workflow_runner.reference_query_preparation import (
    prepare_and_start_reference_query_in_session,
)
from eom_workflow_runner.reference_query_prepare_application import reference_query_prepare_identity
from eom_workflow_runner.reference_query_runner_composition import (
    build_reference_query_workflow_runner,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_DRIVE_INVALID")


def prepare_batch_reference_query_context(
    parent: SupportedEmbeddingBatchRequest,
    ordinal: int,
    context: SupportedSimilarityContextRequest,
) -> SupportedSimilarityContextRequest:
    """New logical child intent, with every supplied immutable source/index pin unchanged.

    Reuse the existing QUERY logical-ID derivation. Otherwise generic Workflow
    equivalence could correctly return another parent's identical old QUERY.
    This does not edit that history or provide current source authority.
    """
    context = parse_supported_similarity_context_request(context)
    _key, logical_id = reference_query_prepare_identity(
        parent.scope.actor_id, embedding_batch_query_key(parent, ordinal)
    )
    body = context.model_dump(mode="json", exclude={"request_sha256"}) | {"request_id": logical_id}
    return parse_supported_similarity_context_request(
        body | {"request_sha256": content_sha256(body)}
    )


def start_batch_reference_queries(
    executor: CatalogBatchReferenceQueryExecutor,
    contexts: tuple[SupportedSimilarityContextRequest, ...],
) -> tuple[str, ...]:
    """Pinned sources become child intents through the original current-owner atomic START.

    Supplied contexts/actor IDs are not authority: that use case resolves actual
    current Identity and canonical sources before creating any Workflow. One bad
    member rolls back this whole submission root; no model or unit starts here.
    """
    _require(type(executor) is CatalogBatchReferenceQueryExecutor and type(contexts) is tuple)
    group = executor.group
    _require(len(contexts) == len(group.selection.anchors))
    caller = EmbeddingRegistryCaller(group.selection.scope.actor_id)
    workflows = []
    with group.publisher.sessions.begin() as session:
        for ordinal, value in enumerate(contexts):
            context = prepare_batch_reference_query_context(group.active.request, ordinal, value)
            submitted = prepare_and_start_reference_query_in_session(
                session,
                caller=caller,
                context=context,
                idempotency_key=embedding_batch_query_key(group.active.request, ordinal),
                owner=executor.owner,
                executor=executor,
            )
            request = parse_supported_reference_query_workflow_request(
                submitted.workflow.initial_request
            )
            _require(group.ordinal(request) == ordinal)
            workflows.append(submitted.workflow.workflow_id)
    return tuple(workflows)


def _runner(executor: CatalogBatchReferenceQueryExecutor) -> WorkflowRunner:
    group = executor.group
    return build_reference_query_workflow_runner(
        group.publisher, executor.owner, executor, operator_id=group.selection.scope.actor_id
    )


def _completed(
    executor: CatalogBatchReferenceQueryExecutor, workflow_id: str
) -> ReferenceQueryStepOutput:
    owner, group = executor.owner, executor.group
    caller = EmbeddingRegistryCaller(group.selection.scope.actor_id)
    with group.publisher.sessions.begin() as session:
        return read_completed_reference_query_selection(session, owner, caller, workflow_id).output


def drive_batch_reference_queries(
    executor: CatalogBatchReferenceQueryExecutor, workflow_ids: tuple[str, ...]
) -> tuple[ReferenceQueryStepOutput, ...]:
    """Each child keeps normal claim/heartbeat/completion; only numerical work is grouped.

    No SQL root crosses the bounded thread pool. Existing completed children are
    read/re-authorized, never re-claimed. A failed/missing claim aborts gathering;
    it is not an instruction to retry a worker or choose CPU.
    """
    _require(type(executor) is CatalogBatchReferenceQueryExecutor and type(workflow_ids) is tuple)
    group = executor.group
    _require(
        len(workflow_ids) == len(group.selection.anchors)
        and len(set(workflow_ids)) == len(workflow_ids)
    )
    pending = []
    with group.publisher.sessions.begin() as session:
        for ordinal, workflow_id in enumerate(workflow_ids):
            workflow = session.get(WorkflowInstanceRecord, workflow_id, populate_existing=True)
            _require(workflow is not None)
            assert workflow is not None
            request = parse_supported_reference_query_workflow_request(workflow.initial_request)
            _require(
                group.ordinal(request) == ordinal
                and workflow.idempotency_key
                == embedding_batch_query_key(group.active.request, ordinal)
                and workflow.state in {"REQUESTED", "RUNNING", "COMPLETED"}
            )
            executor.owner.resolve_submission(session, request)
            if workflow.state != "COMPLETED":
                pending.append(workflow_id)
    if pending:
        try:
            with ThreadPoolExecutor(
                max_workers=len(pending), thread_name_prefix="eom-query-batch"
            ) as pool:
                futures = []
                try:
                    for workflow_id in pending:
                        futures.append(pool.submit(_runner(executor).run_once, workflow_id))
                    for future in as_completed(futures):
                        command = future.result()
                        _require(command is not None and command.state == "SUCCEEDED")
                except BaseException:
                    group.abort()
                    for future in futures:
                        future.cancel()
                    raise
        except BaseException:
            group.abort()
            raise
    return tuple(_completed(executor, workflow_id) for workflow_id in workflow_ids)
