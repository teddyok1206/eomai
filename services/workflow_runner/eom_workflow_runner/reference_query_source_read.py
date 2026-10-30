"""Current read authority and exact QUERY source/input closure, never native execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Protocol

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
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.public_solution_similarity_service import PreparedPublicSolutionQuerySource
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import PreparedSimilarityContext
from eom_catalog_service.similarity_context_service import validate_similarity_preparation
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_orchestrator.embedding_runtime_bundle_artifacts import RUNTIME_BUNDLE_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import REFERENCE_QUERY_POLICY_ARTIFACT_TYPE
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.reference_query_execution import (
    REFERENCE_QUERY_POLICY_REF,
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequestV3,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_step_output,
    parse_reference_query_workflow_request_v3,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_policy_bundle,
    validate_reference_query_request_references,
)
from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_step_completion import (
    native_application_step,
    validate_completed_native_workflow,
)
from eom_workflow_runner.repository import (
    validate_reference_query_workflow_submission,
)


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

    request: SupportedReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    prepared: PreparedSimilarityContext

    def __post_init__(self) -> None:
        request = parse_supported_reference_query_workflow_request(self.request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        validate_reference_query_request_references(request, policy, bundle)
        validate_similarity_preparation(request.context_request, self.prepared)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "bundle", bundle)


@dataclass(frozen=True, slots=True)
class ResolvedPublicSolutionReferenceQuerySources:
    """Current-root public source projection, not a source/lease/execution capability."""

    request: ReferenceQueryWorkflowRequestV3
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    prepared: PreparedPublicSolutionQuerySource

    def __post_init__(self) -> None:
        request = parse_reference_query_workflow_request_v3(self.request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        validate_reference_query_request_references(request, policy, bundle)
        if type(self.prepared) is not PreparedPublicSolutionQuerySource:
            raise ValueError("REFERENCE_QUERY_PUBLIC_SOURCE_INVALID")
        row = ReferenceQueryTextInput.model_validate(
            raw_similarity_contract_value(self.prepared.row)
        )
        anchor = PublicSolutionSourceReference.model_validate(
            raw_similarity_contract_value(self.prepared.anchor)
        )
        view = request.context_request.views[0]
        if (
            self.prepared.request_sha256 != request.context_request.request_sha256
            or anchor != request.context_request.anchor
            or row.view != "CONCRETE_FACETS"
            or row.encoding.space_sha256 != policy.spaces.query.space_sha256
            or row.encoding.storage_partition != view.index.storage_partition
            or len(row.text.encode("utf-8")) > view.recipe.maximum_text_bytes
        ):
            raise ValueError("REFERENCE_QUERY_PUBLIC_SOURCE_INVALID")
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(
            self,
            "prepared",
            PreparedPublicSolutionQuerySource(
                self.prepared.request_sha256, request.context_request.anchor, row
            ),
        )


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
    if type(sources) is not ResolvedReferenceQuerySources:
        raise ValueError("REFERENCE_QUERY_SOURCE_FAMILY_INVALID")
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


def build_public_solution_query_native_input(
    sources: ResolvedPublicSolutionReferenceQuerySources,
    *,
    job_id: str,
    query_request_id: str,
) -> PublicSolutionQueryInput:
    """Materialize one exact QUERY2 anchor; never reinterpret a DOCUMENT encoding."""
    if type(sources) is not ResolvedPublicSolutionReferenceQuerySources:
        raise ValueError("REFERENCE_QUERY_PUBLIC_SOURCE_INVALID")
    sources.__post_init__()
    row = sources.prepared.row
    body = {
        "schema_version": "embedding-reference-query-input/2.0",
        "job_id": job_id,
        "query_request_id": query_request_id,
        "context_request_sha256": sources.request.context_request.request_sha256,
        "spaces": sources.policy.spaces.model_dump(mode="json"),
        "recipe": sources.request.context_request.views[0].recipe.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json")],
        "batch_size": sources.policy.resource_profile.batch_size,
        "threads": sources.policy.resource_profile.threads,
        "input_set_sha256": embedding_input_set_sha256((row.encoding,)),
    }
    return PublicSolutionQueryInput.model_validate(body | {"request_sha256": content_sha256(body)})


def resolve_public_solution_reference_query_sources(
    owner: ReferenceQuerySourceOwner,
    session: Session,
    request: ReferenceQueryWorkflowRequestV3,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> ResolvedPublicSolutionReferenceQuerySources:
    """Same actual Identity/Catalog/control owners, distinct exact public-report request.

    The running owner still requires its separate Workflow/claim/native admission.
    This function neither changes installed configuration nor discovers latest.
    """
    request = parse_reference_query_workflow_request_v3(request)
    caller = EmbeddingRegistryCaller(request.operator_audit.operator_id)
    owner.identity.fence_current_operator(session, caller.operator_id)
    config, context = owner.configuration, request.context_request
    if (
        not isinstance(config.registry.namespace, PublicSolutionIndexNamespace)
        or request.native_execution_policy != config.native_execution_policy
        or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
        or request.runtime_bundle != config.runtime_bundle
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_MISMATCH")
    owner.catalog.authorize_scope(
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
    reader = (
        PinnedArtifactReadContext.for_session(session, owner.settings)
        if artifact_reader is None
        else artifact_reader
    )
    reader.require_session(session)
    if reader.settings != owner.settings:
        raise ValueError("REFERENCE_QUERY_READ_ARTIFACT_CONTEXT_INVALID")
    policy, bundle = read_pinned_reference_query_controls(reader, config)
    validate_reference_query_request_references(request, policy, bundle)
    prepared = CatalogPublicSolutionSimilarityRead(owner.catalog).prepare_query_in_session(
        session, caller, context
    )
    reader.revalidate_provenance()
    result = ResolvedPublicSolutionReferenceQuerySources(request, policy, bundle, prepared)
    owner.identity.fence_current_operator(session, caller.operator_id)
    return result


class ReferenceQuerySourceOwner(Protocol):
    """Current read composition only; never a native submission/claim/mutation port."""

    @property
    def configuration(self) -> ReferenceQueryOwnerConfiguration: ...

    @property
    def settings(self) -> CatalogSettings: ...

    @property
    def identity(self) -> OperatorAuthorizationFence: ...

    @property
    def catalog(self) -> CatalogEmbeddingRegistryVerifier: ...

    def resolve_sources(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedReferenceQuerySources: ...

    def resolve_completed_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        workflow_id: str,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedCompletedReferenceQuerySources: ...


class CatalogReferenceQueryReadOwner:
    """Trusted authenticated Catalog/accepted-role read, with no native execution methods.

    The ingress owns actual authentication; the mandatory Identity adapter and
    official Catalog source resolver own every current root. An ID/DTO cannot
    construct those actual runtime capabilities, and no expired owner is replaced.
    """

    cuda_owner: CatalogReferenceQueryReadOwner | None

    def __init__(
        self,
        engine: Engine,
        configuration: ReferenceQueryOwnerConfiguration,
        *,
        identity_fence: OperatorAuthorizationFence | None,
        settings: CatalogSettings | None = None,
        cuda_owner: CatalogReferenceQueryReadOwner | None = None,
    ) -> None:
        configuration.__post_init__()
        if identity_fence is None or not callable(
            getattr(identity_fence, "fence_current_operator", None)
        ):
            raise ValueError("REFERENCE_QUERY_READ_AUTHORITY_UNAVAILABLE")
        self.configuration = configuration
        self.settings = settings or CatalogSettings.from_environment()
        self.identity = identity_fence
        self.catalog = CatalogEmbeddingRegistryVerifier(
            engine, configuration.registry, identity_fence=self.identity, settings=self.settings
        )
        if cuda_owner is not None and (
            type(cuda_owner) is not CatalogReferenceQueryReadOwner
            or cuda_owner.cuda_owner is not None
            or cuda_owner.catalog.engine is not engine
            or cuda_owner.identity is not self.identity
            or cuda_owner.settings != self.settings
            or configuration.registry.space.runtime.device != "CPU"
            or cuda_owner.configuration.registry.space.runtime.device != "CUDA"
            or replace(
                cuda_owner.configuration.registry,
                namespace=configuration.registry.namespace,
                space=configuration.registry.space,
            )
            != configuration.registry
            or type(cuda_owner.configuration.registry.namespace)
            is not type(configuration.registry.namespace)
            or cuda_owner.configuration.registry.namespace.model_dump(
                mode="json", exclude={"space_sha256"}
            )
            != configuration.registry.namespace.model_dump(mode="json", exclude={"space_sha256"})
        ):
            raise ValueError("REFERENCE_QUERY_READ_DEVICE_CONFIGURATION_INVALID")
        self.cuda_owner = cuda_owner

    def resolve_sources(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedReferenceQuerySources:
        return resolve_reference_query_sources(
            self, session, request, artifact_reader=artifact_reader
        )

    def resolve_completed_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedReferenceQueryWorkflowRequest,
        *,
        workflow_id: str,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedCompletedReferenceQuerySources:
        return resolve_completed_reference_query_sources(
            self, session, caller, request, workflow_id=workflow_id, artifact_reader=artifact_reader
        )


def select_completed_reference_query_read_owner(
    owner: ReferenceQuerySourceOwner, request: SupportedReferenceQueryWorkflowRequest
) -> ReferenceQuerySourceOwner:
    """Pure installed-device choice; caller must bind stored history and actual authority."""
    if type(owner) is CatalogReferenceQueryReadOwner:
        checked = parse_supported_reference_query_workflow_request(request)
        if checked.resource_profile.device == owner.configuration.registry.space.runtime.device:
            return owner
        if owner.cuda_owner is not None and checked.resource_profile.device == "CUDA":
            return owner.cuda_owner
        raise ValueError("REFERENCE_QUERY_READ_DEVICE_UNAVAILABLE")
    # Existing actual execution/capture owners already carry their selected device.
    return owner


def read_pinned_reference_query_controls(
    reader: PinnedArtifactReadContext,
    config: ReferenceQueryOwnerConfiguration,
) -> tuple[ReferenceQueryExecutionPolicy, EmbeddingRuntimeBundle]:
    """Configured control bytes only; caller owns current authority and request closure."""
    config.__post_init__()
    return read_selected_reference_query_controls(
        reader,
        policy_member=config.native_execution_policy,
        policy_sha256=config.native_execution_policy_sha256,
        runtime_bundle=config.runtime_bundle,
    )


def read_selected_reference_query_controls(
    reader: PinnedArtifactReadContext,
    *,
    policy_member: ArtifactMemberPointer,
    policy_sha256: str,
    runtime_bundle: EmbeddingRuntimeBundlePointer,
) -> tuple[ReferenceQueryExecutionPolicy, EmbeddingRuntimeBundle]:
    """Canonical system controls without inventing a source/user context for startup."""
    policy_member = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(policy_member)
    )
    runtime_bundle = EmbeddingRuntimeBundlePointer.model_validate(
        raw_similarity_contract_value(runtime_bundle)
    )
    TypeAdapter(Sha256).validate_python(policy_sha256)
    if (
        policy_member.member_path != "policy.json"
        or policy_member.schema_ref != REFERENCE_QUERY_POLICY_REF
        or policy_member.media_type != "application/json"
    ):
        raise ValueError("REFERENCE_QUERY_CONTROL_SELECTION_INVALID")
    pointers = (policy_member, runtime_bundle.manifest_member)
    reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in pointers))
    pointer = policy_member
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
        read(policy_member, REFERENCE_QUERY_POLICY_ARTIFACT_TYPE, 64 * 1024)
    )
    raw_bundle = read(
        runtime_bundle.manifest_member,
        RUNTIME_BUNDLE_ARTIFACT_TYPE,
        MAX_RUNTIME_BUNDLE_BYTES,
    )
    if not isinstance(raw_bundle, dict):
        raise ValueError("REFERENCE_QUERY_BUNDLE_INVALID")
    bundle = parse_embedding_runtime_bundle(raw_bundle)
    if policy.policy_sha256 != policy_sha256 or policy.runtime_bundle != runtime_bundle:
        raise ValueError("REFERENCE_QUERY_CONTROL_SELECTION_INVALID")
    return validate_reference_query_policy_bundle(policy, bundle)


def resolve_reference_query_sources(
    owner: ReferenceQuerySourceOwner,
    session: Session,
    request: SupportedReferenceQueryWorkflowRequest,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> ResolvedReferenceQuerySources:
    request = parse_supported_reference_query_workflow_request(request)
    caller = EmbeddingRegistryCaller(request.operator_audit.operator_id)
    owner.identity.fence_current_operator(session, caller.operator_id)
    config, context = owner.configuration, request.context_request
    if (
        request.native_execution_policy != config.native_execution_policy
        or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
        or request.runtime_bundle != config.runtime_bundle
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_MISMATCH")
    # Keep the original current deployment fence before opening Artifact state;
    # a historical namespace is not a replacement for current source authority.
    owner.catalog.authorize_scope(
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
    reader = (
        PinnedArtifactReadContext.for_session(session, owner.settings)
        if artifact_reader is None
        else artifact_reader
    )
    reader.require_session(session)
    if reader.settings != owner.settings:
        raise ValueError("REFERENCE_QUERY_READ_ARTIFACT_CONTEXT_INVALID")
    # A stored request owns its exact registered index identity. The current
    # deployment remains unchanged; only this operation uses its verified scope.
    catalog = owner.catalog.for_pinned_similarity_request_in_session(
        session, caller, context, artifact_reader=reader
    )
    registry = catalog.configuration
    if registry.namespace != config.registry.namespace:
        catalog.authorize_scope(
            session,
            caller,
            EmbeddingRegistryLookup(
                registry.corpus_id,
                registry.namespace,
                context.graph_snapshot,
                context.policy_revision_id,
                context.policy_sha256,
                context.maximum_sources,
            ),
        )
    policy, bundle = read_pinned_reference_query_controls(reader, config)
    validate_reference_query_request_references(request, policy, bundle)
    prepared = catalog.prepare_reference_query_anchor_in_session(
        session, caller, context, artifact_reader=reader
    )
    reader.revalidate_provenance()
    result = ResolvedReferenceQuerySources(request, policy, bundle, prepared)
    owner.identity.fence_current_operator(session, caller.operator_id)
    return result


def resolve_completed_reference_query_sources(
    owner: ReferenceQuerySourceOwner,
    session: Session,
    caller: EmbeddingRegistryCaller,
    request: SupportedReferenceQueryWorkflowRequest,
    *,
    workflow_id: str,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> ResolvedCompletedReferenceQuerySources:
    """Current read authority, never a new claim or a completed-command lease."""
    request = parse_supported_reference_query_workflow_request(request)
    owner = select_completed_reference_query_read_owner(owner, request)
    if (
        not isinstance(caller, EmbeddingRegistryCaller)
        or caller.operator_id != request.operator_audit.operator_id
    ):
        raise ValueError("REFERENCE_QUERY_READ_CALLER_INVALID")
    owner.identity.fence_current_operator(session, caller.operator_id)
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
    sources = (
        owner.resolve_sources(session, request)
        if artifact_reader is None
        else owner.resolve_sources(session, request, artifact_reader=artifact_reader)
    )
    return ResolvedCompletedReferenceQuerySources(sources, workflow, step, output)
