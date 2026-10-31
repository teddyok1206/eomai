"""Current operator-fenced Catalog materialization; no model, writes or source grants."""

from __future__ import annotations

import json

from eom_catalog_contracts.assessment_item import AssessmentItemContentContract
from eom_catalog_contracts.public_similarity_materials import (
    PublicQuestionAvailable,
    PublicQuestionUnavailable,
    PublicSolutionReferenceMaterial,
    PublicSolutionSimilarityMaterials,
    build_public_similarity_materials,
)
from eom_catalog_contracts.public_solution_delivery import (
    validate_deliverable_public_solution_context,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
)
from eom_catalog_contracts.similarity_materials import MAX_SIMILARITY_MATERIAL_CANDIDATES
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.inference_transfer_item_projection import (
    ItemProjectionUnavailable,
    render_public_reference_item_text,
)
from eom_catalog_service.item_content_contract import ITEM_CONTENT_SCHEMAS, read_item_content
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)

# Same source-member resource ceiling as the existing canonical question projector.
# Report text has its own immutable recipe budget and is never clipped here.
MAX_PUBLIC_MATERIAL_SOURCE_BYTES = 16 * 1024 * 1024


def _decode_question(schema_ref: str, payload: bytes) -> AssessmentItemContentContract:
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError("public reference question is not an object")
    return read_item_content(schema_ref, document)


def _question_material(
    reader: PinnedArtifactReadContext, entry: PublicSolutionEncodingEntry
) -> PublicSolutionReferenceMaterial:
    source = entry.source.artifact_member
    if source.media_type != "application/json":
        return PublicSolutionReferenceMaterial(
            entry=entry, question=PublicQuestionUnavailable(reason="MEDIA_TYPE_UNSUPPORTED")
        )
    if source.schema_ref is None or source.schema_ref not in ITEM_CONTENT_SCHEMAS:
        return PublicSolutionReferenceMaterial(
            entry=entry, question=PublicQuestionUnavailable(reason="SCHEMA_UNSUPPORTED")
        )
    if source.bytes > MAX_PUBLIC_MATERIAL_SOURCE_BYTES:
        return PublicSolutionReferenceMaterial(
            entry=entry, question=PublicQuestionUnavailable(reason="SOURCE_BYTE_LIMIT_EXCEEDED")
        )
    pointer = ArtifactMemberPointer(
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        member_path=source.member_path,
        schema_ref=source.schema_ref,
        media_type=source.media_type,
        sha256=source.sha256,
    )
    item = reader.read_model_member(pointer, expected_bytes=source.bytes, decoder=_decode_question)
    try:
        content = render_public_reference_item_text(
            item=item, original_source=source, recipe=entry.recipe
        )
    except ItemProjectionUnavailable as error:
        if error.code != "INFERENCE_ITEM_TEXT_TOO_LARGE":
            raise
        return PublicSolutionReferenceMaterial(
            entry=entry,
            question=PublicQuestionUnavailable(reason="QUESTION_TEXT_LIMIT_EXCEEDED"),
        )
    return PublicSolutionReferenceMaterial(
        entry=entry, question=PublicQuestionAvailable(content=content)
    )


class CatalogPublicSolutionMaterialsRead:
    """Read exact selected sources once, with bounded root-local Artifact reuse.

    The calling application must independently resolve completed QUERY/context
    provenance before and after this operation. A supplied typed context alone
    is not proof of execution, current permission, pixel access or item quality.
    """

    def __init__(self, catalog: CatalogEmbeddingRegistryVerifier) -> None:
        if type(catalog) is not CatalogEmbeddingRegistryVerifier or not isinstance(
            catalog.configuration.namespace, PublicSolutionIndexNamespace
        ):
            raise ValueError("PUBLIC_SIMILARITY_CATALOG_OWNER_REQUIRED")
        self.catalog = catalog

    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        context: SupportedPublicSolutionSimilarityContext,
    ) -> PublicSolutionSimilarityMaterials:
        root = session.get_transaction()
        if (
            root is None
            or not root.is_active
            or session.in_nested_transaction()
            or session.get_bind() is not self.catalog.engine
            or type(caller) is not EmbeddingRegistryCaller
            or self.catalog.identity_fence is None
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        try:
            context = validate_deliverable_public_solution_context(
                context, expected_request=context.request
            )
            request, config = context.request, self.catalog.configuration
            if (
                len(context.candidates) > MAX_SIMILARITY_MATERIAL_CANDIDATES
                or request.views[0].index.storage_partition != config.namespace.storage_partition
                or request.views[0].index.spaces.document != config.space
                or request.views[0].recipe != config.recipe
                or request.source_classes != config.source_classes
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            references = (request.anchor, *context.candidates)
            keys = tuple(sorted(reference.source.item_revision_id for reference in references))
            scope = EmbeddingRegistryLookup(
                config.corpus_id,
                config.namespace,
                request.graph_snapshot,
                request.policy_revision_id,
                request.policy_sha256,
                request.maximum_sources,
            )
            reader = PinnedArtifactReadContext.for_session(session, self.catalog.settings)
            resolved = self.catalog.resolve_selected_sources(
                session, caller, SelectedEmbeddingSources(scope, keys), artifact_reader=reader
            )
            entries = {
                entry.source.item_revision_id: entry
                for entry in resolved.entries
                if isinstance(
                    entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                )
            }
            if (
                resolved.truncated
                or len(entries) != len(resolved.entries)
                or len(entries) != len(keys)
                or set(entries) != set(keys)
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            reader.prefetch(
                tuple(
                    (
                        entry.source.artifact_member.artifact_id,
                        entry.source.artifact_member.artifact_revision_id,
                    )
                    for entry in entries.values()
                )
            )
            materials = tuple(
                _question_material(reader, entries[reference.source.item_revision_id])
                for reference in references
            )
            result = build_public_similarity_materials(
                context, anchor=materials[0], entries=materials[1:]
            )
            self.catalog.authorize_scope(session, caller, scope)
            reader.revalidate_provenance()
            return result
        except SimilarityContextReadError:
            raise
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, TypeError, SchemaError):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None
