"""Original BUSY-route QUERY binding barrier before the unchanged fixed CPU launcher."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from threading import Condition

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanStore,
)
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_orchestrator.native_embedding_query_systemd import FixedNativeQueryLauncher
from eom_workflow.embedding_batch_plan import EmbeddingBatchBound
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    validate_embedding_batch_query_context,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_cpu_route import require_original_cpu_batch_route
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    ReferenceQueryBatchSource,
)
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.reference_query_batch_binding import prepare_reference_query_batch_binding
from eom_workflow_runner.reference_query_cpu_execution import CpuReferenceQueryExecutionContext
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_CPU_BATCH_INVALID")


class _Phase(StrEnum):
    GATHERING = "GATHERING"
    BINDING = "BINDING"
    BOUND = "BOUND"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class _Child:
    prepared: PreparedNativeQuery
    source: ReferenceQueryBatchSource


class CatalogCpuReferenceQueryBatchGroup:
    """Finite operation-local barrier, not a queue, model owner or permission cache.

    Parent binding is metadata, never CPU numerical completion. Completed
    siblings do not rejoin an already-bound group on recovery. Each remaining
    child keeps its own official claim, launcher and completion checkpoints.
    """

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        parent: SupportedEmbeddingBatchRequest,
        original: ExistingEmbeddingBatchExecution | UnavailableEmbeddingBatchExecution,
        owner: CatalogReferenceQueryOwnerAdmission,
    ) -> None:
        _require(
            type(owner) is CatalogReferenceQueryOwnerAdmission
            and parent.purpose == "REFERENCE_QUERY"
        )
        _require(operation.admission.catalog is owner.catalog)
        self.operation, self.parent, self.original, self.owner = operation, parent, original, owner
        history = require_original_cpu_batch_route(operation, parent, original)
        assert history.route is not None
        _require(history.route.decision.selected.profile.resource_profile.timeout_seconds <= 180)
        with (
            operation.publisher.sessions.begin() as session,
            operation.admission.admit(session, parent) as sources,
        ):
            self.selection, self.policy = sources.selection, sources.policy
            _require(owner.configuration.registry.space == self.policy.cpu.profile.space)
        self.decision = history.route.decision
        self._ordinals = {
            anchor.source.item_revision_id: ordinal
            for ordinal, anchor in enumerate(self.selection.anchors)
        }
        _require(len(self._ordinals) == len(self.selection.anchors))
        self._condition = Condition()
        self._children: dict[int, _Child] = {}
        self._phase = _Phase.BOUND if history.bound is not None else _Phase.GATHERING
        self._deadline = time.monotonic() + min(
            self.decision.selected.profile.resource_profile.timeout_seconds, 180
        )

    def abort(self) -> None:
        with self._condition:
            if self._phase is not _Phase.BOUND:
                self._phase = _Phase.ABORTED
                self._condition.notify_all()

    def _ordinal(self, prepared: PreparedNativeQuery, source: ReferenceQueryBatchSource) -> int:
        _require(
            type(prepared) is PreparedNativeQuery and type(source) is ReferenceQueryBatchSource
        )
        _require(
            source.owner is self.owner
            and source.request == prepared.workflow_request
            and source.launch == prepared.association
        )
        ordinal = self._ordinals.get(
            prepared.workflow_request.context_request.anchor.source.item_revision_id
        )
        _require(ordinal is not None)
        assert ordinal is not None
        validate_embedding_batch_query_context(
            self.selection, self.decision, ordinal, prepared.workflow_request
        )
        config = self.owner.configuration
        _require(
            prepared.workflow_request.native_execution_policy == config.native_execution_policy
            and prepared.workflow_request.native_execution_policy_sha256
            == config.native_execution_policy_sha256
            and prepared.workflow_request.runtime_bundle == config.runtime_bundle
        )
        return ordinal

    def _validate_bound(
        self, bound: EmbeddingBatchBound, ordinal: int, prepared: PreparedNativeQuery
    ) -> None:
        _require(ordinal < len(bound.children))
        child, launch = bound.children[ordinal], prepared.association
        _require(
            bound.request_sha256 == self.parent.request_sha256
            and bound.resource_profile_sha256
            == prepared.workflow_request.resource_profile.resource_profile_sha256
            and child.selection_sha256 == self.parent.child_selection_sha256s[ordinal]
            and (
                child.workflow_id,
                child.step_run_id,
                child.native_job_id,
                child.workflow_request_sha256,
                child.launch_association_sha256,
                child.native_input_sha256,
            )
            == (
                launch.workflow_id,
                launch.step_run_id,
                launch.native_launch_job_id,
                prepared.workflow_request.request_sha256,
                launch.association_sha256,
                prepared.request.request_sha256,
            )
        )

    def _ready_child(self, ordinal: int, child: _Child) -> None:
        current = require_original_cpu_batch_route(self.operation, self.parent, self.original)
        _require(current.bound is not None)
        assert current.bound is not None
        self._validate_bound(current.bound, ordinal, child.prepared)
        child.source.authorize_current(child.prepared.request)

    def join(self, prepared: PreparedNativeQuery, source: ReferenceQueryBatchSource) -> None:
        """No SQL root is held while another Runner prepares or waits at this barrier."""
        try:
            self._join(prepared, source)
        except BaseException:
            self.abort()
            raise

    def _join(self, prepared: PreparedNativeQuery, source: ReferenceQueryBatchSource) -> None:
        ordinal = self._ordinal(prepared, source)
        source.authorize_current(prepared.request)
        current = require_original_cpu_batch_route(self.operation, self.parent, self.original)
        child = _Child(prepared, source)
        leader = False
        with self._condition:
            _require(self._phase is not _Phase.ABORTED)
            if current.bound is not None:
                self._phase = _Phase.BOUND
                self._condition.notify_all()
            elif self._phase is _Phase.GATHERING:
                _require(ordinal not in self._children)
                self._children[ordinal] = child
                if len(self._children) == len(self.selection.anchors):
                    self._phase = _Phase.BINDING
                    leader = True
            elif self._phase is _Phase.BINDING:
                raise ValueError("REFERENCE_QUERY_CPU_BATCH_DUPLICATE_CHILD")
            if not leader:
                while self._phase is not _Phase.BOUND:
                    _require(self._phase is not _Phase.ABORTED)
                    remaining = self._deadline - time.monotonic()
                    if remaining <= 0:
                        self._phase = _Phase.ABORTED
                        self._condition.notify_all()
                        raise TimeoutError("REFERENCE_QUERY_CPU_BATCH_GATHER_DEADLINE")
                    self._condition.wait(remaining)
        if leader:
            try:
                self._bind(tuple(self._children[key] for key in range(len(self.selection.anchors))))
                with self._condition:
                    _require(self._phase is _Phase.BINDING)
                    self._phase = _Phase.BOUND
                    self._condition.notify_all()
            except BaseException:
                self.abort()
                raise
        self._ready_child(ordinal, child)

    def _bind(self, children: tuple[_Child, ...]) -> None:
        current = require_original_cpu_batch_route(self.operation, self.parent, self.original)
        assert current.route is not None
        binding, batch = prepare_reference_query_batch_binding(
            self.parent, current.route, tuple(child.prepared for child in children)
        )
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, tuple(child.source for child in children)
        )
        with (
            self.operation.publisher.sessions.begin() as session,
            self.operation.admission.admit(session, self.parent) as sources,
        ):
            history = EmbeddingBatchPlanStore(self.parent, sources.selection, sources.policy).bind(
                session, binding, batch, authorize_child=authorization.authorize_binding
            )
            _require(history.bound == binding)


class RoutedCpuReferenceQueryExecution:
    """Typed pre-run strategy; never replaces the fixed numerical CPU adapter."""

    def __init__(
        self, group: CatalogCpuReferenceQueryBatchGroup, launcher: FixedNativeQueryLauncher
    ) -> None:
        _require(type(group) is CatalogCpuReferenceQueryBatchGroup)
        self.group, self.launcher = group, launcher

    def run(
        self, prepared: PreparedNativeQuery, *, source: CpuReferenceQueryExecutionContext
    ) -> EmbeddingReferenceQueryResult:
        _require(source.owner is self.group.owner)

        @contextmanager
        def source_transaction() -> Iterator[Session]:
            # Another Runner may lead the barrier. Never use its ContextVar to
            # authorize this child's original Workflow/command generation.
            with native_fenced_runner_transaction(
                self.group.operation.publisher.sessions,
                owner=source.owner,
                workflow_id=prepared.association.workflow_id,
                request=prepared.workflow_request,
                lease=source.command_lease,
            ) as session:
                yield session

        self.group.join(
            prepared,
            ReferenceQueryBatchSource(
                source.owner,
                prepared.workflow_request,
                prepared.association,
                source.command_lease,
                source_transaction,
            ),
        )
        return self.launcher.run(prepared)
