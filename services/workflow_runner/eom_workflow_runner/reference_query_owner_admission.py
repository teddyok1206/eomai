"""Current operator/source/control preparation; no QUERY launch or implicit admission."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQueryTextInput,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.models import Sha256
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import PreparedSimilarityContext
from eom_catalog_service.similarity_context_service import validate_similarity_preparation
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.embedding_runtime_bundle_artifacts import RUNTIME_BUNDLE_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import REFERENCE_QUERY_POLICY_ARTIFACT_TYPE
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.reference_query_execution import (
    REFERENCE_QUERY_POLICY_REF,
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_step_output,
    parse_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
)
from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
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
from eom_workflow_runner.native_step_completion import (
    native_application_step,
    validate_completed_native_workflow,
)
from eom_workflow_runner.reference_query_admission import ResolvedReferenceQueryAdmission
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    require_command_lease,
    validate_reference_query_workflow_submission,
)
from eom_workflow_runner.state_machine import CommandState


@dataclass(frozen=True, slots=True)
class ReferenceQueryOwnerConfiguration:
    """Trusted installed selection, not request-controlled policy release or permission."""

    registry: EmbeddingRegistryOwnerConfiguration
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: str
    runtime_bundle: EmbeddingRuntimeBundlePointer

    def __post_init__(self) -> None:
        pointer = ArtifactMemberPointer.model_validate(
            raw_similarity_contract_value(self.native_execution_policy)
        )
        if (
            pointer.member_path != "policy.json"
            or pointer.schema_ref != REFERENCE_QUERY_POLICY_REF
            or pointer.media_type != "application/json"
        ):
            raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID")
        object.__setattr__(self, "native_execution_policy", pointer)
        TypeAdapter(Sha256).validate_python(self.native_execution_policy_sha256)
        object.__setattr__(
            self,
            "runtime_bundle",
            EmbeddingRuntimeBundlePointer.model_validate(
                raw_similarity_contract_value(self.runtime_bundle)
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedReferenceQuerySources:
    """Exact current-root values only; never a cached authority or claim grant."""

    request: ReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    prepared: PreparedSimilarityContext

    def __post_init__(self) -> None:
        request = parse_reference_query_workflow_request(self.request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        validate_reference_query_request_references(request, policy, bundle)
        validate_similarity_preparation(request.context_request, self.prepared)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "bundle", bundle)


@dataclass(frozen=True, slots=True)
class ResolvedCompletedReferenceQuerySources:
    """Root-local attached records and exact values, never a durable read permission."""

    sources: ResolvedReferenceQuerySources
    workflow: WorkflowInstanceRecord
    step: WorkflowStepRunRecord
    output: ReferenceQueryStepOutput


def build_reference_query_native_input(
    sources: ResolvedReferenceQuerySources, *, job_id: str, query_request_id: str
) -> EmbeddingReferenceQueryInputV11:
    """Derive bounded exact anchor rows, not permission or another source lookup."""
    sources.__post_init__()
    context, policy = sources.request.context_request, sources.policy
    texts = dict(sources.prepared.query_texts)
    rows: list[ReferenceQueryTextInput] = []
    for selection in context.views:
        if selection.index is None or selection.view not in texts:
            continue
        text = texts[selection.view]
        encoding_body = {
            "storage_partition": selection.index.storage_partition,
            "space_sha256": policy.spaces.query.space_sha256,
            "input_text_sha256": content_sha256(text),
        }
        encoding = EmbeddingEncodingIdentity.model_validate(
            encoding_body | {"encoding_sha256": content_sha256(encoding_body)}
        )
        rows.append(ReferenceQueryTextInput(view=selection.view, encoding=encoding, text=text))
    if not rows:
        raise ValueError("REFERENCE_QUERY_VIEW_INPUT_UNAVAILABLE")
    ordered = tuple(sorted(rows, key=lambda row: row.encoding.encoding_sha256))
    body = {
        "schema_version": "embedding-reference-query-input/1.1",
        "job_id": job_id,
        "query_request_id": query_request_id,
        "context_request_sha256": context.request_sha256,
        "spaces": policy.spaces.model_dump(mode="json"),
        "recipe": context.views[0].recipe.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in ordered],
        "batch_size": policy.resource_profile.batch_size,
        "threads": policy.resource_profile.threads,
        "input_set_sha256": embedding_input_set_sha256(tuple(row.encoding for row in ordered)),
    }
    return parse_embedding_reference_query_input_v11(
        body | {"request_sha256": content_sha256(body)}
    )


def validate_current_reference_query_input(
    sources: ResolvedReferenceQuerySources,
    launch: ReferenceQueryLaunchAssociation,
    native_input: EmbeddingReferenceQueryInputV11,
) -> None:
    """Exact current derivation under original IDs; not authority or a launch grant."""
    current = build_reference_query_native_input(
        sources, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
    )
    validate_reference_query_launch_association(
        launch, sources.request, sources.policy, sources.bundle, current
    )
    if current != native_input:
        raise ValueError("REFERENCE_QUERY_EXECUTOR_CURRENT_INPUT_CHANGED")


class CatalogReferenceQueryOwnerAdmission:
    """Actual Identity and official Catalog scope, before any QUERY side effect.

    Claim/mutation independently resolve the actual source/session in their own
    root. Installed physical QUERY-purpose admission remains the executor's duty.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: ReferenceQueryOwnerConfiguration,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        configuration.__post_init__()
        self.configuration = configuration
        self.settings = settings or CatalogSettings.from_environment()
        self.identity = CapturedOperatorAuthorizationFence(
            capture, session_fence, PermissionKey.WORKFLOW_START
        )
        self.catalog = CatalogEmbeddingRegistryVerifier(
            engine, configuration.registry, identity_fence=self.identity, settings=self.settings
        )
        self._command_fence = NativeCommandMutationFence()

    def resolve_submission(
        self, session: Session, request: ReferenceQueryWorkflowRequest
    ) -> ResolvedReferenceQueryAdmission:
        sources = self.resolve_sources(session, request)
        return ResolvedReferenceQueryAdmission(sources.request, sources.policy, sources.bundle)

    @staticmethod
    def _require_rows(
        session: Session,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: ReferenceQueryWorkflowRequest,
    ) -> None:
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        if (
            object_session(command) is not session
            or object_session(workflow) is not session
            or command.workflow_id != workflow.workflow_id
            or definition is None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "QUERY current owner requires attached exact Workflow/command rows",
            )
        validate_reference_query_workflow_submission(
            session,
            workflow,
            definition=definition,
            request=request,
            actor_type="human",
            actor_id=request.operator_audit.operator_id,
        )

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: ReferenceQueryWorkflowRequest,
    ) -> ResolvedReferenceQueryAdmission:
        request = parse_reference_query_workflow_request(request)
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        self._require_rows(session, command, workflow, request)
        fresh = (
            command.state == CommandState.PENDING.value
            and command.attempts == 0
            and command.lease_generation == 0
            and command.lease_owner is None
            and command.lease_token is None
            and command.lease_expires_at is None
        )
        expired = (
            command.state in {CommandState.LEASED.value, CommandState.PROCESSING.value}
            and command.attempts >= 1
            and command.lease_generation >= 1
            and command.lease_expires_at is not None
            and command.lease_expires_at <= datetime.now(UTC)
        )
        if not fresh and not expired:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY acquisition requires supported original-execution reconciliation",
            )
        scope = self.resolve_submission(session, request)
        step = native_application_step(session, workflow.workflow_id, "encode_reference_query")
        if fresh and step is None:
            return scope
        if step is None or (
            step.workflow_id != workflow.workflow_id
            or step.step_key != "encode_reference_query"
            or step.attempt != 1
            or step.state not in {"RUNNING", "SUCCEEDED"}
            or step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != "embedding-reference-query-result@1.0"
            or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
        ):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY original-execution reconciliation lacks its exact prior attempt",
            )
        launch = read_native_reference_query_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        if launch is None:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY recovery cannot replace a vanished original execution",
            )
        history = NativeReferenceQueryCoordinator(request, launch).read(session)
        if not history.records or history.state in {"FAILED", "CANCELLED"}:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "QUERY recovery requires allocated nonfailed original history",
            )
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        return scope

    def fence_mutation(
        self, session: Session, request: ReferenceQueryWorkflowRequest, lease: CommandLeaseIdentity
    ) -> None:
        self.resolve_mutation_sources(session, request, lease)

    def resolve_mutation_sources(
        self, session: Session, request: ReferenceQueryWorkflowRequest, lease: CommandLeaseIdentity
    ) -> ResolvedReferenceQuerySources:
        request = parse_reference_query_workflow_request(request)
        self.identity.fence_current_operator(session, request.operator_audit.operator_id)
        command = self._command_fence.acquire(session, request.request_sha256, lease)
        workflow = session.get(WorkflowInstanceRecord, command.workflow_id)
        if workflow is None:
            raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "QUERY Workflow disappeared")
        self._require_rows(session, command, workflow, request)
        sources = self.resolve_sources(session, request)
        require_unexpired_native_command(command, lease)
        return sources

    def resolve_execution_sources(
        self,
        session: Session,
        request: ReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        *,
        workflow_id: str,
        step_run_id: str,
    ) -> ResolvedReferenceQuerySources:
        """Current attached Workflow/command/step closure for computation and completion."""
        sources = self.resolve_mutation_sources(session, request, lease)
        command = require_command_lease(session, lease)
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        step = session.get(WorkflowStepRunRecord, step_run_id)
        if (
            workflow is None
            or step is None
            or workflow.state not in {"RUNNING", "COMPLETED"}
            or command.workflow_id != workflow_id
            or step.workflow_id != workflow_id
            or step.step_key != "encode_reference_query"
            or step.attempt != 1
            or step.state not in {"RUNNING", "SUCCEEDED"}
            or step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != "embedding-reference-query-result@1.0"
            or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
        ):
            raise ValueError("REFERENCE_QUERY_EXECUTOR_CURRENT_STEP_INVALID")
        return sources

    def resolve_sources(
        self, session: Session, request: ReferenceQueryWorkflowRequest
    ) -> ResolvedReferenceQuerySources:
        request = parse_reference_query_workflow_request(request)
        caller = EmbeddingRegistryCaller(request.operator_audit.operator_id)
        self.identity.fence_current_operator(session, caller.operator_id)
        config, context = self.configuration, request.context_request
        if (
            request.native_execution_policy != config.native_execution_policy
            or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
            or request.runtime_bundle != config.runtime_bundle
        ):
            raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_MISMATCH")
        self.catalog.authorize_scope(
            session,
            caller,
            EmbeddingRegistryLookup(
                config.registry.corpus_id,
                config.registry.namespace,
                context.graph_snapshot,
                context.policy_revision_id,
                context.policy_sha256,
                context.maximum_sources,
            ),
        )
        reader = PinnedArtifactReadContext(session, self.settings)
        pointers = (config.native_execution_policy, config.runtime_bundle.manifest_member)
        reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in pointers))
        pointer = config.native_execution_policy
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            ("policy.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )

        def read(pointer: ArtifactMemberPointer, artifact_type: str, maximum: int) -> object:
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(artifact_type,),
                expected_primary_file=pointer.member_path,
                max_bytes=maximum,
            ).payload
            value: object = json.loads(raw)
            if canonical_json_bytes(value) != raw:
                raise ValueError("REFERENCE_QUERY_CONTROL_NONCANONICAL")
            return value

        policy = parse_reference_query_execution_policy(
            read(config.native_execution_policy, REFERENCE_QUERY_POLICY_ARTIFACT_TYPE, 64 * 1024)
        )
        raw_bundle = read(
            config.runtime_bundle.manifest_member,
            RUNTIME_BUNDLE_ARTIFACT_TYPE,
            MAX_RUNTIME_BUNDLE_BYTES,
        )
        if not isinstance(raw_bundle, dict):
            raise ValueError("REFERENCE_QUERY_BUNDLE_INVALID")
        bundle = parse_embedding_runtime_bundle(raw_bundle)
        validate_reference_query_request_references(request, policy, bundle)
        prepared, _reads = self.catalog.prepare_and_read_similarity_context_in_session(
            session, caller, context
        )
        result = ResolvedReferenceQuerySources(request, policy, bundle, prepared)
        self.identity.fence_current_operator(session, caller.operator_id)
        return result

    def resolve_completed_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: ReferenceQueryWorkflowRequest,
        *,
        workflow_id: str,
    ) -> ResolvedCompletedReferenceQuerySources:
        """Current read authority, never a new claim or a completed-command lease."""
        request = parse_reference_query_workflow_request(request)
        if (
            not isinstance(caller, EmbeddingRegistryCaller)
            or caller.operator_id != request.operator_audit.operator_id
        ):
            raise ValueError("REFERENCE_QUERY_READ_CALLER_INVALID")
        self.identity.fence_current_operator(session, caller.operator_id)
        workflow = session.get(WorkflowInstanceRecord, workflow_id, populate_existing=True)
        if workflow is None or object_session(workflow) is not session:
            raise ValueError("REFERENCE_QUERY_READ_WORKFLOW_MISSING")
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        if definition is None:
            raise ValueError("REFERENCE_QUERY_READ_DEFINITION_MISSING")
        validate_reference_query_workflow_submission(
            session,
            workflow,
            definition=definition,
            request=request,
            actor_type="human",
            actor_id=caller.operator_id,
        )
        step = native_application_step(session, workflow_id, "encode_reference_query")
        if step is None or (
            step.step_type != "application"
            or step.worker_role is not None
            or step.result_schema != "embedding-reference-query-result@1.0"
            or step.attempt != 1
            or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
            or step.output_pointer_manifest is None
            or step.error_code is not None
            or step.superseded_by_step_run_id is not None
        ):
            raise ValueError("REFERENCE_QUERY_READ_STEP_INVALID")
        output = parse_reference_query_step_output(step.output_pointer_manifest)
        validate_completed_native_workflow(session, workflow, step, output)
        sources = self.resolve_sources(session, request)
        return ResolvedCompletedReferenceQuerySources(sources, workflow, step, output)
