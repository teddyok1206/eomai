"""Private-request public DOCUMENT reads through the existing Catalog owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.private_chat_similarity_ports import PreparedPrivateChatDocumentScope
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)
from eom_catalog_service.similarity_document_read_validation import (
    validate_prepared_similarity_sources,
    validate_similarity_document_reads,
)
from eom_catalog_service.similarity_document_read_window import SimilarityDocumentReadWindow

if TYPE_CHECKING:
    from eom_catalog_service.embedding_registry_catalog_adapter import (
        CatalogEmbeddingRegistryVerifier,
    )


def _request(value: PrivateChatSimilarityRequest) -> PrivateChatSimilarityRequest:
    try:
        return PrivateChatSimilarityRequest.model_validate(raw_similarity_contract_value(value))
    except (JsonSchemaError, ValueError, TypeError):
        # Rejected untrusted extras can contain private text; never stringify them.
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None


def _require_root(catalog: CatalogEmbeddingRegistryVerifier, session: Session) -> object:
    catalog._require_similarity_root(session)
    if session.new or session.dirty or session.deleted:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    return session.get_transaction()


def _capture(
    catalog: CatalogEmbeddingRegistryVerifier,
    session: Session,
    caller: EmbeddingRegistryCaller,
    request: PrivateChatSimilarityRequest,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> tuple[PinnedArtifactReadContext, InferenceTransferSessionCapture]:
    _require_root(catalog, session)
    if (
        type(caller) is not EmbeddingRegistryCaller
        or catalog.identity_fence is None
        or (catalog._indexing_source_authority is not None)
    ):
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    owner = catalog._document_view_owner(request.source_classes, request.views[0], request.top_k)
    scope = EmbeddingRegistryLookup(
        owner.configuration.corpus_id,
        owner.configuration.namespace,
        request.graph_snapshot,
        request.policy_revision_id,
        request.policy_sha256,
        request.maximum_sources,
    )
    # A fresh capture owner has no window-reuse shortcut. In particular, final
    # capture must not be performed through the numerical read's cached owner.
    reader, capture = owner._guard(
        lambda: owner._capture(
            session,
            caller,
            scope,
            InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
            artifact_reader=artifact_reader,
        )
    )
    if not isinstance(capture, InferenceTransferSessionCapture) or capture.corpus is None:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    return reader, capture


def _scope(
    catalog: CatalogEmbeddingRegistryVerifier,
    request: PrivateChatSimilarityRequest,
    capture: InferenceTransferSessionCapture,
) -> PreparedPrivateChatDocumentScope:
    if capture.corpus is None:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    scope = PreparedPrivateChatDocumentScope(
        request.request_sha256,
        catalog._prepared_document_sources(capture),
        capture.corpus.truncated,
    )
    validate_prepared_similarity_sources(
        scope.sources,
        source_classes=request.source_classes,
        maximum_sources=request.maximum_sources,
    )
    return scope


def prepare_private_chat_document_scope_in_session(
    catalog: CatalogEmbeddingRegistryVerifier,
    session: Session,
    caller: EmbeddingRegistryCaller,
    request: PrivateChatSimilarityRequest,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> PreparedPrivateChatDocumentScope:
    """Current public DOCUMENT scope only; no fake approved query Item or private text."""
    root = _require_root(catalog, session)
    request = _request(request)
    try:
        with session.no_autoflush:
            reader, capture = _capture(
                catalog,
                session,
                caller,
                request,
                artifact_reader=artifact_reader,
            )
            result = _scope(catalog, request, capture)
            if _require_root(catalog, session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            reader.revalidate_provenance()
            if _require_root(catalog, session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            return result
    except SimilarityContextReadError:
        raise
    except EmbeddingRegistryError as error:
        raise similarity_context_error_from_registry(error) from None
    except (PinnedArtifactResolutionError, JsonSchemaError, ValueError, TypeError, KeyError):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None


def read_private_chat_document_index_in_session(
    catalog: CatalogEmbeddingRegistryVerifier,
    session: Session,
    caller: EmbeddingRegistryCaller,
    request: PrivateChatSimilarityRequest,
    prepared: PreparedPrivateChatDocumentScope,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
    """Exact current public scope, shared pinned read and mandatory fresh end capture."""
    root = _require_root(catalog, session)
    request = _request(request)
    if type(prepared) is not PreparedPrivateChatDocumentScope:
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    prepared.__post_init__()
    sources = validate_prepared_similarity_sources(
        prepared.sources,
        source_classes=request.source_classes,
        maximum_sources=request.maximum_sources,
    )
    try:
        with session.no_autoflush:
            reader, capture = _capture(
                catalog,
                session,
                caller,
                request,
                artifact_reader=artifact_reader,
            )
            if _require_root(catalog, session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            if _scope(catalog, request, capture) != prepared:
                raise SimilarityContextReadError("SOURCE_REVOKED")
            window = SimilarityDocumentReadWindow(session, root, caller, reader, capture)
            selection = request.views[0]
            values: tuple[ResolvedPinnedEmbeddingIndex, ...] = ()
            if selection.index is not None:
                owner = catalog._document_view_owner(
                    request.source_classes, selection, request.top_k
                )
                scope = EmbeddingRegistryLookup(
                    owner.configuration.corpus_id,
                    owner.configuration.namespace,
                    request.graph_snapshot,
                    request.policy_revision_id,
                    request.policy_sha256,
                    request.maximum_sources,
                )
                values = (owner._read_document_index_in_window(window, scope, selection),)
            validate_similarity_document_reads(
                request,
                sources,
                values,
                {"CONTENT_ONLY"} if selection.index is not None else set(),
            )
            if _require_root(catalog, session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            _reader, final = _capture(
                catalog,
                session,
                caller,
                request,
                artifact_reader=reader,
            )
            if _scope(catalog, request, final) != prepared:
                raise SimilarityContextReadError("SOURCE_REVOKED")
            reader.revalidate_provenance()
            if _require_root(catalog, session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            return values
    except SimilarityContextReadError:
        raise
    except EmbeddingRegistryError as error:
        raise similarity_context_error_from_registry(error) from None
    except (PinnedArtifactResolutionError, JsonSchemaError, ValueError, TypeError, KeyError):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None
