"""One native owner application with explicit operator or service authentication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_contracts.models import Sha256
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryActor,
    EmbeddingRegistryLookup,
    EmbeddingRegistryServiceCaller,
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
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingRuntimeProfile,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_executable_policy,
    parse_local_embedding_service_execution_policy,
)
from eom_workflow.local_embedding_request import (
    LocalEmbeddingExecutableRequest,
    local_embedding_request_actor,
    parse_local_embedding_executable_request,
)
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from pydantic import TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_actor_authority import (
    LocalEmbeddingActorAuthority,
    OperatorLocalEmbeddingActorAuthority,
    ServiceLocalEmbeddingActorAuthority,
)
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
            or pointer.schema_ref
            not in {LOCAL_EMBEDDING_POLICY_SCHEMA_REF, LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF}
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


@dataclass(frozen=True, slots=True)
class ServiceReconciliationControls:
    """Current-root data for request construction, not future source authority."""

    caller: EmbeddingRegistryServiceCaller
    grant: LocalIndexingAccessPolicy
    policy: LocalEmbeddingServiceExecutionPolicy


class CatalogLocalEmbeddingOwnerAdmission:
    """Use current Identity/Catalog authority for the existing bounded native workflow.

    Production still requires an admitted owner connection/provider, selected
    released controls and native executor. Expired acquisitions need supported
    execution reconciliation; this adapter never assumes that expiry means no run.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: LocalEmbeddingOwnerConfiguration,
        *,
        actor_authority: LocalEmbeddingActorAuthority,
        settings: CatalogSettings | None = None,
    ) -> None:
        configuration.__post_init__()
        if (
            type(actor_authority)
            not in {OperatorLocalEmbeddingActorAuthority, ServiceLocalEmbeddingActorAuthority}
            or configuration.native_execution_policy.schema_ref != actor_authority.policy_schema_ref
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_INVALID")
        self.configuration = configuration
        self.settings = settings or CatalogSettings.from_environment()
        self._actor_authority = actor_authority
        self.catalog = actor_authority.catalog(engine, configuration.registry, self.settings)
        self._command_fence = NativeCommandMutationFence()

    @classmethod
    def for_operator(
        cls,
        engine: Engine,
        configuration: LocalEmbeddingOwnerConfiguration,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> CatalogLocalEmbeddingOwnerAdmission:
        return cls(
            engine,
            configuration,
            actor_authority=OperatorLocalEmbeddingActorAuthority(
                CapturedOperatorAuthorizationFence(
                    capture, session_fence, PermissionKey.WORKFLOW_START
                )
            ),
            settings=settings,
        )

    @classmethod
    def for_indexing_service(
        cls,
        engine: Engine,
        configuration: LocalEmbeddingOwnerConfiguration,
        *,
        source_authority: CatalogIndexingRegistrySourceAuthority,
        settings: CatalogSettings | None = None,
    ) -> CatalogLocalEmbeddingOwnerAdmission:
        if (
            type(source_authority) is not CatalogIndexingRegistrySourceAuthority
            or source_authority.native_execution_policy_sha256
            != configuration.native_execution_policy_sha256
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_MISMATCH")
        return cls(
            engine,
            configuration,
            actor_authority=ServiceLocalEmbeddingActorAuthority(
                source_authority, configuration.registry
            ),
            settings=settings,
        )

    @property
    def identity(self) -> CapturedOperatorAuthorizationFence:
        """Existing human owner observation only; no machine-to-user impersonation."""
        if not isinstance(self._actor_authority, OperatorLocalEmbeddingActorAuthority):
            raise ValueError("LOCAL_EMBEDDING_OPERATOR_UNAVAILABLE")
        return self._actor_authority.identity

    def registry_caller(self, request: LocalEmbeddingExecutableRequest) -> EmbeddingRegistryActor:
        return self._actor_authority.registry_caller(request)

    def fence_current_actor(
        self, session: Session, request: LocalEmbeddingExecutableRequest
    ) -> None:
        self._actor_authority.fence(session, request)

    def _service_authority(self) -> ServiceLocalEmbeddingActorAuthority:
        if type(self._actor_authority) is not ServiceLocalEmbeddingActorAuthority:
            raise ValueError("LOCAL_EMBEDDING_SERVICE_UNAVAILABLE")
        return self._actor_authority

    def current_reconciliation_lookup(self, session: Session) -> EmbeddingRegistryLookup | None:
        return self._service_authority().source_authority.current_lookup(
            session, self.configuration.registry
        )

    @staticmethod
    def _read_control(
        reader: PinnedArtifactReadContext,
        pointer: ArtifactMemberPointer,
        artifact_type: str,
        limit: int,
    ) -> object:
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
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

    def resolve_reconciliation_controls(
        self,
        session: Session,
        query: EmbeddingRegistryLookup,
        profile: LocalEmbeddingRuntimeProfile,
    ) -> ServiceReconciliationControls:
        authority = self._service_authority().source_authority
        caller = EmbeddingRegistryServiceCaller(authority.authority.service_fence.pin.service)
        config = self.configuration
        grant = authority.authorize_scope(session, caller, query, config.registry)
        self.catalog.authorize_scope(session, caller, query)
        policy = parse_local_embedding_service_execution_policy(
            self._read_control(
                PinnedArtifactReadContext(session, self.settings),
                config.native_execution_policy,
                EXECUTION_POLICY_ARTIFACT_TYPE,
                64 * 1024,
            )
        )
        profile = LocalEmbeddingRuntimeProfile.model_validate(profile.model_dump(mode="json"))
        if (
            policy.policy_sha256 != config.native_execution_policy_sha256
            or policy.service != caller.service
            or profile not in policy.profiles
            or profile.space != config.registry.space
            or profile.resource_profile.resource_profile_sha256 != authority.resource_profile_sha256
        ):
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_MISMATCH")
        return ServiceReconciliationControls(caller, grant, policy)

    def resolve_submission(
        self, session: Session, request: LocalEmbeddingExecutableRequest
    ) -> ResolvedLocalEmbeddingAdmission:
        return self.resolve_sources(session, request).admission

    def resolve_sources(
        self, session: Session, request: LocalEmbeddingExecutableRequest
    ) -> ResolvedLocalEmbeddingSources:
        request = parse_local_embedding_executable_request(request)
        # No control/source bytes are read for a stale capture or a substituted actor.
        self.fence_current_actor(session, request)
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
        caller = self.registry_caller(request)
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

        policy = parse_local_embedding_executable_policy(
            self._read_control(
                reader, request.native_execution_policy, EXECUTION_POLICY_ARTIFACT_TYPE, 64 * 1024
            )
        )
        plan = parse_local_embedding_source_plan(
            self._read_control(reader, request.source_plan, SOURCE_PLAN_ARTIFACT_TYPE, 64 * 1024**2)
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
        self.fence_current_actor(session, request)
        return ResolvedLocalEmbeddingSources(scope, selected)

    @staticmethod
    def _require_rows(
        session: Session,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingExecutableRequest,
    ) -> None:
        actor_type, actor_id = local_embedding_request_actor(request)
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
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingExecutableRequest,
    ) -> ResolvedLocalEmbeddingAdmission:
        self.fence_current_actor(session, request)
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
            self.fence_current_actor(session, request)
            return scope
        return self.resolve_submission(session, request)

    def fence_mutation(
        self,
        session: Session,
        request: LocalEmbeddingExecutableRequest,
        lease: CommandLeaseIdentity,
    ) -> None:
        self.resolve_mutation_sources(session, request, lease)

    def resolve_mutation_sources(
        self,
        session: Session,
        request: LocalEmbeddingExecutableRequest,
        lease: CommandLeaseIdentity,
    ) -> ResolvedLocalEmbeddingSources:
        self.fence_current_actor(session, request)
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
