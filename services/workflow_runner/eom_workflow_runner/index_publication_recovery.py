"""One exact retired, already-computed INDEX: normal publication, no numerical execution."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from threading import get_ident
from typing import Literal, NoReturn
from weakref import ReferenceType, WeakKeyDictionary, ref

from eom_catalog_service.embedding_registry_application import (
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.index_publication_recovery_authority import (
    IndexPublicationRecoveryAuthority,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import lock_current_local_indexing_service_metadata
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.native_embedding_coordinator import (
    NativeEmbeddingCoordinator,
    NativeEmbeddingCoordinatorHistory,
)
from eom_orchestrator.native_embedding_index_handoff import materialize_prepared_index_publication
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_workflow.index_publication_recovery import IndexPublicationRecoveryCommand
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_service,
)
from eom_workflow.local_embedding_request_v4 import LocalEmbeddingWorkflowRequestV4
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    SupportedLocalEmbeddingStepOutput,
    parse_supported_local_embedding_step_output,
)
from eom_workflow.native_embedding_coordinator import NativeCoordinatorAllocation
from eom_workflow.native_embedding_coordinator_v4 import (
    NativeCoordinatorCompletedV4,
    NativeCoordinatorIndexPreparedV4,
    NativeCoordinatorRegisteredV4,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from eom_workflow_runner.document_embedding_execution import OwnedDocumentEmbedding
from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_context import native_embedding_registry_scope
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_index_completion import NativeEmbeddingIndexCompletion
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from eom_workflow_runner.local_embedding_publications import native_embedding_publications
from eom_workflow_runner.local_indexing_runner_composition import (
    build_local_indexing_workflow_runner,
)
from eom_workflow_runner.models import (
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_step_completion import validate_completed_native_workflow
from eom_workflow_runner.native_workflow_maintenance_authority import (
    ALLOCATED_MAINTENANCE_TABLES,
    require_native_workflow_maintenance_owner,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandLeaseIdentity, NativeCommandActorSelection
from eom_workflow_runner.state_machine import record_workflow_event


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("INDEX_PUBLICATION_RECOVERY_SCOPE_INVALID")


class PreparedIndexRecoveryFence:
    """Actual OS/schema-owner admission and original checkpoint lock, per SQL root."""

    def __init__(self, command: IndexPublicationRecoveryCommand) -> None:
        self.command = IndexPublicationRecoveryCommand.model_validate(command)
        self._roots: WeakKeyDictionary[SessionTransaction, tuple[ReferenceType[Session], int]] = (
            WeakKeyDictionary()
        )

    def __call__(self, session: Session) -> None:
        _require(os.getresuid() == (0, 0, 0))
        root = session.get_transaction()
        _require(root is not None and root.is_active)
        assert root is not None
        prior = self._roots.get(root)
        if prior is None:
            # Admission locks must belong to the outer transaction, not to a
            # savepoint that can roll back independently. Registry may recheck
            # that same admitted root inside its uniqueness savepoint.
            _require(not session.in_nested_transaction())
            require_native_workflow_maintenance_owner(session, ALLOCATED_MAINTENANCE_TABLES)
            lock_current_local_indexing_service_metadata(session, self.command.current_service)
            self.original(session)
            self._roots[root] = (ref(session), get_ident())
        else:
            _require(prior[0]() is session and prior[1] == get_ident())
            # Original native-launch reads require the outer owner transaction.
            # Its retained locks protect the already checked identity while the
            # Registry uses a savepoint solely for its own uniqueness writes.
            if not session.in_nested_transaction():
                self.original(session)

    def original(
        self, session: Session
    ) -> tuple[
        LocalEmbeddingWorkflowRequestV4,
        WorkflowInstanceRecord,
        WorkflowStepRunRecord,
        NativeEmbeddingCoordinator,
        NativeEmbeddingCoordinatorHistory,
    ]:
        """No mutation: bind the current root to this exact prepared/completed computation."""
        command = self.command
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
            .with_for_update(nowait=True)
        )
        _require(workflow is not None)
        assert workflow is not None
        request = parse_supported_local_embedding_request(workflow.initial_request)
        _require(isinstance(request, LocalEmbeddingWorkflowRequestV4))
        assert isinstance(request, LocalEmbeddingWorkflowRequestV4)
        service = supported_local_embedding_request_service(request)
        _require(
            request.schema_version == "local-embedding-workflow-request/5.0"
            and request.space.runtime.device == request.resource_profile.device == "CPU"
            and request.request_sha256 == command.workflow_request_sha256
            and service.service_id == command.current_service.service_id
            and service.service_revision_id != command.current_service.service_revision_id
            and workflow.created_actor_type == "local_indexing_service"
            and workflow.created_actor_id == service.service_id
            and workflow.state in {"RUNNING", "COMPLETED"}
            and workflow.failure_code is None
        )
        step = session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                WorkflowStepRunRecord.step_key == "encode_batch",
                WorkflowStepRunRecord.attempt == 1,
            )
            .with_for_update(nowait=True)
        )
        _require(step is not None and step.state in {"RUNNING", "SUCCEEDED"})
        assert step is not None
        launch = read_native_embedding_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        _require(launch is not None and launch.intent.intent_sha256 == command.native_intent_sha256)
        assert launch is not None
        coordinator = NativeEmbeddingCoordinator(launch.intent, request)
        history = coordinator.read(session)
        _require(
            history.state in {"VALIDATING_RESULT", "COMMITTING", "SUCCEEDED"}
            and 2 <= len(history.records) <= 4
        )
        prepared = history.records[1].payload
        _require(isinstance(prepared, NativeCoordinatorIndexPreparedV4))
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
        _require(
            prepared.registration_command.request_sha256 == command.registration_request_sha256
        )
        association = read_native_embedding_launch_association(session, launch.intent, request)
        _require(association is not None and 1 <= len(association.owned_jobs) <= 4)
        assert association is not None
        references = tuple(
            sorted(
                (job.job_reference for job in association.owned_jobs), key=lambda row: row.job_id
            )
        )
        storage = EmbeddingEncodingReservationStorage
        rows = storage.reservations(
            session, storage.lock_references(session, references, lock=False)
        )
        _require(all(row.job.status == "SUCCEEDED" and row.completion is not None for row in rows))
        return request, workflow, step, coordinator, history


class NoNumericalRecoveryExecution:
    """Explicitly no model/runtime execution: canonical completed encodings only."""

    @property
    def device(self) -> Literal["CPU"]:
        return "CPU"

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> NoReturn:
        raise ValueError("INDEX_PUBLICATION_RECOVERY_NUMERICAL_EXECUTION_FORBIDDEN")

    def observe(self, intent: SupportedEmbeddingIntent) -> NoReturn:
        raise ValueError("INDEX_PUBLICATION_RECOVERY_INCOMPLETE_ENCODING")

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> NoReturn:
        raise ValueError("INDEX_PUBLICATION_RECOVERY_NUMERICAL_EXECUTION_FORBIDDEN")


class PreparedIndexPublicationExecutor:
    """Implements the existing Runner executor port without allocation or encoding paths."""

    def __init__(
        self,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        publisher: ControlFileSetPublisher,
        fence: PreparedIndexRecoveryFence,
    ) -> None:
        self.owner, self.publisher, self.fence = owner, publisher, fence
        self.completion = NativeEmbeddingIndexCompletion(
            owner, publisher, NoNumericalRecoveryExecution()
        )

    def evaluate(self, request: SupportedLocalEmbeddingRequest) -> RuntimeReadinessReport:
        _require(request.request_sha256 == self.fence.command.workflow_request_sha256)
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "prepared_index_publication",
                    ReadinessStatus.PASS,
                    "INDEX_PUBLICATION_RECOVERY_READY",
                    "publication only; claim requires current maintenance admission",
                ),
            )
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
    ) -> SupportedLocalEmbeddingStepOutput:
        _require(
            idempotency_key
            == (
                f"local-embedding-step:{workflow.workflow_id}:encode_batch:1:"
                f"{request.workflow_definition_sha256}"
            )
        )
        with fenced_transaction() as session:
            self.fence(session)
            original, _, _, coordinator, history = self.fence.original(session)
            _require(original == request)
        allocation = history.records[0].payload
        assert isinstance(allocation, NativeCoordinatorAllocation)
        if len(history.records) == 4:
            completed = history.records[3].payload
            assert isinstance(completed, NativeCoordinatorCompletedV4)
            with fenced_transaction() as session:
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
        prepared = history.records[1].payload
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
        publications = native_embedding_publications(self.publisher, allocation.source_commit)
        with materialize_prepared_index_publication(
            coordinator.intent.native_launch_job_id.removeprefix("job_"),
            prepared.registration_command.index_manifest.sha256,
        ) as (workspace, index):
            publications.artifacts.stage_index_manifest(index=index, workspace=workspace)
            return self.completion.publish(
                workflow,
                step,
                request,
                command_lease,
                self.owner.registry_caller(request),
                coordinator,
                allocation,
                (),
                fenced_transaction,
                publications,
                workspace=workspace,
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
        self.fence(session)
        return self.completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            output=output,
        )


def build_publication_recovery_executor(
    publisher: ControlFileSetPublisher,
    command: IndexPublicationRecoveryCommand,
    *,
    settings: CatalogSettings | None = None,
) -> PreparedIndexPublicationExecutor:
    fence = PreparedIndexRecoveryFence(command)
    settings = settings or CatalogSettings.from_environment()
    with publisher.sessions.begin() as session:
        fence(session)
        request, _, _, _, _ = fence.original(session)
        original_policy = KnowledgeRetrievalApplicationService(
            publisher.engine, settings
        ).resolve_local_indexing_access_policy(
            session,
            request.actor_context.service_policy_revision_id,
            sha256=request.actor_context.service_policy_sha256,
        )
    recovery = IndexPublicationRecoveryAuthority(
        supported_local_embedding_request_service(request),
        command.current_service,
        request.actor_context.service_policy_revision_id,
        request.actor_context.service_policy_sha256,
        command.current_policy_revision_id,
        command.current_policy_sha256,
        request.graph_snapshot,
        fence,
    )
    source = CatalogIndexingRegistrySourceAuthority(
        CatalogLocalIndexingSourceAuthority(
            KnowledgeRetrievalApplicationService(publisher.engine, settings), recovery
        ),
        request.actor_context.service_policy_revision_id,
        request.actor_context.service_policy_sha256,
        request.native_execution_policy_sha256,
        request.resource_profile.resource_profile_sha256,
        maximum_sources=original_policy.maximum_sources,
    )
    owner = CatalogLocalEmbeddingOwnerAdmission.for_indexing_service(
        publisher.engine,
        LocalEmbeddingOwnerConfiguration(
            EmbeddingRegistryOwnerConfiguration(
                request.corpus_id,
                request.namespace,
                request.space,
                original_policy.recipe,
                original_policy.source_classes,
            ),
            request.native_execution_policy,
            request.native_execution_policy_sha256,
        ),
        source_authority=source,
        settings=settings,
    )
    return PreparedIndexPublicationExecutor(owner, publisher, fence)


@dataclass(frozen=True, slots=True)
class RecoveredIndexPublication:
    workflow_id: str
    index_revision_id: str
    index_sha256: str
    binding_count: int
    resumed_commands: int
    state: Literal["COMPLETED"] = "COMPLETED"


def recover_prepared_index_publication(
    publisher: ControlFileSetPublisher,
    command: IndexPublicationRecoveryCommand,
    *,
    source_commit: str,
    settings: CatalogSettings | None = None,
) -> RecoveredIndexPublication:
    """Explicit root operation; no API, new submission, activation or numerical launcher.

    Same original command/receipts are handled by the existing Runner. Source
    authorization is limited to equivalent current grants and the pinned Graph.
    """
    _require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None)
    executor = build_publication_recovery_executor(publisher, command, settings=settings)
    with publisher.sessions.begin() as session:
        principal = require_native_workflow_maintenance_owner(session, ALLOCATED_MAINTENANCE_TABLES)
        executor.fence(session)
        request, _, _, _, history = executor.fence.original(session)
        executor.owner.resolve_submission(session, request)
        if len(history.records) == 2:
            prepared = history.records[1].payload
            assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
            previous = executor.owner.catalog.resolve_indexing_namespace_predecessor(
                session,
                executor.owner.registry_caller(request),
                native_embedding_registry_scope(request),
            )
            selected = None if previous is None else previous[1].index_revision_id
            if selected != prepared.registration_command.expected_current_index_revision_id:
                raise ValueError("INDEX_PUBLICATION_SUPERSEDED_REQUIRES_SUCCESSOR")
        event = session.scalar(
            select(WorkflowEventRecord).where(
                WorkflowEventRecord.workflow_id == command.workflow_id,
                WorkflowEventRecord.event_type == "INDEX_PUBLICATION_RECOVERY_AUTHORIZED",
            )
        )
        if event is None:
            record_workflow_event(
                session,
                command.workflow_id,
                "INDEX_PUBLICATION_RECOVERY_AUTHORIZED",
                actor_type="database_owner",
                actor_id=principal,
                command_id=None,
                payload={
                    "command": command.model_dump(mode="json"),
                    "source_commit": source_commit,
                },
            )
        else:
            _require(event.payload.get("command") == command.model_dump(mode="json"))
    service = supported_local_embedding_request_service(request)
    runner = build_local_indexing_workflow_runner(
        executor,
        NativeCommandActorSelection(
            "local_indexing_service", service.service_id, request.namespace, service
        ),
    )
    resumed = 0
    for _ in range(3):
        with publisher.sessions.begin() as session:
            executor.fence(session)
            _, workflow, _, _, _ = executor.fence.original(session)
            if workflow.state == "COMPLETED":
                break
        result = runner.run_once(command.workflow_id)
        if result is None:
            raise ValueError("INDEX_PUBLICATION_RECOVERY_NOT_CLAIMABLE")
        resumed += 1
        if result.state != "SUCCEEDED":
            raise ValueError("INDEX_PUBLICATION_RECOVERY_COMMAND_NOT_COMPLETED")
    with publisher.sessions.begin() as session:
        executor.fence(session)
        request, workflow, step, _, history = executor.fence.original(session)
        executor.owner.resolve_submission(session, request)
        _require(len(history.records) == 4)
        prepared, registered, completed = (row.payload for row in history.records[1:])
        assert isinstance(prepared, NativeCoordinatorIndexPreparedV4)
        assert isinstance(registered, NativeCoordinatorRegisteredV4)
        assert isinstance(completed, NativeCoordinatorCompletedV4)
        output = parse_supported_local_embedding_step_output(step.output_pointer_manifest)
        _require(output == completed.output)
        receipt = resolve_native_embedding_completion(session, executor.owner.settings, output)
        _require(
            receipt.registration_command == prepared.registration_command
            and receipt.registration_result == registered.registration_result
        )
        verify_embedding_index_registration_observation(
            session,
            executor.owner.registry_caller(request),
            prepared.registration_command,
            registered.registration_result,
            executor.owner.catalog,
        )
        validate_completed_native_workflow(session, workflow, step, output)
        return RecoveredIndexPublication(
            workflow.workflow_id,
            prepared.registration_command.index_revision_id,
            prepared.registration_command.index_sha256,
            prepared.registration_command.binding_count,
            resumed,
        )
