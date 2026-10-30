"""Current HTTP source → existing official QUERY → canonical read → DB navigation."""

from eom_api_contracts.item_db_similarity import (
    ItemDbSimilarityCandidate,
    ItemDbSimilarityInput,
    ItemDbSimilarityView,
)
from eom_catalog_contracts.item_db_similarity_selection import ItemDbSimilaritySelectionRequest
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareReplyV4
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.inference_transfer_workflow_read import authorize_inference_transfer_read
from eom_api.services.item_db_similarity_client import (
    CatalogItemDbSimilarityClient,
    ItemDbSimilarityClientError,
)
from eom_api.services.query_adapter import QueryAdapter
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService
from eom_api.services.similarity_context_read import SimilarityContextReadApplicationService


class ItemDbSimilarityApplicationService:
    def __init__(
        self,
        selection: CatalogItemDbSimilarityClient,
        queries: ReferenceQueryPreparationApplicationService,
        results: SimilarityContextReadApplicationService,
        metadata: QueryAdapter,
    ) -> None:
        self.selection, self.queries, self.results, self.metadata = (
            selection,
            queries,
            results,
            metadata,
        )

    def search(
        self,
        context: RequestContext,
        body: ItemDbSimilarityInput,
        *,
        idempotency_key: str,
    ) -> ItemDbSimilarityView:
        authentication = context.authentication
        if authentication is None:
            raise ApiError(401, "AUTH_REQUIRED", "Authentication required", "Login is required.")
        authorize_inference_transfer_read(authentication)
        if not {PermissionKey.CONTENT_INTAKE_READ, PermissionKey.WORKFLOW_START}.issubset(
            authentication.permissions
        ):
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Source read denied.")
        body = ItemDbSimilarityInput.model_validate(body)
        operation = content_sha256({"purpose": "ITEM_DATABASE_SEARCH/1.0", "key": idempotency_key})
        try:
            request = ItemDbSimilaritySelectionRequest(
                schema_version="item-db-similarity-selection-request/1.0",
                operation="RESOLVE_ITEM_DB_SIMILARITY",
                actor_id=authentication.operator.operator_id,
                operation_id="queryprepare_" + operation[7:39],
                idempotency_key=idempotency_key,
                selection=body.selection,
                top_k=body.top_k,
                pinned_query=body.pinned_query,
            )
        except (ValueError, SchemaError):
            raise ApiError(
                409,
                "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
                "Search input differs",
                "Retain the original source, key and pinned query together.",
            ) from None
        try:
            resolved = self.selection.resolve(request)
        except ItemDbSimilarityClientError:
            raise ApiError(
                503,
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Similarity unavailable",
                "The canonical selected source could not be resolved; retain the original key.",
            ) from None
        selected = resolved.result
        if selected is None:
            if resolved.status == "UNAVAILABLE":
                return ItemDbSimilarityView(
                    status="UNAVAILABLE",
                    phase="PREPARING",
                    candidates=(),
                    pinned_query=body.pinned_query,
                    search_snapshot_sha256=None,
                    message="풀이보고서와 검색 자료가 아직 준비되지 않았습니다.",
                    error_code=resolved.error_code,
                )
            raise ApiError(
                403 if resolved.error_code == "SOURCE_ACCESS_DENIED" else 409,
                resolved.error_code or "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Similarity source unavailable",
                "The exact selected source could not be verified.",
            )
        reply = self.queries.prepare(context, selected.query, idempotency_key=idempotency_key)
        if not isinstance(reply, ReferenceQueryPrepareReplyV4):
            raise ApiError(
                503,
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Invalid query family",
                "The public search cannot use a legacy query response.",
            )
        if reply.status != "READY":
            return ItemDbSimilarityView(
                status=reply.status,
                phase="COMPUTING" if reply.device is not None else "WAITING_FOR_RESOURCE",
                candidates=(),
                pinned_query=selected.query,
                search_snapshot_sha256=selected.search_snapshot_sha256,
                message=(
                    "같은 검색 요청의 처리가 진행되고 있습니다."
                    if reply.status == "PENDING"
                    else "이 범위의 검색 자료가 아직 준비되지 않았습니다."
                    if reply.status == "UNAVAILABLE"
                    else "검색을 완료하지 못했습니다. 같은 요청으로 다시 확인해 주세요."
                ),
                error_code=reply.error_code,
            )
        if reply.selection is None or len(reply.children) != 1:
            raise ApiError(
                503,
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Missing query selection",
                "One exact completed source query is required.",
            )
        result = self.results.read_public(authentication, reply.selection)
        if (
            result.request.anchor.source.item_revision_id != selected.anchor.item_revision_id
            or result.request.graph_snapshot != selected.query.graph_snapshot
            or result.request.policy_revision_id != selected.query.policy_revision_id
            or result.request.policy_sha256 != selected.query.policy_sha256
            or result.request.consumer_purpose != "ITEM_DATABASE_SEARCH"
            or result.request.top_k != selected.query.top_k
        ):
            raise ApiError(
                409,
                "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
                "Search source differs",
                "The completed query differs from the exact selected Item.",
            )
        metadata = (
            self.metadata.selected_production_item_candidates(
                tuple(candidate.source for candidate in result.candidates)
            )
            if result.candidates
            else ()
        )
        by_revision = {entry.item_revision_id: entry for entry in metadata}
        return ItemDbSimilarityView(
            status="READY" if result.status == "EMPTY" else result.status,
            phase="READING_RESULTS",
            pinned_query=selected.query,
            search_snapshot_sha256=selected.search_snapshot_sha256,
            candidates=tuple(
                ItemDbSimilarityCandidate(
                    entry=by_revision[candidate.source.item_revision_id],
                    label=by_revision[candidate.source.item_revision_id].source_display_label,
                    unit_label=" · ".join(
                        unit.label
                        for unit in by_revision[candidate.source.item_revision_id].curriculum_units
                    ),
                    cosine_millionths=candidate.observation.cosine_millionths,
                )
                for candidate in result.candidates
            ),
            message="점수는 참고값이며 풀이의 동일성이나 정확성을 뜻하지 않습니다.",
            error_code=None,
        )
