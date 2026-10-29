"""Common encoding reservations/publication around one explicitly selected numerical adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingResult,
)
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_artifact_store import (
    PublishedEmbeddingArtifacts,
)
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetPublisher,
)
from eom_orchestrator.native_embedding_coordinator import (
    NativeEmbeddingCoordinator,
)
from eom_orchestrator.native_embedding_launch_identity import (
    create_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    SupportedEmbeddingCompletedEvent,
    SupportedEmbeddingIntent,
    build_supported_owned_incremental_embedding_input,
    parse_supported_embedding_association,
    parse_supported_embedding_completed,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobRequest,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    local_embedding_launch_protocol,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_embedding_index_refresh import LocalEmbeddingIndexRefreshRequest
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import LocalEmbeddingSourcePlanV2
from eom_workflow.local_embedding_source_plan_v3 import LocalEmbeddingSourcePlanV3
from eom_workflow.local_embedding_workflow_receipt_v2 import SupportedLocalEmbeddingStepOutput
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorAllocation,
    NativeCoordinatorCompleted,
)
from eom_workflow.native_embedding_coordinator_v2 import NativeCoordinatorCompletedV2
from eom_workflow.native_embedding_coordinator_v3 import NativeCoordinatorCompletedV3
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingExecution,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.local_embedding_encoding_admission import (
    CatalogEncodingOwnerAdmission,
    CurrentEncodingExecution,
)
from eom_workflow_runner.local_embedding_execution_context import (
    native_embedding_registry_scope,
    resolve_native_execution_sources,
)
from eom_workflow_runner.local_embedding_execution_port import (
    LocalEmbeddingStepPending,
    NativeFencedRunnerTransaction,
)
from eom_workflow_runner.local_embedding_index_completion import NativeEmbeddingIndexCompletion
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


def _encoding_requests(
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2 | LocalEmbeddingSourcePlanV3,
    *,
    reusable_encodings: frozenset[str] = frozenset(),
) -> tuple[EmbeddingEncodingJobRequest, ...]:
    encodings = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
    values = []
    for key in sorted(set(encodings) - reusable_encodings):
        body = {
            "schema_version": "embedding-encoding-job/1.0",
            "record_type": "REQUEST",
            "purpose": "LOCAL_EMBEDDING",
            "space": plan.space.model_dump(mode="json"),
            "encoding": encodings[key].model_dump(mode="json"),
        }
        values.append(
            EmbeddingEncodingJobRequest.model_validate(
                body | {"request_sha256": content_sha256(body)}
            )
        )
    return tuple(values)


def _completion_events(
    association: SupportedEmbeddingAssociation,
    result: IncrementalEmbeddingResult,
    published: PublishedEmbeddingArtifacts,
) -> tuple[SupportedEmbeddingCompletedEvent, ...]:
    events = []
    for ordinal, owned in enumerate(association.owned_jobs):
        body = {
            "native_launch_job_id": association.intent.native_launch_job_id,
            "result_manifest": published.result.model_dump(mode="json"),
            "result_sha256": result.result_sha256,
            "shard_manifest": published.shard.model_dump(mode="json"),
            "shard_sha256": result.shard.shard_sha256,
            "binary_member": published.binary.model_dump(mode="json"),
            "row_ref": {
                "shard_manifest": published.shard.model_dump(mode="json"),
                "row_index": ordinal,
                "encoding_sha256": owned.request.encoding.encoding_sha256,
            },
        }
        receipt = body | {"receipt_sha256": content_sha256(body)}
        body = {
            "schema_version": association.schema_version,
            "record_type": "COMPLETED",
            "owned_job": owned.model_dump(mode="json"),
            "intent": association.intent.model_dump(mode="json"),
            "launch_association_sha256": association.association_sha256,
            "receipt": receipt,
        }
        events.append(
            parse_supported_embedding_completed(body | {"event_sha256": content_sha256(body)})
        )
    return tuple(events)


class CatalogNativeEmbeddingExecutor:
    """No implicit activation/fallback. One common current-owner and completion path."""

    def __init__(
        self,
        *,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        publisher: ControlFileSetPublisher,
        execution_backend: DocumentEmbeddingExecution,
        runtime_profile: LocalEmbeddingRuntimeProfile,
        source_commit: str,
    ) -> None:
        self.owner, self.publisher, self.execution_backend = owner, publisher, execution_backend
        self.runtime_profile = LocalEmbeddingRuntimeProfile.model_validate(runtime_profile)
        if (
            self.runtime_profile.space != owner.configuration.registry.space
            or self.runtime_profile.resource_profile.device != execution_backend.device
        ):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONFIGURATION_INVALID")
        native_embedding_publications(
            publisher, source_commit
        )  # validate configured provenance, not activation
        self.source_commit = source_commit
        self._index_completion = NativeEmbeddingIndexCompletion(owner, publisher, execution_backend)

    def _assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        request = parse_supported_local_embedding_request(request)
        profile = self.runtime_profile
        if (
            request.space != profile.space
            or request.runtime_bundle != profile.runtime_bundle
            or request.resource_profile != profile.resource_profile
            or request.native_execution_policy != self.owner.configuration.native_execution_policy
            or request.native_execution_policy_sha256
            != self.owner.configuration.native_execution_policy_sha256
            or request.corpus_id != self.owner.configuration.registry.corpus_id
            or request.namespace != self.owner.configuration.registry.namespace
        ):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONTROLS_MISMATCH")
        self.execution_backend.assert_current_runtime(request)

    def evaluate(self, request: SupportedLocalEmbeddingRequest) -> RuntimeReadinessReport:
        try:
            self._assert_current_runtime(request)
            check = RuntimeReadinessCheck(
                "native_document_index",
                ReadinessStatus.PASS,
                "LOCAL_EMBEDDING_READY",
                "exact selected document controls are available",
            )
        except (ValueError, OSError):
            check = RuntimeReadinessCheck(
                "native_document_index",
                ReadinessStatus.FAIL,
                "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE",
                "configured document boundary is unavailable",
            )
        return RuntimeReadinessReport((check,))

    def _current(
        self,
        session: Session,
        *,
        workflow_id: str,
        step_run_id: str,
        request: SupportedLocalEmbeddingRequest,
        lease: CommandLeaseIdentity,
    ) -> ResolvedLocalEmbeddingSources:
        return resolve_native_execution_sources(
            self.owner,
            session,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            request=request,
            lease=lease,
        )

    def _reservations(
        self,
        request: SupportedLocalEmbeddingRequest,
        intent: SupportedEmbeddingIntent,
        lease: CommandLeaseIdentity,
    ) -> EmbeddingEncodingReservations:
        return EmbeddingEncodingReservations(
            self.publisher.sessions,
            CatalogEncodingOwnerAdmission(
                self.owner, CurrentEncodingExecution(request, intent, lease), self.execution_backend
            ),
        )

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedLocalEmbeddingRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> SupportedLocalEmbeddingStepOutput | LocalEmbeddingStepPending:
        expected_key = (
            f"local-embedding-step:{workflow.workflow_id}:encode_batch:1:"
            f"{request.workflow_definition_sha256}"
        )
        try:
            self._assert_current_runtime(request)
        except (ValueError, OSError) as error:
            # Readiness is a redacted public projection. Execution must retain
            # the actual failure chain for the existing bounded site reporter.
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID") from error
        if idempotency_key != expected_key:
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID")
        caller = self.owner.registry_caller(request)
        with fenced_transaction() as session:
            sources = self._current(
                session,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                request=request,
                lease=command_lease,
            )
            self.owner.catalog.require_index_publication_scope(
                session, caller, native_embedding_registry_scope(request)
            )
            launch = create_native_embedding_launch(
                session,
                request=request,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                command_id=command_lease.command_id,
                runner_id=command_lease.runner_id,
                lease_generation=command_lease.lease_generation,
            )
            coordinator = NativeEmbeddingCoordinator(launch.intent, request)
            history = coordinator.read(session)
            if history.state in {"FAILED", "CANCELLED"}:
                raise ValueError("LOCAL_EMBEDDING_EXECUTOR_TERMINAL_HISTORY")
            if not history.records:
                allocation = NativeCoordinatorAllocation(
                    index_producer=new_native_artifact_producer(),
                    receipt_producer=new_native_artifact_producer(),
                    created_at=datetime.now(UTC),
                    source_commit=self.source_commit,
                )
                history = coordinator.append(
                    session, coordinator.checkpoint("ALLOCATION", allocation)
                )
            allocated = history.records[0].payload
            assert isinstance(allocated, NativeCoordinatorAllocation)
            allocation = allocated
            if len(history.records) == 4:
                completed = history.records[3].payload
                assert isinstance(
                    completed,
                    NativeCoordinatorCompleted
                    | NativeCoordinatorCompletedV2
                    | NativeCoordinatorCompletedV3,
                )
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
            reusable_encodings = frozenset[str]()
            if isinstance(request, LocalEmbeddingWorkflowRequestV2):
                basis = self.owner.catalog.prepare_mixed_index_basis(
                    session, caller, native_embedding_registry_scope(request)
                )
                reusable_encodings = frozenset(
                    row.encoding.encoding_sha256 for row in basis.reusable_rows
                )
        if isinstance(request, LocalEmbeddingIndexRefreshRequest) or (
            isinstance(request, LocalEmbeddingWorkflowRequestV2)
            and not _encoding_requests(
                sources.admission.plan, reusable_encodings=reusable_encodings
            )
        ):
            # Reuse canonical registry rows directly. A membership-only request
            # must never allocate encoding reservations or launch numerical work.
            return self._index_completion.publish(
                workflow,
                step,
                request,
                command_lease,
                caller,
                coordinator,
                allocation,
                (),
                fenced_transaction,
                native_embedding_publications(self.publisher, allocation.source_commit),
            )
        # Reservation API owns short independent roots. Never hold Workflow SQL locks here.
        reservations = self._reservations(request, launch.intent, command_lease)
        publications = native_embedding_publications(self.publisher, allocation.source_commit)
        encoding_requests = _encoding_requests(
            sources.admission.plan, reusable_encodings=reusable_encodings
        )
        readings = reservations.reserve_and_attach(encoding_requests, launch.intent)
        if any(r.status == "FAILED" for r in readings):
            readings = reservations.retry_known_failed(
                encoding_requests,
                launch.intent,
            )
        if any(r.status in {"FAILED", "CANCELLED"} for r in readings):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_ENCODING_FAILED")
        own = tuple(
            r.owned_job for r in readings if r.owner_intent == launch.intent and r.status == "OWNED"
        )
        if own:
            with fenced_transaction() as session:
                sources = self._current(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    request=request,
                    lease=command_lease,
                )
                association = read_native_embedding_launch_association(
                    session, launch.intent, request
                )
                if association is None:
                    native_input = build_supported_owned_incremental_embedding_input(
                        sources.admission.plan,
                        sources.entries,
                        owned_jobs=own,
                        native_launch_job_id=launch.intent.native_launch_job_id,
                        resources=request.resource_profile,
                    )
                    saved = publications.controls.publish_owned_input(
                        native_input,
                        idempotency_key="native-owned-input:" + launch.intent.native_launch_job_id,
                        created_at=allocation.created_at,
                    )
                    body = {
                        "schema_version": local_embedding_launch_protocol(request)[0],
                        "record_type": "LAUNCH_ASSOCIATION",
                        "intent": launch.intent.model_dump(mode="json"),
                        "owned_jobs": [j.model_dump(mode="json") for j in own],
                        "owned_input": saved.member.model_dump(mode="json"),
                        "owned_input_request_sha256": native_input.request_sha256,
                        "owned_input_set_sha256": native_input.input_set_sha256,
                    }
                    association = parse_supported_embedding_association(
                        body | {"association_sha256": content_sha256(body)}
                    )
                else:
                    native_input = CatalogLocalEmbeddingEncodingArtifacts(
                        session, self.owner.settings
                    ).resolve_input(association)
            reservations.bind_launch(association)
            output = self.execution_backend.execute(
                OwnedDocumentEmbedding(association, native_input),
                source=CatalogEncodingOwnerAdmission(
                    self.owner,
                    CurrentEncodingExecution(request, launch.intent, command_lease),
                    self.execution_backend,
                ),
                transaction=fenced_transaction,
            )
            if output is None:
                return LocalEmbeddingStepPending(
                    tuple(
                        sorted(
                            reservations.read(
                                tuple(
                                    sorted(
                                        (r.owned_job.job_reference for r in readings),
                                        key=lambda ref: ref.job_id,
                                    )
                                )
                            ),
                            key=lambda r: r.owned_job.request.encoding.encoding_sha256,
                        )
                    )
                )
            with fenced_transaction() as session:
                sources = self._current(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    request=request,
                    lease=command_lease,
                )
                published = publications.artifacts.publish_owned_batch(
                    workflow_request=request,
                    plan=sources.admission.plan,
                    policy=sources.admission.policy,
                    association=association,
                    request=native_input,
                    workspace=output.workspace,
                    created_at=allocation.created_at,
                )
            reservations.complete(_completion_events(association, output.result, published))
        readings = tuple(
            sorted(
                reservations.read(
                    tuple(
                        sorted(
                            (r.owned_job.job_reference for r in readings),
                            key=lambda ref: ref.job_id,
                        )
                    )
                ),
                key=lambda r: r.owned_job.request.encoding.encoding_sha256,
            )
        )
        if any(r.status != "COMPLETED" for r in readings):
            return LocalEmbeddingStepPending(readings)
        return self._index_completion.publish(
            workflow,
            step,
            request,
            command_lease,
            caller,
            coordinator,
            allocation,
            readings,
            fenced_transaction,
            publications,
        )

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedLocalEmbeddingRequest,
        command_lease: CommandLeaseIdentity,
        output: SupportedLocalEmbeddingStepOutput,
    ) -> SupportedLocalEmbeddingStepOutput:
        return self._index_completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            output=output,
        )
