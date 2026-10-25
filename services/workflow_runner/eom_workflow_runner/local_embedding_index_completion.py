"""Index publication/registration and genuine completion, separate from numeric execution."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_assembly import (
    AssembledEmbeddingIndex,
    PreparedEmbeddingIndexBasis,
    assemble_embedding_index_revision,
)
from eom_catalog_service.embedding_index_assembly_v2 import (
    AssembledMixedEmbeddingIndex,
    PreparedMixedEmbeddingIndexBasis,
    assemble_embedding_index_revision_v2,
)
from eom_catalog_service.embedding_registry_application import (
    register_embedding_index,
    validate_resolved_embedding_registration,
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryActor,
)
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    sha256_bytes,
)
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingIndexPublicationScope,
)
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetPublisher,
)
from eom_orchestrator.native_embedding_coordinator import (
    NativeEmbeddingCoordinator,
    native_embedding_index_registration_key,
)
from eom_orchestrator.native_embedding_index_handoff import (
    ensure_native_index_owner_workspace,
)
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingReadResult,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EmbeddingEncodingReadResultV2,
    SupportedLocalEmbeddingLaunchIntent,
)
from eom_workflow.local_embedding_index_refresh import (
    LocalEmbeddingIndexRefreshRequest,
    validate_index_refresh_request_basis,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
)
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    validate_local_embedding_selected_index_coverage,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    validate_local_embedding_selected_index_coverage_v2,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LocalEmbeddingStepOutputV2,
    SupportedLocalEmbeddingStepOutput,
    parse_supported_local_embedding_workflow_receipt,
    validate_supported_local_embedding_workflow_receipt,
)
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorAllocation,
    NativeCoordinatorCompleted,
    NativeCoordinatorIndexPrepared,
    NativeCoordinatorRegistered,
)
from eom_workflow.native_embedding_coordinator_v2 import (
    NativeCoordinatorCompletedV2,
    NativeCoordinatorIndexPreparedV2,
    NativeCoordinatorRegisteredV2,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_execution import DocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_completion_coverage import resolved_native_index_coverage
from eom_workflow_runner.local_embedding_encoding_admission import (
    CatalogEncodingOwnerAdmission,
    CurrentEncodingExecution,
)
from eom_workflow_runner.local_embedding_execution_context import (
    native_embedding_registry_scope,
    resolve_native_execution_sources,
)
from eom_workflow_runner.local_embedding_execution_port import (
    NativeFencedRunnerTransaction,
)
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.local_embedding_publications import (
    NativeEmbeddingPublications,
    native_publication_identity,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandLeaseIdentity


class NativeEmbeddingIndexCompletion:
    """One current owner composes immutable index and receipt, never computes a vector."""

    def __init__(
        self,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        publisher: ControlFileSetPublisher,
        execution_backend: DocumentEmbeddingExecution,
    ) -> None:
        self.owner, self.publisher, self.execution_backend = owner, publisher, execution_backend

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
        intent: SupportedLocalEmbeddingLaunchIntent,
        lease: CommandLeaseIdentity,
    ) -> EmbeddingEncodingReservations:
        return EmbeddingEncodingReservations(
            self.publisher.sessions,
            CatalogEncodingOwnerAdmission(
                self.owner, CurrentEncodingExecution(request, intent, lease), self.execution_backend
            ),
        )

    def publish(
        self,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedLocalEmbeddingRequest,
        lease: CommandLeaseIdentity,
        caller: EmbeddingRegistryActor,
        coordinator: NativeEmbeddingCoordinator,
        allocation: NativeCoordinatorAllocation,
        readings: tuple[EmbeddingEncodingReadResult | EmbeddingEncodingReadResultV2, ...],
        fenced_transaction: NativeFencedRunnerTransaction,
        publications: NativeEmbeddingPublications,
    ) -> SupportedLocalEmbeddingStepOutput:
        with fenced_transaction() as session:
            sources = self._current(
                session,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                request=request,
                lease=lease,
            )
            history = coordinator.read(session)
            workspace = ensure_native_index_owner_workspace(
                coordinator.intent.native_launch_job_id.removeprefix("job_")
            )
            if len(history.records) == 1:
                basis: PreparedEmbeddingIndexBasis | PreparedMixedEmbeddingIndexBasis
                if isinstance(request, LocalEmbeddingWorkflowRequestV2):
                    basis = self.owner.catalog.prepare_mixed_index_basis(
                        session, caller, native_embedding_registry_scope(request)
                    )
                else:
                    basis = self.owner.catalog.prepare_index_basis(
                        session, caller, native_embedding_registry_scope(request)
                    )
                if isinstance(request, LocalEmbeddingWorkflowRequestV2) != isinstance(
                    basis, PreparedMixedEmbeddingIndexBasis
                ):
                    raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                selected = tuple(
                    (r.owned_job, r.completion) for r in readings if r.completion is not None
                )
                new_shards = (
                    CatalogLocalEmbeddingEncodingArtifacts(
                        session, self.owner.settings
                    ).resolve_shared_row_shards(selected)
                    if selected
                    else ()
                )
                rows = {r.encoding.encoding_sha256: r for r in basis.reusable_rows}
                for reading in readings:
                    assert reading.completion is not None
                    row = RegisteredEmbeddingRow(
                        reading.owned_job.request.encoding, reading.completion.receipt.row_ref
                    )
                    previous_row = rows.get(row.encoding.encoding_sha256)
                    if previous_row is not None and previous_row != row:
                        raise ValueError("LOCAL_EMBEDDING_EXECUTOR_REUSE_CONFLICT")
                    rows[row.encoding.encoding_sha256] = row
                shards = dict(basis.shards)
                for pointer, manifest in new_shards:
                    if pointer in shards and shards[pointer] != manifest:
                        raise ValueError("LOCAL_EMBEDDING_EXECUTOR_SHARD_CONFLICT")
                    shards[pointer] = manifest
                # A local file survives SQL rollback. Keep the candidate stable
                # from the committed allocation, including a pre-checkpoint crash.
                created = allocation.created_at
                producer = allocation.index_producer.model_dump(mode="json")
                index_id = (
                    "embeddingindex_"
                    + content_sha256({"purpose": "NATIVE_INDEX_ENTITY", "producer": producer})[-32:]
                    if basis.previous is None
                    else basis.previous[1].index_id
                )
                revision_id = (
                    "embeddingindexrev_"
                    + content_sha256({"purpose": "NATIVE_INDEX_REVISION", "producer": producer})[
                        -32:
                    ]
                )
                assembled: AssembledEmbeddingIndex | AssembledMixedEmbeddingIndex
                if isinstance(basis, PreparedMixedEmbeddingIndexBasis):
                    if not isinstance(sources.admission.plan, LocalEmbeddingSourcePlanV2):
                        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                    assembled = assemble_embedding_index_revision_v2(
                        basis.full_plan,
                        available_rows=tuple(rows.values()),
                        shards=tuple(shards.items()),
                        index_id=index_id,
                        index_revision_id=revision_id,
                        previous=basis.previous,
                        created_at=created,
                    )
                    validate_local_embedding_selected_index_coverage_v2(
                        sources.admission.plan, assembled.index
                    )
                else:
                    if not isinstance(sources.admission.plan, LocalEmbeddingSourcePlan):
                        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                    assembled = assemble_embedding_index_revision(
                        basis.full_plan,
                        available_rows=tuple(rows.values()),
                        shards=tuple(shards.items()),
                        index_id=index_id,
                        index_revision_id=revision_id,
                        previous=basis.previous,
                        created_at=created,
                    )
                    validate_local_embedding_selected_index_coverage(
                        sources.admission.plan, assembled.index
                    )
                if isinstance(request, LocalEmbeddingIndexRefreshRequest):
                    if readings:
                        raise ValueError("LOCAL_EMBEDDING_REFRESH_ENCODING_FORBIDDEN")
                    if not isinstance(basis, PreparedEmbeddingIndexBasis) or not isinstance(
                        assembled, AssembledEmbeddingIndex
                    ):
                        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                    validate_index_refresh_request_basis(
                        request,
                        eligible_source_set_sha256=basis.full_plan.source_set_sha256,
                        eligible_source_count=len(basis.full_plan.sources),
                        available_bindings=assembled.index.bindings,
                        previous=basis.previous,
                    )
                publications.artifacts.stage_index_manifest(
                    index=assembled.index, workspace=workspace
                )
                body = {
                    "schema_version": (
                        "embedding-registry-registration-command/2.0"
                        if isinstance(request, LocalEmbeddingWorkflowRequestV2)
                        else "embedding-registry-registration-command/1.0"
                    ),
                    "operation": "REGISTER_EMBEDDING_INDEX",
                    "operation_key": native_embedding_index_registration_key(
                        coordinator.intent, index_id, revision_id
                    ),
                    "corpus_id": request.corpus_id,
                    "namespace": request.namespace.model_dump(mode="json"),
                    "index_id": index_id,
                    "index_revision_id": revision_id,
                    "index_manifest": ArtifactMemberPointer(
                        artifact_id=allocation.index_producer.artifact_id,
                        artifact_revision_id=allocation.index_producer.artifact_revision_id,
                        member_path="index.json",
                        schema_ref=(
                            MIXED_EMBEDDING_INDEX_SCHEMA_REF
                            if isinstance(request, LocalEmbeddingWorkflowRequestV2)
                            else INDEX_SCHEMA_REF
                        ),
                        media_type="application/json",
                        sha256=sha256_bytes(
                            canonical_json_bytes(assembled.index.model_dump(mode="json"))
                        ),
                    ).model_dump(mode="json"),
                    "index_sha256": assembled.index.index_sha256,
                    "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
                    "policy_revision_id": request.access_policy_revision_id,
                    "policy_sha256": request.access_policy_sha256,
                    "expected_current_index_revision_id": None
                    if basis.previous is None
                    else basis.previous[1].index_revision_id,
                    "expected_lock_version": basis.expected_lock_version,
                    "source_set_sha256": basis.full_plan.source_set_sha256,
                    "binding_set_sha256": content_sha256(
                        [b.binding_sha256 for b in assembled.index.bindings]
                    ),
                    "eligible_source_count": len(basis.full_plan.sources),
                    "binding_count": len(assembled.index.bindings),
                    "requested_at": created.isoformat().replace("+00:00", "Z"),
                }
                command = (
                    RegisterEmbeddingIndexCommandV2.model_validate(
                        body | {"request_sha256": content_sha256(body)}
                    )
                    if isinstance(request, LocalEmbeddingWorkflowRequestV2)
                    else RegisterEmbeddingIndexCommand.model_validate(
                        body | {"request_sha256": content_sha256(body)}
                    )
                )
                history = coordinator.append(
                    session,
                    coordinator.checkpoint(
                        "INDEX_PREPARED",
                        NativeCoordinatorIndexPreparedV2(
                            registration_command=command, index_created_at=created
                        )
                        if isinstance(command, RegisterEmbeddingIndexCommandV2)
                        else NativeCoordinatorIndexPrepared(
                            registration_command=command, index_created_at=created
                        ),
                    ),
                )
            prepared = history.records[1].payload
            assert isinstance(
                prepared, (NativeCoordinatorIndexPrepared, NativeCoordinatorIndexPreparedV2)
            )
            command = prepared.registration_command
        if len(history.records) == 2:
            with fenced_transaction() as session:
                self._current(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    request=request,
                    lease=lease,
                )
                resolved = self.owner.catalog.resolve_optional_index_publication(
                    session, caller, command
                )
                if resolved is None:
                    index = (
                        publications.artifacts.read_staged_mixed_index(
                            workspace=workspace, expected_sha256=command.index_manifest.sha256
                        )
                        if isinstance(command, RegisterEmbeddingIndexCommandV2)
                        else publications.artifacts.read_staged_index(
                            workspace=workspace, expected_sha256=command.index_manifest.sha256
                        )
                    )
                    resolved = self.owner.catalog.resolve_prepared_index(
                        session, caller, command, index
                    )
                validate_resolved_embedding_registration(command, resolved)
                saved = publications.artifacts.publish_index(
                    index=resolved.index,
                    shards=resolved.shards,
                    previous=resolved.previous,
                    scope=EmbeddingIndexPublicationScope(
                        request.graph_snapshot,
                        request.access_policy_revision_id,
                        request.access_policy_sha256,
                    ),
                    workspace=workspace,
                    identity=native_publication_identity(allocation.index_producer),
                )
                if saved.index_manifest != command.index_manifest:
                    raise ValueError("LOCAL_EMBEDDING_EXECUTOR_INDEX_PUBLICATION_MISMATCH")
                result = register_embedding_index(session, caller, command, self.owner.catalog)
                registered_payload: NativeCoordinatorRegistered | NativeCoordinatorRegisteredV2
                if isinstance(command, RegisterEmbeddingIndexCommandV2):
                    if not isinstance(result, EmbeddingIndexRegistrationResultV2):
                        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                    registered_payload = NativeCoordinatorRegisteredV2(
                        registration_result=result, registration_observed_at=datetime.now(UTC)
                    )
                else:
                    if not isinstance(result, EmbeddingIndexRegistrationResult):
                        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
                    registered_payload = NativeCoordinatorRegistered(
                        registration_result=result, registration_observed_at=datetime.now(UTC)
                    )
                history = coordinator.append(
                    session,
                    coordinator.checkpoint(
                        "REGISTERED",
                        registered_payload,
                    ),
                )
        registered = history.records[2].payload
        assert isinstance(registered, (NativeCoordinatorRegistered, NativeCoordinatorRegisteredV2))
        with fenced_transaction() as session:
            sources = self._current(
                session,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                request=request,
                lease=lease,
            )
            resolved = verify_embedding_index_registration_observation(
                session, caller, command, registered.registration_result, self.owner.catalog
            )
            association = read_native_embedding_launch_association(
                session, coordinator.intent, request
            )
            native_input = (
                None
                if association is None
                else CatalogLocalEmbeddingEncodingArtifacts(
                    session, self.owner.settings
                ).resolve_input(association)
            )
            body = {
                "schema_version": (
                    "local-embedding-workflow-receipt/2.0"
                    if isinstance(request, LocalEmbeddingWorkflowRequestV2)
                    else "local-embedding-workflow-receipt/1.0"
                ),
                "purpose": "LOCAL_EMBEDDING",
                "workflow_id": workflow.workflow_id,
                "workflow_definition_sha256": request.workflow_definition_sha256,
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": request.source_plan_sha256,
                "step_run_id": step.step_run_id,
                "step_key": "encode_batch",
                "attempt": 1,
                "receipt_owner_job_id": allocation.receipt_producer.job_id,
                "execution_result_schema": "incremental-embedding-result@1.0",
                "native_launch_job_id": None
                if association is None
                else coordinator.intent.native_launch_job_id,
                "launch_association_sha256": None
                if association is None
                else association.association_sha256,
                "registration_command": command.model_dump(mode="json"),
                "registration_result": registered.registration_result.model_dump(mode="json"),
                "registration_observed_at": registered.registration_observed_at.isoformat().replace(
                    "+00:00", "Z"
                ),
            }
            receipt = parse_supported_local_embedding_workflow_receipt(
                body | {"receipt_sha256": content_sha256(body)}
            )
            validate_supported_local_embedding_workflow_receipt(
                receipt,
                request,
                sources.admission.plan,
                sources.admission.policy,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                receipt_owner_job_id=allocation.receipt_producer.job_id,
                launch_association=association,
                owned_input=native_input,
                index_coverage=resolved_native_index_coverage(resolved),
            )
            output = publications.completions.publish(
                receipt, identity=native_publication_identity(allocation.receipt_producer)
            )
            self.validate_completion(
                session=session,
                workflow=workflow,
                step=step,
                request=request,
                command_lease=lease,
                output=output,
            )
            coordinator.append(
                session,
                coordinator.checkpoint(
                    "COMPLETED",
                    NativeCoordinatorCompletedV2(output=output)
                    if isinstance(output, LocalEmbeddingStepOutputV2)
                    else NativeCoordinatorCompleted(output=output),
                ),
            )
            return output

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
        sources = self._current(
            session,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            request=request,
            lease=command_lease,
        )
        receipt = resolve_native_embedding_completion(session, self.owner.settings, output)
        launch = read_native_embedding_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        if launch is None:
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_COORDINATOR_MISSING")
        history = NativeEmbeddingCoordinator(launch.intent, request).read(session)
        if len(history.records) < 3 or history.state in {"FAILED", "CANCELLED"}:
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_COMPLETION_NOT_REGISTERED")
        allocation, prepared, registered = (r.payload for r in history.records[:3])
        assert isinstance(allocation, NativeCoordinatorAllocation)
        assert isinstance(
            prepared, (NativeCoordinatorIndexPrepared, NativeCoordinatorIndexPreparedV2)
        )
        assert isinstance(registered, (NativeCoordinatorRegistered, NativeCoordinatorRegisteredV2))
        if (
            receipt.registration_command != prepared.registration_command
            or receipt.registration_result != registered.registration_result
            or receipt.registration_observed_at != registered.registration_observed_at
        ):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_COMPLETION_HISTORY_MISMATCH")
        if (
            output.receipt.artifact_id != allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.receipt_producer.artifact_revision_id
            or (
                step.platform_job_id is not None
                and step.platform_job_id != allocation.receipt_producer.job_id
            )
            or (
                len(history.records) == 4
                and history.records[3].payload
                != (
                    NativeCoordinatorCompletedV2(output=output)
                    if isinstance(output, LocalEmbeddingStepOutputV2)
                    else NativeCoordinatorCompleted(output=output)
                )
            )
        ):
            raise ValueError("LOCAL_EMBEDDING_EXECUTOR_COMPLETION_PRODUCER_MISMATCH")
        caller = self.owner.registry_caller(request)
        resolved = verify_embedding_index_registration_observation(
            session,
            caller,
            receipt.registration_command,
            receipt.registration_result,
            self.owner.catalog,
        )
        association = read_native_embedding_launch_association(session, launch.intent, request)
        if isinstance(request, LocalEmbeddingIndexRefreshRequest) and association is not None:
            raise ValueError("LOCAL_EMBEDDING_REFRESH_ENCODING_FORBIDDEN")
        native_input = None
        if association is not None:
            reservations = self._reservations(request, launch.intent, command_lease)
            rows = reservations.read_in_session(
                session,
                tuple(
                    sorted(
                        (j.job_reference for j in association.owned_jobs),
                        key=lambda ref: ref.job_id,
                    )
                ),
            )
            if any(r.status != "COMPLETED" for r in rows):
                raise ValueError("LOCAL_EMBEDDING_EXECUTOR_ENCODING_NOT_COMPLETED")
            events = {
                r.owned_job.job_reference.job_id: r.completion
                for r in rows
                if r.completion is not None
            }
            native_input = (
                CatalogLocalEmbeddingEncodingArtifacts(session, self.owner.settings)
                .resolve_result(
                    association,
                    tuple(events[j.job_reference.job_id] for j in association.owned_jobs),
                )
                .request
            )
        validate_supported_local_embedding_workflow_receipt(
            receipt,
            request,
            sources.admission.plan,
            sources.admission.policy,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            receipt_owner_job_id=allocation.receipt_producer.job_id,
            launch_association=association,
            owned_input=native_input,
            index_coverage=resolved_native_index_coverage(resolved),
        )
        self.owner.fence_mutation(session, request, command_lease)
        return output
