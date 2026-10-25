"""Finite in-process QUERY gathering around one original admitted physical batch."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from threading import Condition
from types import MappingProxyType

from eom_workflow.embedding_batch_plan_family import validate_embedding_batch_query_context
from eom_workflow.reference_query_execution import SupportedReferenceQueryWorkflowRequest

from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    PublishedEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_route import validate_embedding_batch_route
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    ReferenceQueryBatchSource,
)
from eom_workflow_runner.reference_query_batch_binding import prepare_reference_query_batch_binding
from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_GROUP_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedReferenceQueryBatchChild:
    ordinal: int
    material: PreparedBatchReferenceQuery
    source: ReferenceQueryBatchSource


class _Phase(StrEnum):
    GATHERING = "GATHERING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


# Same upper window as the fixed240s root-owner unit: compute retains its180s
# deadline; only canonical metadata publication may settle for the remaining60s.
_PUBLICATION_WAIT_SECONDS = 60


class CatalogReferenceQueryBatchGroup:
    """One bounded map/Condition, no persistent queue or cached source permission.

    Existing Runner threads retain their individual command claims/heartbeats.
    All SQL roots close before joining; the final child drives the sole original
    root channel. Source callbacks use each child's explicit owner transaction,
    not another Runner thread's ContextVar.
    """

    def __init__(
        self, active: ActiveEmbeddingBatchExecution, owner: CatalogReferenceQueryOwnerAdmission
    ) -> None:
        _require(type(active) is ActiveEmbeddingBatchExecution)
        _require(type(owner) is CatalogReferenceQueryOwnerAdmission)
        operation = active.operation
        _require(
            operation.publisher.engine is owner.catalog.engine
            and operation.publisher.settings.nas_artifact_root == owner.settings.nas_artifact_root
            and active.request.purpose == "REFERENCE_QUERY"
            and active.history.route is not None
            and active.history.route.decision.selected.backend.device == "CUDA"
        )
        with (
            operation.publisher.sessions.begin() as session,
            operation.admission.admit(session, active.request) as sources,
        ):
            self.selection = sources.selection
            self.indexes = sources.indexes
            self.routing_policy = sources.policy
        assert active.history.route is not None
        self.active, self.owner = active, owner
        self.decision = active.history.route.decision
        self.publisher, self.source_commit = operation.publisher, operation.source_commit
        self._ordinals = MappingProxyType(
            {
                anchor.source.item_revision_id: ordinal
                for ordinal, anchor in enumerate(self.selection.anchors)
            }
        )
        _require(len(self._ordinals) == len(self.selection.anchors))
        self._condition = Condition()
        self._phase = _Phase.GATHERING
        self._children: dict[int, PreparedReferenceQueryBatchChild] = {}
        self._result: PublishedEmbeddingBatchExecution | None = None

    def ordinal(self, request: SupportedReferenceQueryWorkflowRequest) -> int:
        ordinal = self._ordinals.get(request.context_request.anchor.source.item_revision_id)
        _require(ordinal is not None)
        assert ordinal is not None
        validate_embedding_batch_query_context(self.selection, self.decision, ordinal, request)
        config = self.owner.configuration
        _require(
            request.native_execution_policy == config.native_execution_policy
            and request.native_execution_policy_sha256 == config.native_execution_policy_sha256
            and request.runtime_bundle == config.runtime_bundle
            and config.registry.space == self.decision.selected.profile.space
        )
        return ordinal

    def assert_gathering(self) -> None:
        """Readiness/liveness only; actual actor/source/lease checks are separate."""
        with self._condition:
            _require(self._phase is _Phase.GATHERING)
            self.active.channel.require_direct_peer()

    def assert_available(self) -> None:
        """A completed original result is readable without reviving its root/socket."""
        with self._condition:
            if self._phase is _Phase.COMPLETED:
                _require(self._result is not None)
            else:
                _require(self._phase is _Phase.GATHERING)
                self.active.channel.require_direct_peer()

    def assert_original_material(self, material: PreparedBatchReferenceQuery) -> None:
        with self._condition:
            if self._phase is _Phase.COMPLETED:
                original = self._children.get(self.ordinal(material.workflow_request))
                _require(original is not None and original.material == material)
            else:
                _require(self._phase is _Phase.GATHERING)
                self.active.channel.require_direct_peer()

    def abort(self) -> None:
        """Wake pending children, never restart/stop another process or rewrite history."""
        with self._condition:
            if self._phase is not _Phase.COMPLETED:
                self._phase = _Phase.ABORTED
                self._condition.notify_all()

    def _completed_result(self) -> PublishedEmbeddingBatchExecution:
        """Caller holds the condition; thread updates are observed afresh here."""
        _require(self._phase is _Phase.COMPLETED and self._result is not None)
        assert self._result is not None
        return self._result

    def join(self, child: PreparedReferenceQueryBatchChild) -> PublishedEmbeddingBatchExecution:
        _require(type(child) is PreparedReferenceQueryBatchChild)
        _require(
            type(child.ordinal) is int
            and self.ordinal(child.material.workflow_request) == child.ordinal
            and child.source.owner is self.owner
            and child.source.request == child.material.workflow_request
            and child.source.launch == child.material.association
        )
        with self._condition:
            if self._phase is _Phase.COMPLETED:
                original = self._children.get(child.ordinal)
                _require(
                    original is not None
                    and original.material == child.material
                    and self._result is not None
                )
                return self._completed_result()
            _require(self._phase is _Phase.GATHERING and child.ordinal not in self._children)
            if time.monotonic_ns() >= self.active.channel.request.expires_monotonic_ns:
                self._phase = _Phase.ABORTED
                self._condition.notify_all()
                raise TimeoutError("REFERENCE_QUERY_BATCH_ORIGINAL_DEADLINE")
            self._children[child.ordinal] = child
            if len(self._children) == len(self.selection.anchors):
                children = tuple(self._children[ordinal] for ordinal in range(len(self._children)))
                self._phase = _Phase.RUNNING
                self._condition.notify_all()
            else:
                while self._phase in {_Phase.GATHERING, _Phase.RUNNING}:
                    deadline = self.active.channel.request.expires_monotonic_ns
                    if self._phase is _Phase.RUNNING:
                        deadline += _PUBLICATION_WAIT_SECONDS * 10**9
                    remaining = (deadline - time.monotonic_ns()) / 10**9
                    if remaining <= 0:
                        self._phase = _Phase.ABORTED
                        self._condition.notify_all()
                        raise TimeoutError("REFERENCE_QUERY_BATCH_ORIGINAL_DEADLINE")
                    self._condition.wait(remaining)
                return self._completed_result()
        try:
            result = self._run(children)
            with self._condition:
                _require(self._phase is _Phase.RUNNING)
                self._result = result
                self._phase = _Phase.COMPLETED
                self._condition.notify_all()
            return result
        except BaseException:
            self.abort()
            raise

    def _run(
        self, children: tuple[PreparedReferenceQueryBatchChild, ...]
    ) -> PublishedEmbeddingBatchExecution:
        route = self.active.history.route
        assert route is not None
        binding, batch = prepare_reference_query_batch_binding(
            self.active.request, route, tuple(child.material for child in children)
        )
        if self.indexes:
            validate_embedding_batch_route(
                policy=self.routing_policy,
                allocation=route.observation,
                decision=self.decision,
                batch=batch,
                indexes=self.indexes,
            )
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, tuple(child.source for child in children)
        )
        return self.active.run(binding, batch, authorization=authorization)
