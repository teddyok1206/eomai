"""One original routed QUERY batch through existing admission, Runner and completion owners."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.similarity_context_v2 import SupportedSimilarityContextRequest
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_workflow.embedding_batch_plan_family import embedding_batch_query_key
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from sqlalchemy import select

from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_batch_driver import (
    drive_batch_reference_queries,
    start_batch_reference_queries,
)
from eom_workflow_runner.reference_query_batch_executor import CatalogBatchReferenceQueryExecutor
from eom_workflow_runner.reference_query_batch_group import CatalogReferenceQueryBatchGroup
from eom_workflow_runner.reference_query_consumer_read import (
    read_completed_reference_query_selection,
)
from eom_workflow_runner.reference_query_cpu_batch import (
    CatalogCpuReferenceQueryBatchGroup,
    RoutedCpuReferenceQueryExecution,
)
from eom_workflow_runner.reference_query_native_executor import CatalogNativeReferenceQueryExecutor
from eom_workflow_runner.reference_query_preparation import (
    prepare_and_start_reference_query_in_session,
)
from eom_workflow_runner.reference_query_routed_context import build_routed_reference_query_context
from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession
from eom_workflow_runner.reference_query_routed_selection import (
    PreparedRoutedReferenceQuerySelection,
)
from eom_workflow_runner.reference_query_runner_composition import (
    build_reference_query_workflow_runner,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_ROUTED_EXECUTION_INVALID")


@dataclass(frozen=True, slots=True)
class RoutedReferenceQueryChildObservation:
    ordinal: int
    workflow_id: str | None
    state: Literal["PENDING", "COMPLETED", "FAILED"]
    selection: CompletedSimilarityQuerySelection | None


@dataclass(frozen=True, slots=True)
class RoutedReferenceQueryObservation:
    parent_request_sha256: str
    device: Literal["CPU", "CUDA"] | None
    state: Literal["PENDING", "READY", "FAILED"]
    children: tuple[RoutedReferenceQueryChildObservation, ...]


def _composition(
    session: RoutedReferenceQuerySession, prepared: PreparedRoutedReferenceQuerySelection
) -> None:
    _require(
        type(session) is RoutedReferenceQuerySession
        and type(prepared) is PreparedRoutedReferenceQuerySelection
    )
    _require(
        session.cpu.owner is session.selection.cpu
        and session.selection.publisher is prepared.operation.publisher
        and prepared.operation.admission.catalog is session.cpu.owner.catalog
        and session.cpu.owner.identity.capture is session.selection.cuda.identity.capture
        and prepared.preparation.parent.scope.actor_id
        == session.cpu.owner.identity.capture.operator_id
    )


def _history(prepared: PreparedRoutedReferenceQuerySelection) -> EmbeddingBatchPlanHistory | None:
    with (
        prepared.operation.publisher.sessions.begin() as session,
        prepared.operation.admission.admit(session, prepared.preparation.parent) as sources,
    ):
        _require(sources.selection == prepared.selection)
        return EmbeddingBatchPlanStore(
            prepared.preparation.parent, sources.selection, sources.policy
        ).read(session)


def _contexts(
    prepared: PreparedRoutedReferenceQuerySelection, history: EmbeddingBatchPlanHistory
) -> tuple[SupportedSimilarityContextRequest, ...]:
    _require(history.route is not None)
    assert history.route is not None
    return tuple(
        build_routed_reference_query_context(
            parent=prepared.preparation.parent,
            selection=prepared.selection,
            policy=prepared.routing_policy,
            allocation=history.allocation,
            route=history.route,
            ordinal=ordinal,
        )
        for ordinal in range(len(prepared.selection.anchors))
    )


def observe_routed_reference_queries(
    session: RoutedReferenceQuerySession,
    prepared: PreparedRoutedReferenceQuerySelection,
) -> RoutedReferenceQueryObservation:
    """Reauthorize and read exact original children in indexed key order; never dispatch."""
    _composition(session, prepared)
    parent = prepared.preparation.parent
    caller = EmbeddingRegistryCaller(parent.scope.actor_id)
    with (
        prepared.operation.publisher.sessions.begin() as root,
        prepared.operation.admission.admit(root, parent) as sources,
    ):
        _require(sources.selection == prepared.selection)
        current = EmbeddingBatchPlanStore(parent, sources.selection, sources.policy).read(root)
        device = (
            None
            if current is None or current.route is None
            else current.route.decision.selected.backend.device
        )
        owner = session.cpu.owner if device == "CPU" else session.selection.cuda
        keys = tuple(
            embedding_batch_query_key(parent, ordinal)
            for ordinal in range(len(prepared.selection.anchors))
        )
        workflows = {
            row.idempotency_key: row
            for row in root.scalars(
                select(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key.in_(keys))
                .execution_options(populate_existing=True)
            )
        }
        _require(current is not None or not workflows)
        expected = () if current is None or current.route is None else _contexts(prepared, current)
        ids = tuple(row.workflow_id for row in workflows.values())
        failed_commands = (
            set(
                root.scalars(
                    select(WorkflowCommandRecord.workflow_id).where(
                        WorkflowCommandRecord.workflow_id.in_(ids),
                        WorkflowCommandRecord.state.in_(("FAILED", "CANCELLED")),
                    )
                )
            )
            if ids
            else set()
        )
        observed = []
        for ordinal, key in enumerate(keys):
            workflow = workflows.get(key)
            if workflow is None:
                observed.append(
                    RoutedReferenceQueryChildObservation(ordinal, None, "PENDING", None)
                )
                continue
            _require(device in {"CPU", "CUDA"} and len(expected) == len(keys))
            request = parse_supported_reference_query_workflow_request(workflow.initial_request)
            _require(
                workflow.created_actor_type == "human"
                and workflow.created_actor_id == caller.operator_id
                and request.context_request == expected[ordinal]
            )
            if workflow.state == "COMPLETED":
                _require(current is not None and current.bound is not None)
                selected = read_completed_reference_query_selection(
                    root, owner, caller, workflow.workflow_id
                ).selection
                observed.append(
                    RoutedReferenceQueryChildObservation(
                        ordinal, workflow.workflow_id, "COMPLETED", selected
                    )
                )
            elif (
                workflow.state in {"FAILED", "CANCELLED"} or workflow.workflow_id in failed_commands
            ):
                owner.resolve_submission(root, request)
                observed.append(
                    RoutedReferenceQueryChildObservation(
                        ordinal, workflow.workflow_id, "FAILED", None
                    )
                )
            else:
                _require(workflow.state in {"REQUESTED", "RUNNING"})
                owner.resolve_submission(root, request)
                observed.append(
                    RoutedReferenceQueryChildObservation(
                        ordinal, workflow.workflow_id, "PENDING", None
                    )
                )
        state: Literal["PENDING", "READY", "FAILED"] = "PENDING"
        if (current is not None and current.failure is not None) or any(
            child.state == "FAILED" for child in observed
        ):
            state = "FAILED"
        elif all(child.state == "COMPLETED" for child in observed):
            state = "READY"
        return RoutedReferenceQueryObservation(
            parent.request_sha256, device, state, tuple(observed)
        )


def _drive_cpu(
    session: RoutedReferenceQuerySession,
    prepared: PreparedRoutedReferenceQuerySelection,
    lane: ExistingEmbeddingBatchExecution | UnavailableEmbeddingBatchExecution,
) -> None:
    _require(type(session.cpu.executor) is CatalogNativeReferenceQueryExecutor)
    assert isinstance(session.cpu.executor, CatalogNativeReferenceQueryExecutor)
    owner, publisher = session.cpu.owner, prepared.operation.publisher
    group = CatalogCpuReferenceQueryBatchGroup(
        prepared.operation, prepared.preparation.parent, lane, owner
    )
    executor = CatalogNativeReferenceQueryExecutor(
        owner=owner,
        publisher=publisher,
        launcher=session.cpu.executor.launcher,
        source_commit=prepared.operation.source_commit,
        execution_backend=RoutedCpuReferenceQueryExecution(group, session.cpu.executor.launcher),
    )
    caller = EmbeddingRegistryCaller(prepared.preparation.parent.scope.actor_id)
    pending = []
    with publisher.sessions.begin() as root:
        for ordinal, context in enumerate(_contexts(prepared, lane.history)):
            submitted = prepare_and_start_reference_query_in_session(
                root,
                caller=caller,
                context=context,
                idempotency_key=embedding_batch_query_key(prepared.preparation.parent, ordinal),
                owner=owner,
                executor=executor,
            )
            if submitted.workflow.state in {"REQUESTED", "RUNNING"}:
                pending.append(submitted.workflow.workflow_id)
    if not pending:
        return
    try:
        with ThreadPoolExecutor(
            max_workers=len(pending), thread_name_prefix="eom-routed-cpu-query"
        ) as pool:
            futures = [
                pool.submit(
                    build_reference_query_workflow_runner(
                        publisher, owner, executor, operator_id=caller.operator_id
                    ).run_once,
                    workflow_id,
                )
                for workflow_id in pending
            ]
            try:
                for future in as_completed(futures):
                    command = future.result()
                    if command is None or command.state != "SUCCEEDED":
                        group.abort()
            except BaseException:
                group.abort()
                for future in futures:
                    future.cancel()
                raise
    finally:
        group.abort()


def drive_routed_reference_queries_once(
    session: RoutedReferenceQuerySession,
    prepared: PreparedRoutedReferenceQuerySelection,
) -> RoutedReferenceQueryObservation:
    """One original drive offer. Physical unknowns are not new roots or CPU permission."""
    _composition(session, prepared)
    snapshot = observe_routed_reference_queries(session, prepared)
    if snapshot.state != "PENDING":
        return snapshot
    original = _history(prepared)
    allocation = original.allocation if original is not None else prepared.allocation_candidate()
    with prepared.operation.open(prepared.preparation.parent, allocation) as lane:
        if isinstance(lane, ActiveEmbeddingBatchExecution):
            group = CatalogReferenceQueryBatchGroup(lane, session.selection.cuda)
            executor = CatalogBatchReferenceQueryExecutor(group)
            try:
                workflow_ids = start_batch_reference_queries(
                    executor, _contexts(prepared, lane.history)
                )
                drive_batch_reference_queries(executor, workflow_ids)
            finally:
                group.abort()
        elif (
            lane.history.route is not None
            and lane.history.route.decision.selected.backend.device == "CPU"
            and lane.history.failure is None
        ):
            _drive_cpu(session, prepared, lane)
        else:
            # Existing CUDA metadata is never an active physical channel. A
            # completed original is readable below; uncertain/unpublished work
            # remains pending for supported reconciliation, not re-encoding.
            _require(isinstance(lane, ExistingEmbeddingBatchExecution))
    return observe_routed_reference_queries(session, prepared)
