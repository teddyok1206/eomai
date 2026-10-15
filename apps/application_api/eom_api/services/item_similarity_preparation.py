"""Fixed Catalog publication/current-read → private checked item-start preparation."""

from __future__ import annotations

from eom_catalog_contracts import EvidenceBundlePublicationResultV5
from eom_catalog_contracts.item_similarity_publication import ItemSimilarityPublication
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_delivery import validate_similarity_context_delivery
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorType, PermissionKey
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.similarity_context_artifact import PublishedSimilarityContext
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowRequest
from eom_workflow.similarity_control import PreparedSimilarityPlan
from eom_workflow_runner.item_similarity_preparation import (
    PreparedItemSimilarity,
    validate_item_similarity_scope,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
    ItemSimilarityPublicationClientError,
)
from eom_api.services.item_similarity_start import check_similarity_start
from eom_api.services.similarity_context_client import (
    CatalogSimilarityContextClient,
    SimilarityContextClientError,
)


class ItemSimilarityStartPreparationService:
    """No native launcher, privileged engine, Artifact IO or model-supplied selector.

    Trusted application composition selects a completed QUERY. The existing item
    command must still atomically check the resulting value before its first plan.
    """

    def __init__(
        self,
        publications: CatalogItemSimilarityPublicationClient,
        contexts: CatalogSimilarityContextClient,
    ) -> None:
        self.publications = publications
        self.contexts = contexts

    def prepare(
        self,
        actor: ActorContext,
        selection: CompletedSimilarityQuerySelection,
        *,
        workflow_request: WorkflowRequest,
        expected_resolution: ExpectedWorkflowResolution,
        evidence: EvidenceBundlePublicationResultV5,
        preset: ExecutionPresetRevisionV2,
    ) -> PreparedItemSimilarity:
        if actor.actor_type is not ActorType.OPERATOR or (
            PermissionKey.WORKFLOW_START not in actor.permissions
        ):
            raise ApiError(
                403,
                "CONTROL_SIMILARITY_AUTHORITY_DENIED",
                "Similarity action denied",
                "The actual item-start caller cannot prepare this request.",
            )
        try:
            selection = CompletedSimilarityQuerySelection.model_validate(selection)
            # Publication is an independently authorized canonical auxiliary result,
            # not item acceptance. Materialize it once at this validation boundary.
            publication = ItemSimilarityPublication.model_validate(
                self.publications.publish(actor.actor_id, selection)
            )
            context = parse_similarity_context(self.contexts.read(actor.actor_id, selection))
            request, resolution, evidence, preset = validate_item_similarity_scope(
                workflow_request=workflow_request,
                expected_resolution=expected_resolution,
                evidence=evidence,
                preset=preset,
                context_request=context.request,
            )
            validate_similarity_context_delivery(
                publication.delivery, context, expected_request=context.request
            )
            preparation = PreparedItemSimilarity(
                PreparedSimilarityPlan(publication.delivery, context),
                PublishedSimilarityContext(
                    publication.owner_job_id, publication.delivery, publication.manifest_sha256
                ),
                content_sha256(request.model_dump(mode="json")),
                evidence.result_sha256,
                preset.content_sha256,
                resolution,
                selection,
                actor.actor_id,
            )
            return check_similarity_start(preparation, request, actor).preparation
        except (SimilarityContextClientError, ItemSimilarityPublicationClientError) as error:
            denied = error.code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
            raise ApiError(
                403 if denied else 503,
                "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                if denied
                else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                "Similarity owner unavailable",
                "The current Catalog preparation did not complete.",
            ) from None
        except ControlPlaneError as error:
            raise ApiError(
                409,
                error.code,
                "Similarity scope differs",
                "The item request and pinned context do not agree.",
            ) from None
        except (ValueError, TypeError, SchemaError):
            # A publication can already exist. Preserve it and the original key.
            raise ApiError(
                409,
                "CONTROL_SIMILARITY_PREPARATION_INVALID",
                "Similarity preparation differs",
                "The checked context and publication do not match the item request.",
            ) from None
