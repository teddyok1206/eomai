"""Concrete operator-seed CPU composition using existing owners and fixed native units."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingResult,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
)
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
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
from eom_orchestrator.native_embedding_index_handoff import (
    PreparedNativeIndex,
    mark_native_index_launch_started,
    stage_native_index,
)
from eom_orchestrator.native_embedding_index_systemd import (
    FixedNativeIndexLauncher,
    NativeIndexLaunchError,
)
from eom_orchestrator.native_embedding_launch_identity import (
    create_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
    build_owned_incremental_embedding_input,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_embedding_request import (
    LocalEmbeddingWorkflowRequestV11,
    require_local_embedding_operator_seed,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_workflow_receipt import (
    LocalEmbeddingStepOutput,
)
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
    NativeCoordinatorCompleted,
    native_coordinator_checkpoint,
)
from sqlalchemy.orm import Session

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
from eom_workflow_runner.local_embedding_publications import native_embedding_publications
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


def _producer() -> NativeArtifactProducerIdentity:
    return NativeArtifactProducerIdentity(
        job_id=new_job_id(),
        artifact_id=new_logical_artifact_id(),
        artifact_revision_id=new_revision_id(),
    )


def _encoding_requests(plan: LocalEmbeddingSourcePlan) -> tuple[EmbeddingEncodingJobRequest, ...]:
    encodings = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
    values = []
    for key in sorted(encodings):
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
    association: LocalEmbeddingLaunchAssociation,
    result: IncrementalEmbeddingResult,
    published: PublishedEmbeddingArtifacts,
) -> tuple[EmbeddingEncodingCompletedEvent, ...]:
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
            "schema_version": "embedding-encoding-job/1.0",
            "record_type": "COMPLETED",
            "owned_job": owned.model_dump(mode="json"),
            "intent": association.intent.model_dump(mode="json"),
            "launch_association_sha256": association.association_sha256,
            "receipt": receipt,
        }
        events.append(
            EmbeddingEncodingCompletedEvent.model_validate(
                body | {"event_sha256": content_sha256(body)}
            )
        )
    return tuple(events)


class CatalogNativeEmbeddingExecutor:
    """No implicit activation. Trusted composition supplies current Identity and admitted CPU."""

    def __init__(
        self,
        *,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        publisher: ControlFileSetPublisher,
        launcher: FixedNativeIndexLauncher,
        runtime_profile: LocalEmbeddingRuntimeProfile,
        source_commit: str,
    ) -> None:
        self.owner, self.publisher, self.launcher = owner, publisher, launcher
        self.runtime_profile = LocalEmbeddingRuntimeProfile.model_validate(runtime_profile)
        if (
            self.runtime_profile.space != owner.configuration.registry.space
            or self.runtime_profile.resource_profile.device != "CPU"
        ):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONFIGURATION_INVALID")
        native_embedding_publications(
            publisher, source_commit
        )  # validate configured provenance, not activation
        self.source_commit = source_commit
        self._index_completion = NativeEmbeddingIndexCompletion(owner, publisher, launcher)

    def evaluate(self, request: LocalEmbeddingWorkflowRequestV11) -> RuntimeReadinessReport:
        try:
            require_local_embedding_operator_seed(request)
            profile = self.runtime_profile
            if (
                request.space != profile.space
                or request.runtime_bundle != profile.runtime_bundle
                or request.resource_profile != profile.resource_profile
                or request.native_execution_policy
                != self.owner.configuration.native_execution_policy
                or request.native_execution_policy_sha256
                != self.owner.configuration.native_execution_policy_sha256
                or request.corpus_id != self.owner.configuration.registry.corpus_id
                or request.namespace != self.owner.configuration.registry.namespace
            ):
                raise ValueError("configured native controls differ")
            self.launcher.assert_current_runtime()
            check = RuntimeReadinessCheck(
                "native_cpu_index",
                ReadinessStatus.PASS,
                "LOCAL_EMBEDDING_READY",
                "exact installed CPU controls are available",
            )
        except (ValueError, OSError):
            check = RuntimeReadinessCheck(
                "native_cpu_index",
                ReadinessStatus.FAIL,
                "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE",
                "configured native CPU boundary is unavailable",
            )
        return RuntimeReadinessReport((check,))

    def _current(
        self,
        session: Session,
        *,
        workflow_id: str,
        step_run_id: str,
        request: LocalEmbeddingWorkflowRequestV11,
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
        request: LocalEmbeddingWorkflowRequestV11,
        intent: LocalEmbeddingLaunchIntent,
        lease: CommandLeaseIdentity,
    ) -> EmbeddingEncodingReservations:
        return EmbeddingEncodingReservations(
            self.publisher.sessions,
            CatalogEncodingOwnerAdmission(
                self.owner, CurrentEncodingExecution(request, intent, lease), self.launcher
            ),
        )

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: LocalEmbeddingWorkflowRequestV11,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> LocalEmbeddingStepOutput | LocalEmbeddingStepPending:
        expected_key = (
            f"local-embedding-step:{workflow.workflow_id}:encode_batch:1:"
            f"{request.workflow_definition_sha256}"
        )
        if not self.evaluate(request).ready or idempotency_key != expected_key:
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID")
        caller = EmbeddingRegistryCaller(require_local_embedding_operator_seed(request).operator_id)
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
                    index_producer=_producer(),
                    receipt_producer=_producer(),
                    created_at=datetime.now(UTC),
                    source_commit=self.source_commit,
                )
                history = coordinator.append(
                    session, native_coordinator_checkpoint(launch.intent, "ALLOCATION", allocation)
                )
            allocated = history.records[0].payload
            assert isinstance(allocated, NativeCoordinatorAllocation)
            allocation = allocated
            if len(history.records) == 4:
                completed = history.records[3].payload
                assert isinstance(completed, NativeCoordinatorCompleted)
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
        # Reservation API owns short independent roots. Never hold Workflow SQL locks here.
        reservations = self._reservations(request, launch.intent, command_lease)
        publications = native_embedding_publications(self.publisher, allocation.source_commit)
        readings = reservations.reserve_and_attach(
            _encoding_requests(sources.admission.plan), launch.intent
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
                    native_input = build_owned_incremental_embedding_input(
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
                        "schema_version": "embedding-encoding-job/1.0",
                        "record_type": "LAUNCH_ASSOCIATION",
                        "intent": launch.intent.model_dump(mode="json"),
                        "owned_jobs": [j.model_dump(mode="json") for j in own],
                        "owned_input": saved.member.model_dump(mode="json"),
                        "owned_input_request_sha256": native_input.request_sha256,
                        "owned_input_set_sha256": native_input.input_set_sha256,
                    }
                    association = LocalEmbeddingLaunchAssociation.model_validate(
                        body | {"association_sha256": content_sha256(body)}
                    )
                else:
                    native_input = CatalogLocalEmbeddingEncodingArtifacts(
                        session, self.owner.settings
                    ).resolve_input(association)
            reservations.bind_launch(association)
            prepared = PreparedNativeIndex(
                launch.intent.native_launch_job_id.removeprefix("job_"), association, native_input
            )
            with fenced_transaction() as session:
                self._current(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    request=request,
                    lease=command_lease,
                )
                stage_native_index(prepared)
                mark_native_index_launch_started(prepared)
            try:
                result = self.launcher.run(prepared)
            except NativeIndexLaunchError as error:
                if error.code not in {"NATIVE_INDEX_BUSY", "NATIVE_INDEX_UNCERTAIN"}:
                    raise
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
                    workspace=prepared.workspace,
                    created_at=allocation.created_at,
                )
            reservations.complete(_completion_events(association, result, published))
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
        request: LocalEmbeddingWorkflowRequestV11,
        command_lease: CommandLeaseIdentity,
        output: LocalEmbeddingStepOutput,
    ) -> LocalEmbeddingStepOutput:
        return self._index_completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            output=output,
        )
