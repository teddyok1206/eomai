"""Actual source-owner finite execution through existing parent, root and publication owners."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_service.embedding_batch_control_connection import (
    dispatch_embedding_batch_control,
    owner_embedding_batch_listener,
)
from eom_catalog_service.embedding_batch_control_workspace import stage_embedding_batch_control
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_workspace import stage_owner_embedding_batch
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import PublishedLocalEmbeddingControl
from eom_workflow.embedding_batch_owner_control import (
    EmbeddingBatchRootBusy,
    EmbeddingBatchRootReady,
    validate_embedding_batch_owner_context,
)
from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_PROTOCOL,
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)

from eom_workflow_runner.embedding_batch_execution_publication import (
    CatalogEmbeddingBatchExecutionPublication,
)
from eom_workflow_runner.embedding_batch_plan_admission import CatalogEmbeddingBatchPlanAdmission
from eom_workflow_runner.embedding_batch_result_read import (
    VerifiedLocalEmbeddingBatchResult,
    read_verified_embedding_batch_result,
)
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_EXECUTION_INVALID")


@dataclass(frozen=True, slots=True)
class ExistingEmbeddingBatchExecution:
    """Original durable planning history only; never a new dispatch or compute grant."""

    history: EmbeddingBatchPlanHistory


@dataclass(frozen=True, slots=True)
class UnavailableEmbeddingBatchExecution:
    """Verified original precompute unavailability; CPU owner must still authorize/execute."""

    history: EmbeddingBatchPlanHistory
    root_observation: EmbeddingBatchRootBusy


@dataclass(frozen=True, slots=True)
class PublishedEmbeddingBatchExecution:
    publication: PublishedLocalEmbeddingControl
    verified: VerifiedLocalEmbeddingBatchResult


class _Phase(StrEnum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


class ActiveEmbeddingBatchExecution:
    """One original admitted channel; child preparation/reservations remain with their owners.

    No transaction survives yield into child preparation or numerical work. This
    object cannot dispatch a second root or reauthorize from cached source DTOs.
    """

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        request: SupportedEmbeddingBatchRequest,
        history: EmbeddingBatchPlanHistory,
        channel: EmbeddingBatchOwnerChannel,
        ready: EmbeddingBatchRootReady,
    ) -> None:
        self.operation, self.request, self.history = operation, request, history
        self.channel, self.ready = channel, ready
        self._phase = _Phase.READY

    def run(
        self,
        binding: EmbeddingBatchBound,
        batch: EmbeddingWorkBatchInput,
        *,
        authorization: CatalogEmbeddingBatchSourceAuthorization,
    ) -> PublishedEmbeddingBatchExecution:
        """Bind exact original children, serve fresh checks, verify/ACK, then publish metadata."""
        _require(self._phase is _Phase.READY)
        self._phase = _Phase.EXECUTING
        try:
            _require(type(authorization) is CatalogEmbeddingBatchSourceAuthorization)
            binding = EmbeddingBatchBound.model_validate(binding)
            batch = parse_embedding_work_batch_input(batch)
            _require(authorization.batch_request_sha256 == batch.request_sha256)
            # A current actual root channel is required before the short BOUND
            # transaction. A pure route value cannot supply physical authority.
            self.channel.require_direct_peer()
            operation = self.operation
            with (
                operation.publisher.sessions.begin() as session,
                operation.admission.admit(session, self.request) as sources,
            ):
                store = EmbeddingBatchPlanStore(self.request, sources.selection, sources.policy)
                history = store.read(session)
                _require(history == self.history)
                store.bind(
                    session,
                    binding,
                    batch,
                    authorize_child=authorization.authorize_binding,
                )
            staged = stage_owner_embedding_batch(self.channel.request, self.ready, binding, batch)
            authorization.authorize_batch()
            self.channel.send_binding(staged.notice)
            while self.channel.authorize_next(authorization.authorize_child) is None:
                pass  # Channel bounds the original deadline and number of checks.
            verified = read_verified_embedding_batch_result(
                self.channel, self.ready, staged, authorization=authorization
            )

            def verify_ack(_completed: object) -> None:
                verified.assert_current()
                authorization.authorize_batch()

            self.channel.acknowledge_completion(verify_ack)
            self.channel.close()
            # This publication reopens actual current parent/source/lease fences;
            # it uses only the verified terminal snapshot, not a live root PID.
            saved = CatalogEmbeddingBatchExecutionPublication(
                operation.admission,
                self.request,
                authorization,
                operation.publisher,
                source_commit=operation.source_commit,
            ).publish(self.channel, verified)
            self._phase = _Phase.COMPLETED
            return PublishedEmbeddingBatchExecution(saved, verified)
        except BaseException:
            self._phase = _Phase.INTERRUPTED
            self.channel.close()
            raise

    def close(self) -> None:
        if self._phase in {_Phase.READY, _Phase.EXECUTING}:
            self._phase = _Phase.INTERRUPTED
        self.channel.close()


class CatalogEmbeddingBatchExecution:
    """Compose existing official owners, not a new registry, queue or numerical executor."""

    def __init__(
        self,
        admission: CatalogEmbeddingBatchPlanAdmission,
        publisher: ControlFileSetPublisher,
        *,
        source_commit: str,
        controller_release: str,
    ) -> None:
        _require(
            type(admission) is CatalogEmbeddingBatchPlanAdmission
            and publisher.engine is admission.catalog.engine
            and publisher.settings.nas_artifact_root == admission.catalog.settings.nas_artifact_root
            and re.fullmatch(r"[0-9a-f]{40}", source_commit, re.ASCII) is not None
            and re.fullmatch(r"[0-9a-f]{40}", controller_release, re.ASCII) is not None
        )
        self.admission, self.publisher = admission, publisher
        self.source_commit, self.controller_release = source_commit, controller_release

    @contextmanager
    def open(
        self, request: SupportedEmbeddingBatchRequest, allocation: EmbeddingBatchAllocation
    ) -> Iterator[
        ActiveEmbeddingBatchExecution
        | UnavailableEmbeddingBatchExecution
        | ExistingEmbeddingBatchExecution
    ]:
        """Only the newly committed allocation owns dispatch; replay never starts a root.

        Caller supplies the original schema-validated candidate, not authority.
        Canonical admission validates its exact current source/control closure.
        An interrupted original requires supported reconciliation, not this path.
        """
        request = parse_embedding_batch_plan_request(request)
        allocation = EmbeddingBatchAllocation.model_validate(allocation)
        with (
            self.publisher.sessions.begin() as session,
            self.admission.admit(session, request) as sources,
        ):
            history, created = EmbeddingBatchPlanStore(
                request, sources.selection, sources.policy
            ).allocate(session, allocation)
        if not created:
            yield ExistingEmbeddingBatchExecution(history)
            return
        staged = stage_embedding_batch_control(history.allocation.control_request)
        with owner_embedding_batch_listener(staged) as listener:
            dispatch_embedding_batch_control(listener)
            channel = listener.accept_root(controller_release=self.controller_release)
            active = None
            try:
                notice = channel.receive_allocation()
                with (
                    self.publisher.sessions.begin() as session,
                    self.admission.admit(session, request) as sources,
                ):
                    route = _root_route(request, history.allocation, sources.policy, notice)
                    history = EmbeddingBatchPlanStore(
                        request, sources.selection, sources.policy
                    ).route(session, route)
                if isinstance(notice, EmbeddingBatchRootBusy):
                    channel.close()
                    yield UnavailableEmbeddingBatchExecution(history, notice)
                else:
                    active = ActiveEmbeddingBatchExecution(self, request, history, channel, notice)
                    yield active
            finally:
                if active is not None:
                    active.close()
                channel.close()


def _root_route(
    request: SupportedEmbeddingBatchRequest,
    allocation: EmbeddingBatchAllocation,
    policy: EmbeddingDeviceRoutingPolicy,
    notice: EmbeddingBatchRootReady | EmbeddingBatchRootBusy,
) -> EmbeddingBatchRoute:
    """Only the original actual channel caller may turn root observations into a plan."""
    _require(type(notice) in {EmbeddingBatchRootReady, EmbeddingBatchRootBusy})
    validate_embedding_batch_owner_context(
        allocation.control_request, notice.controller_release, notice
    )
    ready = isinstance(notice, EmbeddingBatchRootReady)
    observed_at = (
        notice.observed_at if isinstance(notice, EmbeddingBatchRootReady) else notice.retired_at
    )
    observation_body = dict(
        schema_version="embedding-device-routing/1.0",
        message_type="ALLOCATION_OBSERVATION",
        allocation_attempt_id=allocation.control_request.allocation_attempt_id,
        request_sha256=request.request_sha256,
        policy_sha256=policy.policy_sha256,
        phase="PRE_EXECUTION",
        cuda_launch_state="NOT_STARTED",
        status="ACQUIRED" if ready else "BUSY",
        allocation_reference_sha256=notice.message_sha256,
        observed_at=observed_at.isoformat().replace("+00:00", "Z"),
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        observation_body | {"observation_sha256": content_sha256(observation_body)}
    )
    route_body = dict(
        schema_version=BATCH_PLAN_PROTOCOL,
        message_type="ROUTED",
        request_sha256=request.request_sha256,
        allocation_record_sha256=allocation.record_sha256,
        observation=observation.model_dump(mode="json"),
        decision=plan_embedding_device_route(policy, observation).model_dump(mode="json"),
    )
    return EmbeddingBatchRoute.model_validate(
        route_body | {"record_sha256": content_sha256(route_body)}
    )
