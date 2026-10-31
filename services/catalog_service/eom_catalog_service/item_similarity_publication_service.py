"""Current Catalog source owner → existing Orchestrator context publisher."""

from __future__ import annotations

from eom_catalog_contracts.item_similarity_publication import (
    ItemSimilarityPublication,
    ItemSimilarityPublicationRequest,
    ItemSimilarityPublicationRequestV2,
    ItemSimilarityPublicationV2,
)
from eom_catalog_contracts.public_solution_delivery import (
    validate_deliverable_public_solution_context,
    validate_public_solution_similarity_delivery,
)
from eom_catalog_contracts.similarity_context import MAX_SIMILARITY_CONTEXT_BYTES
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetPublisher,
)
from eom_orchestrator.similarity_context_artifact import (
    SIMILARITY_CONTEXT_ARTIFACT_TYPE,
    publish_public_solution_similarity_context,
)
from eom_workflow.reference_query_execution import PublicReferenceQueryWorkflowRequest
from eom_workflow_runner.item_similarity_preparation import (
    CatalogItemSimilarityPreparation,
    require_item_similarity_start_permission,
)
from eom_workflow_runner.reference_query_consumer_read import (
    CatalogCompletedReferenceQueryRead,
    read_completed_public_solution_similarity_in_session,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError


class CatalogItemSimilarityPublicationService:
    """Pointer-only publication for the authenticated API, not QUERY or item submission."""

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        publisher: ControlFileSetPublisher,
        *,
        source_commit: str,
    ) -> None:
        self.owner = owner
        self.publisher = publisher
        self.source_commit = source_commit
        self.sessions = build_session_factory(owner.catalog.engine)

    def publish(self, request: ItemSimilarityPublicationRequest) -> ItemSimilarityPublication:
        request = ItemSimilarityPublicationRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        with self.sessions.begin() as session:
            original = select_completed_reference_query_request(
                session, self.owner, caller, request.selection
            )
        query = CatalogCompletedReferenceQueryRead(
            self.owner, workflow_id=request.selection.workflow_id, request=original
        )
        # The shared owner rechecks current operator/source/history/member state in
        # its actual root before publication and after the independent Artifact commit.
        _plan, published = CatalogItemSimilarityPreparation(
            query, self.publisher, source_commit=self.source_commit
        ).publish_context(caller)
        return ItemSimilarityPublication(
            owner_job_id=published.owner_job_id,
            delivery=published.delivery,
            manifest_sha256=published.manifest_sha256,
        )

    def publish_public(
        self, request: ItemSimilarityPublicationRequestV2
    ) -> ItemSimilarityPublicationV2:
        """Original completed public QUERY, reauthorized before and after the existing commit.

        Native launch, current-head selection and Item acceptance are deliberately absent.
        A late failure may leave a valid committed Artifact; preserve its original key.
        """
        request = ItemSimilarityPublicationRequestV2.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        with self.sessions.begin() as session:
            try:
                original = select_completed_reference_query_request(
                    session, self.owner, caller, request.selection
                )
                if not isinstance(original, PublicReferenceQueryWorkflowRequest) or (
                    original.context_request.consumer_purpose
                    not in {"ITEM_AUTHORING", "PAST_EXAM_VARIATION"}
                ):
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_FAMILY_INVALID")
                require_item_similarity_start_permission(session, self.owner, caller)
                context = validate_deliverable_public_solution_context(
                    read_completed_public_solution_similarity_in_session(
                        session, self.owner, caller, request.selection
                    ),
                    expected_request=original.context_request,
                )
                key = "item-public-similarity:" + content_sha256(
                    dict(
                        operator_id=caller.operator_id,
                        query_workflow_id=request.selection.workflow_id,
                        context_request_sha256=original.context_request.request_sha256,
                    )
                ).removeprefix("sha256:")
                publication = publish_public_solution_similarity_context(
                    self.publisher,
                    context=context,
                    expected_request=original.context_request,
                    idempotency_key=key,
                    source_commit=self.source_commit,
                )
                pin = publication.delivery.context_member
                reader = PinnedArtifactReadContext(session, self.owner.settings)
                reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
                reader.require_file_set(
                    pin.artifact_id,
                    pin.artifact_revision_id,
                    ("context.json",),
                    manifest_version=CONTROL_FILE_SET_PROTOCOL,
                    manifest_sha256=publication.manifest_sha256,
                )
                read_arguments = pin.model_dump(mode="python") | {
                    "expected_artifact_types": (SIMILARITY_CONTEXT_ARTIFACT_TYPE,),
                    "expected_primary_file": "context.json",
                    "max_bytes": MAX_SIMILARITY_CONTEXT_BYTES,
                }
                member = reader.read_pinned(**read_arguments)
                if (
                    member.producer_job_id != publication.owner_job_id
                    or member.payload != canonical_json_bytes(context.model_dump(mode="json"))
                ):
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_BYTES_MISMATCH")
                late = read_completed_public_solution_similarity_in_session(
                    session, self.owner, caller, request.selection
                )
                if late != context:
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_SOURCE_CHANGED")
                validate_public_solution_similarity_delivery(
                    publication.delivery, late, expected_request=original.context_request
                )
                reader.revalidate_provenance()
                if reader.read_pinned(**read_arguments).payload != member.payload:
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_MEMBER_CHANGED")
                require_item_similarity_start_permission(session, self.owner, caller)
                return ItemSimilarityPublicationV2(
                    owner_job_id=publication.owner_job_id,
                    delivery=publication.delivery,
                    manifest_sha256=publication.manifest_sha256,
                )
            except SimilarityContextReadError:
                # Preserve the official owner's stable revoke/missing/hash code and HTTP meaning.
                raise
            except OperatorAuthorizationFenceError as error:
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                    if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                    else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                    "current owner unavailable",
                ) from None
            except (ValueError, TypeError, SchemaError):
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_PREPARATION_INVALID", "public preparation did not close"
                ) from None
