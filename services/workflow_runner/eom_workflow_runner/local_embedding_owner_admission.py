"""Concrete authenticated operator-seed composition; never an implicit production default."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.models import Sha256
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_operator_identity.contracts import PermissionKey
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import (
    EXECUTION_POLICY_ARTIFACT_TYPE,
    SOURCE_PLAN_ARTIFACT_TYPE,
)
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import read_native_embedding_launch
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    parse_local_embedding_execution_policy,
)
from eom_workflow.local_embedding_request import (
    LocalEmbeddingWorkflowRequestV11,
    parse_local_embedding_workflow_request_v11,
    require_local_embedding_operator_seed,
)
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from pydantic import TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_command_fence import (
    NativeCommandMutationFence,
    require_unexpired_native_command,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    validate_local_embedding_workflow_submission,
)
from eom_workflow_runner.state_machine import CommandState


@dataclass(frozen=True, slots=True)
class LocalEmbeddingOwnerConfiguration:
    """Installed owner-selected controls, not request-supplied release approval.

    The release composition must select this exact policy member deliberately;
    merely publishing a candidate policy does not activate it.
    """

    registry: EmbeddingRegistryOwnerConfiguration
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: str

    def __post_init__(self) -> None:
        pointer = ArtifactMemberPointer.model_validate(
            self.native_execution_policy.model_dump(mode="json")
        )
        if (
            pointer.member_path != "policy.json"
            or pointer.schema_ref != LOCAL_EMBEDDING_POLICY_SCHEMA_REF
            or pointer.media_type != "application/json"
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_INVALID")
        object.__setattr__(self, "native_execution_policy", pointer)
        TypeAdapter(Sha256).validate_python(self.native_execution_policy_sha256)


@dataclass(frozen=True, slots=True)
class ResolvedLocalEmbeddingSources:
    """Current root's values only; every later root must independently reauthorize."""

    admission: ResolvedLocalEmbeddingAdmission
    entries: tuple[StagedExperimentEntry, ...]


class CatalogLocalEmbeddingOwnerAdmission:
    """Use current Identity and official Catalog boundaries for a bounded operator seed.

    Production still requires an admitted owner connection/provider, selected
    released controls and native executor. Expired acquisitions need supported
    execution reconciliation; this adapter never assumes that expiry means no run.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: LocalEmbeddingOwnerConfiguration,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.configuration = configuration
        self.settings = settings or CatalogSettings.from_environment()
        self.identity = CapturedOperatorAuthorizationFence(
            capture, session_fence, PermissionKey.WORKFLOW_START
        )
        self.catalog = CatalogEmbeddingRegistryVerifier(
            engine,
            configuration.registry,
            identity_fence=self.identity,
            settings=self.settings,
        )
        self._command_fence = NativeCommandMutationFence()

    def resolve_submission(
        self, session: Session, request: LocalEmbeddingWorkflowRequestV11
    ) -> ResolvedLocalEmbeddingAdmission:
        return self.resolve_sources(session, request).admission

    def resolve_sources(
        self, session: Session, request: LocalEmbeddingWorkflowRequestV11
    ) -> ResolvedLocalEmbeddingSources:
        request = parse_local_embedding_workflow_request_v11(request.model_dump(mode="json"))
        operator = require_local_embedding_operator_seed(request).operator_id
        # No control/source bytes are read for a stale capture or a substituted actor.
        self.identity.fence_current_operator(session, operator)
        config = self.configuration
        if (
            request.native_execution_policy != config.native_execution_policy
            or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
            or request.corpus_id != config.registry.corpus_id
            or request.namespace != config.registry.namespace
            or request.space != config.registry.space
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_MISMATCH")
        query = EmbeddingRegistryLookup(
            request.corpus_id,
            request.namespace,
            request.graph_snapshot,
            request.access_policy_revision_id,
            request.access_policy_sha256,
        )
        caller = EmbeddingRegistryCaller(operator)
        # Current read policy must admit the scope before even metadata-only
        # plan bytes are dereferenced. This public phase performs no source IO.
        self.catalog.authorize_scope(session, caller, query)
        reader = PinnedArtifactReadContext(session, self.settings)
        reader.prefetch(
            tuple(
                (pointer.artifact_id, pointer.artifact_revision_id)
                for pointer in (request.native_execution_policy, request.source_plan)
            )
        )

        def read(pointer: ArtifactMemberPointer, artifact_type: str, limit: int) -> object:
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(artifact_type,),
                expected_primary_file=pointer.member_path,
                max_bytes=limit,
            ).payload
            value: object = json.loads(raw)
            if canonical_json_bytes(value) != raw:
                raise ValueError("LOCAL_EMBEDDING_CONTROL_BYTES_INVALID")
            return value

        policy = parse_local_embedding_execution_policy(
            read(request.native_execution_policy, EXECUTION_POLICY_ARTIFACT_TYPE, 64 * 1024)
        )
        plan = parse_local_embedding_source_plan(
            read(request.source_plan, SOURCE_PLAN_ARTIFACT_TYPE, 64 * 1024**2)
        )
        scope = ResolvedLocalEmbeddingAdmission(request, plan, policy)
        current = self.catalog.resolve_lookup(session, caller, query)
        rebuilt = build_local_embedding_source_plan(
            query,
            current,
            target_revision_ids=tuple(source.item_revision_id for source in plan.sources),
        )
        if rebuilt != plan:
            raise ValueError("LOCAL_EMBEDDING_SOURCE_PLAN_STALE")
        by_source = {
            entry.profile.source_basis.source.item_revision_id: entry for entry in current.entries
        }
        selected = tuple(by_source[d.source_revision_id] for d in plan.demands)
        # Reading/resolving may consume time. Never let an old successful check
        # stand in for the actual session's expiry/permission check at return.
        self.identity.fence_current_operator(session, operator)
        return ResolvedLocalEmbeddingSources(scope, selected)

    @staticmethod
    def _require_rows(
        session: Session,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingWorkflowRequestV11,
    ) -> None:
        operator = require_local_embedding_operator_seed(request).operator_id
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        if (
            object_session(command) is not session
            or object_session(workflow) is not session
            or command.workflow_id != workflow.workflow_id
            or definition is None
            or definition.definition_key != request.workflow_definition_key
            or definition.definition_version != request.workflow_definition_version
            or definition.definition_hash != request.workflow_definition_sha256
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "native current owner rows differ from their exact request",
            )
        # Repository owns the canonical request/actor/business-hash invariant;
        # do not maintain a second, weaker copy of its replay checks here.
        validate_local_embedding_workflow_submission(
            session,
            workflow,
            definition=definition,
            request=request,
            actor_type="human",
            actor_id=operator,
        )

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingWorkflowRequestV11,
    ) -> ResolvedLocalEmbeddingAdmission:
        self.identity.fence_current_operator(
            session, require_local_embedding_operator_seed(request).operator_id
        )
        self._require_rows(session, command, workflow, request)
        if command.state != CommandState.PENDING.value or command.attempts != 0:
            # Current source/session authority is still required; original intent
            # is ONLY provenance for rejoining the exact existing computation.
            if (
                command.state not in {CommandState.LEASED.value, CommandState.PROCESSING.value}
                or command.attempts < 1
                or command.lease_generation < 1
                or command.lease_expires_at is None
                or command.lease_expires_at > datetime.now(UTC)
            ):
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                    "native acquisition requires supported prior-execution reconciliation",
                )
            scope = self.resolve_submission(session, request)
            step = session.scalar(
                select(WorkflowStepRunRecord)
                .where(
                    WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                    WorkflowStepRunRecord.step_key == "encode_batch",
                    WorkflowStepRunRecord.attempt == 1,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                step is None
                or step.state not in {"RUNNING", "SUCCEEDED"}
                or step.step_type != "application"
                or step.worker_role is not None
                or step.result_schema != "incremental-embedding-result@1.0"
                or step.input_pointer_manifest
                != {
                    "source_plan": request.source_plan.model_dump(mode="json"),
                    "source_plan_sha256": request.source_plan_sha256,
                }
            ):
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                    "native recovery lacks its exact prior step; supported reconcile is required",
                )
            launch = read_native_embedding_launch(
                session,
                request=request,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            if launch is None:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                    "native recovery cannot substitute a vanished execution identity",
                )
            history = NativeEmbeddingCoordinator(launch.intent, request).read(session)
            if not history.records or history.state in {"FAILED", "CANCELLED"}:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                    "native recovery requires allocated, non-failed original execution history",
                )
            self.identity.fence_current_operator(
                session, require_local_embedding_operator_seed(request).operator_id
            )
            return scope
        return self.resolve_submission(session, request)

    def fence_mutation(
        self,
        session: Session,
        request: LocalEmbeddingWorkflowRequestV11,
        lease: CommandLeaseIdentity,
    ) -> None:
        self.resolve_mutation_sources(session, request, lease)

    def resolve_mutation_sources(
        self,
        session: Session,
        request: LocalEmbeddingWorkflowRequestV11,
        lease: CommandLeaseIdentity,
    ) -> ResolvedLocalEmbeddingSources:
        self.identity.fence_current_operator(
            session, require_local_embedding_operator_seed(request).operator_id
        )
        command = self._command_fence.acquire(session, request.request_sha256, lease)
        # Runner has already locked Workflow then command. Do not acquire these
        # in the reverse order; an unattached/different Workflow is not accepted.
        workflow = session.get(WorkflowInstanceRecord, command.workflow_id)
        if workflow is None:
            raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "native workflow disappeared")
        self._require_rows(session, command, workflow, request)
        sources = self.resolve_sources(session, request)
        require_unexpired_native_command(command, lease)
        return sources
