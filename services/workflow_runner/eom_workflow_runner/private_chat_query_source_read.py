"""Live Chat ownership, current public Catalog reads and exact private controls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.private_chat_query_read import (
    ChatPrivateQueryOrigin,
    LiveChatQueryProjection,
)
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.private_chat_similarity_ports import PreparedPrivateChatDocumentScope
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFence, OperatorAuthorizationFenceError
from eom_orchestrator.embedding_runtime_bundle_artifacts import RUNTIME_BUNDLE_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.general_chat_similarity_basis import (
    PreparedPrivateChatQuery,
    prepare_private_chat_query_execution_input,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.local_embedding_control_artifacts import (
    PRIVATE_CHAT_QUERY_POLICY_ARTIFACT_TYPE,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket
from eom_workflow.private_chat_query_execution import (
    PRIVATE_CHAT_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    validate_private_chat_query_request_references,
)
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session


class LivePrivateChatSource(Protocol):
    """Actual fixed-peer client in installed composition; never worker wire authority."""

    def materialize(self, ticket: ChatWorkerTicket) -> LiveChatQueryProjection: ...
    def authorize(self, origin: ChatPrivateQueryOrigin) -> ChatPrivateQueryOrigin: ...


@dataclass(frozen=True, slots=True)
class PrivateChatQueryOwnerConfiguration:
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
            or pointer.schema_ref != PRIVATE_CHAT_QUERY_POLICY_REF
            or pointer.media_type != "application/json"
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID")
        TypeAdapter(Sha256).validate_python(self.native_execution_policy_sha256, strict=True)
        object.__setattr__(self, "native_execution_policy", pointer)
        object.__setattr__(
            self,
            "runtime_bundle",
            EmbeddingRuntimeBundlePointer.model_validate(
                raw_similarity_contract_value(self.runtime_bundle)
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedPrivateChatQuerySources:
    """Temporary source materialization; cannot retain a live claim or execution grant."""

    request: PrivateChatQueryWorkflowRequest
    policy: PrivateChatQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    projection: LiveChatQueryProjection = field(repr=False)
    documents: PreparedPrivateChatDocumentScope

    def __post_init__(self) -> None:
        request, policy = validate_private_chat_query_request_references(
            self.request, self.policy, self.bundle
        )
        projection = LiveChatQueryProjection.model_validate(
            raw_similarity_contract_value(self.projection)
        )
        if type(self.documents) is not PreparedPrivateChatDocumentScope:
            raise ValueError("PRIVATE_CHAT_QUERY_SOURCE_CLOSURE_INVALID")
        self.documents.__post_init__()
        if (
            projection.origin.actor_id != request.operator_audit.operator_id
            or projection.origin.basis != request.context_request.query_basis
            or self.documents.request_sha256 != request.context_request.request_sha256
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_SOURCE_CLOSURE_INVALID")
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "projection", projection)


def build_private_chat_query_native_input(
    sources: ResolvedPrivateChatQuerySources, *, job_id: str, query_request_id: str
) -> EmbeddingPrivateChatQueryInput:
    """Reuse the one canonical question projection; not current authority or execution."""
    try:
        sources.__post_init__()
        return prepare_private_chat_query_execution_input(
            PreparedPrivateChatQuery(sources.projection.origin.basis, sources.projection.text),
            sources.request,
            sources.policy,
            sources.bundle,
            job_id=job_id,
            query_request_id=query_request_id,
        )
    except (SchemaError, ValueError, TypeError):
        raise ValueError("PRIVATE_CHAT_QUERY_CURRENT_INPUT_INVALID") from None


def validate_current_private_chat_query_input(
    sources: ResolvedPrivateChatQuerySources,
    launch: PrivateChatQueryLaunchAssociation,
    native: EmbeddingPrivateChatQueryInput,
) -> None:
    """Reconstruct the same original input; this pure comparison grants no authority."""
    try:
        current = build_private_chat_query_native_input(
            sources, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
        )
        native = EmbeddingPrivateChatQueryInput.model_validate(
            raw_similarity_contract_value(native)
        )
        validate_private_chat_query_launch(
            launch, sources.request, sources.policy, sources.bundle, native
        )
        if current != native:
            raise ValueError()
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_CURRENT_INPUT_INVALID") from None


def require_private_chat_query_source_root(session: Session) -> object:
    """Require the same clean caller root before reads can autoflush pending writes."""
    root = session.get_transaction()
    if (
        not session.is_active
        or root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    return root


def read_pinned_private_chat_query_controls(
    reader: PinnedArtifactReadContext, config: PrivateChatQueryOwnerConfiguration
) -> tuple[PrivateChatQueryExecutionPolicy, EmbeddingRuntimeBundle]:
    """Selected immutable bytes, never a release, source permission or default latest."""
    config.__post_init__()
    pointers = (config.native_execution_policy, config.runtime_bundle.manifest_member)
    reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in pointers))
    policy_member = config.native_execution_policy
    reader.require_file_set(
        policy_member.artifact_id,
        policy_member.artifact_revision_id,
        ("policy.json",),
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
    )

    def read(pointer: ArtifactMemberPointer, artifact_type: str, maximum: int) -> object:
        payload = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(artifact_type,),
            expected_primary_file=pointer.member_path,
            max_bytes=maximum,
        ).payload
        value: object = json.loads(payload)
        if canonical_json_bytes(value) != payload:
            raise ValueError("PRIVATE_CHAT_QUERY_CONTROL_NONCANONICAL")
        return value

    policy = PrivateChatQueryExecutionPolicy.model_validate(
        read(policy_member, PRIVATE_CHAT_QUERY_POLICY_ARTIFACT_TYPE, 64 * 1024)
    )
    raw_bundle = read(
        config.runtime_bundle.manifest_member,
        RUNTIME_BUNDLE_ARTIFACT_TYPE,
        MAX_RUNTIME_BUNDLE_BYTES,
    )
    if not isinstance(raw_bundle, dict):
        raise ValueError("PRIVATE_CHAT_QUERY_CONTROL_INVALID")
    bundle = parse_embedding_runtime_bundle(raw_bundle)
    if (
        policy.policy_sha256 != config.native_execution_policy_sha256
        or policy.runtime_bundle != config.runtime_bundle
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CONTROL_SELECTION_INVALID")
    return policy, bundle


class CatalogPrivateChatQuerySourceOwner:
    """Explicit composition of actual independent owners; no Job/Workflow/native writes."""

    def __init__(
        self,
        engine: Engine,
        configuration: PrivateChatQueryOwnerConfiguration,
        *,
        chat: LivePrivateChatSource,
        identity_fence: OperatorAuthorizationFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        configuration.__post_init__()
        if (
            identity_fence is None
            or not callable(getattr(identity_fence, "fence_current_operator", None))
            or not callable(getattr(chat, "materialize", None))
            or not callable(getattr(chat, "authorize", None))
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        self.configuration, self.chat, self.identity = configuration, chat, identity_fence
        self.settings = settings or CatalogSettings.from_environment()
        self.catalog = CatalogEmbeddingRegistryVerifier(
            engine, configuration.registry, identity_fence=identity_fence, settings=self.settings
        )

    def resolve_sources(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        origin: ChatPrivateQueryOrigin,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> ResolvedPrivateChatQuerySources:
        root = require_private_chat_query_source_root(session)
        try:
            request = PrivateChatQueryWorkflowRequest.model_validate(
                raw_similarity_contract_value(request)
            )
            origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
            config = self.configuration
            if (
                request.operator_audit.operator_id != origin.actor_id
                or request.context_request.query_basis != origin.basis
                or request.native_execution_policy != config.native_execution_policy
                or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
                or request.runtime_bundle != config.runtime_bundle
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            with session.no_autoflush:
                self.identity.fence_current_operator(session, origin.actor_id)
                if require_private_chat_query_source_root(session) is not root:
                    raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
                projection = LiveChatQueryProjection.model_validate(
                    raw_similarity_contract_value(self.chat.materialize(origin.ticket))
                )
                if projection.origin != origin:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                if require_private_chat_query_source_root(session) is not root:
                    raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
                reader = (
                    PinnedArtifactReadContext(session, self.settings)
                    if artifact_reader is None
                    else artifact_reader
                )
                reader.require_session(session)
                if reader.settings != self.settings:
                    raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
                policy, bundle = read_pinned_private_chat_query_controls(reader, config)
                validate_private_chat_query_request_references(request, policy, bundle)
                caller = EmbeddingRegistryCaller(origin.actor_id)
                documents = self.catalog.prepare_private_chat_document_scope_in_session(
                    session, caller, request.context_request, artifact_reader=reader
                )
                reads = self.catalog.read_private_chat_document_index_in_session(
                    session, caller, request.context_request, documents, artifact_reader=reader
                )
                if len(reads) != 1:
                    raise SimilarityContextReadError("INDEX_POINTER_INVALID")
                result = ResolvedPrivateChatQuerySources(
                    request, policy, bundle, projection, documents
                )
                final_origin = ChatPrivateQueryOrigin.model_validate(
                    raw_similarity_contract_value(self.chat.authorize(origin))
                )
                if final_origin != origin:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                if require_private_chat_query_source_root(session) is not root:
                    raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
                self.identity.fence_current_operator(session, origin.actor_id)
                # The private owner RPC may overlap a public-source revocation.
                # Reuse immutable decoding, never the earlier source authority.
                final_documents = self.catalog.prepare_private_chat_document_scope_in_session(
                    session, caller, request.context_request, artifact_reader=reader
                )
                if final_documents != documents:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                reader.revalidate_provenance()
                if require_private_chat_query_source_root(session) is not root:
                    raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
                return result
        except SimilarityContextReadError:
            raise
        except OperatorAuthorizationFenceError as error:
            raise SimilarityContextReadError(
                "SOURCE_ACCESS_DENIED"
                if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                else "AUTHORITY_UNAVAILABLE"
            ) from None
        except ChatError as error:
            raise SimilarityContextReadError(
                "SOURCE_ACCESS_DENIED"
                if error.code == "GENERAL_CHAT_FORBIDDEN"
                else "SOURCE_POINTER_INVALID"
                if error.code == "GENERAL_CHAT_POINTER_INVALID"
                else "AUTHORITY_UNAVAILABLE"
            ) from None
        except (
            PinnedArtifactResolutionError,
            SchemaError,
            ValueError,
            TypeError,
            KeyError,
            OSError,
        ):
            # Exception representations may include the private question. Never stringify.
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None
