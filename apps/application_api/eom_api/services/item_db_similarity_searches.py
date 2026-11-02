"""Owned list search use cases; completed reads have no path to QUERY prepare or dispatch."""

from eom_api_contracts.item_db_similarity import (
    ItemDbSimilarityAnchorResult,
    ItemDbSimilarityListInput,
    ItemDbSimilaritySearchView,
)
from eom_catalog_contracts.item_db_similarity_selection_v2 import ItemDbSimilaritySelectionRequestV2
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareReplyV4
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.inference_transfer_workflow_read import authorize_inference_transfer_read
from eom_api.services.item_db_similarity import item_db_similarity_candidates
from eom_api.services.item_db_similarity_client import (
    CatalogItemDbSimilarityClient,
    ItemDbSimilarityClientError,
)
from eom_api.services.item_db_similarity_state import (
    ItemDbSimilaritySearchSnapshot,
    item_db_search_operation_id,
)
from eom_api.services.item_db_similarity_store import ItemDbSimilaritySearchStore
from eom_api.services.pagination import PageResult
from eom_api.services.query_adapter import QueryAdapter
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService
from eom_api.services.similarity_context_read import SimilarityContextReadApplicationService


def _authentication(context: RequestContext) -> AccessAuthentication:
    auth = context.authentication
    if auth is None:
        raise ApiError(401, "AUTH_REQUIRED", "Authentication required", "Login is required.")
    authorize_inference_transfer_read(auth)
    if PermissionKey.CONTENT_INTAKE_READ not in auth.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Source read denied.")
    return auth


def _start_authentication(context: RequestContext) -> AccessAuthentication:
    auth = _authentication(context)
    if PermissionKey.WORKFLOW_START not in auth.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Search start denied.")
    return auth


class ItemDbSimilaritySearchApplication:
    def __init__(
        self,
        store: ItemDbSimilaritySearchStore,
        selection: CatalogItemDbSimilarityClient,
        queries: ReferenceQueryPreparationApplicationService,
        results: SimilarityContextReadApplicationService,
        metadata: QueryAdapter,
    ) -> None:
        self.store, self.selection, self.queries, self.results, self.metadata = (
            store,
            selection,
            queries,
            results,
            metadata,
        )

    def _capture(self, record: ItemDbSimilaritySearchSnapshot) -> ItemDbSimilaritySearchSnapshot:
        if record.query is not None:
            return record
        request = ItemDbSimilaritySelectionRequestV2(
            schema_version="item-db-similarity-selection-request/2.0",
            operation="RESOLVE_ITEM_DB_SIMILARITY_LIST",
            actor_id=record.operator_id,
            operation_id=item_db_search_operation_id(record.operator_id, record.idempotency_key),
            idempotency_key=record.idempotency_key,
            selections=record.input.selections,
            top_k=record.input.top_k,
            pinned_query=None,
        )
        try:
            reply = self.selection.resolve_many(request)
        except ItemDbSimilarityClientError:
            raise ApiError(
                503,
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Search unavailable",
                "Keep the existing owned request; source resolution did not complete.",
            ) from None
        if reply.result is None:
            if reply.status == "UNAVAILABLE":
                return self.store.capture_unavailable(
                    record.operator_id,
                    record.search_id,
                    reply.error_code or "ITEM_DB_SIMILARITY_UNAVAILABLE",
                )
            raise ApiError(
                403 if reply.error_code == "SOURCE_ACCESS_DENIED" else 409,
                reply.error_code or "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Source unavailable",
                "A selected source has not been registered or indexed, or is no longer accessible.",
            )
        return self.store.latch_query(record.operator_id, record.search_id, reply.result.query)

    def submit(
        self, context: RequestContext, value: ItemDbSimilarityListInput, *, idempotency_key: str
    ) -> ItemDbSimilaritySearchView:
        auth = _start_authentication(context)
        record = self.store.admit(auth.operator.operator_id, idempotency_key, value)
        return self._capture(record).view()

    def check(self, context: RequestContext, search_id: str) -> ItemDbSimilaritySearchView:
        auth = _start_authentication(context)
        record = self.store.get(auth.operator.operator_id, search_id)
        if record.state in {"READY", "FAILED"}:
            return record.view()
        record = self._capture(record)
        if record.query is None:
            return record.view()
        assert record.query is not None
        reply = self.queries.prepare(context, record.query, idempotency_key=record.idempotency_key)
        if not isinstance(reply, ReferenceQueryPrepareReplyV4):
            raise ApiError(
                503,
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
                "Wrong query family",
                "The public list needs its exact original batch family.",
            )
        return self.store.observe(auth.operator.operator_id, search_id, reply).view()

    def get(self, context: RequestContext, search_id: str) -> ItemDbSimilaritySearchView:
        auth = _authentication(context)
        return self.store.get(auth.operator.operator_id, search_id).view()

    def recent(
        self, context: RequestContext, *, limit: int, cursor: str | None
    ) -> PageResult[ItemDbSimilaritySearchView]:
        auth = _authentication(context)
        page = self.store.list_recent(auth.operator.operator_id, limit=limit, cursor=cursor)
        return PageResult(
            tuple(record.view() for record in page.data), page.next_cursor, page.has_more
        )

    def read_result(
        self, context: RequestContext, search_id: str, ordinal: int
    ) -> ItemDbSimilarityAnchorResult:
        auth = _authentication(context)
        record = self.store.get(auth.operator.operator_id, search_id)
        if not 0 <= ordinal < len(record.input.selections):
            raise ApiError(
                404,
                "ITEM_DB_SIMILARITY_RESULT_NOT_FOUND",
                "Result not found",
                "No such input ordinal exists.",
            )
        if (
            record.query is None
            or ordinal >= len(record.children)
            or record.children[ordinal].selection is None
        ):
            raise ApiError(
                409,
                "ITEM_DB_SIMILARITY_RESULT_PENDING",
                "Result pending",
                "This exact source query is not complete yet.",
            )
        selection = record.children[ordinal].selection
        assert selection is not None
        result = self.results.read_public(auth, selection)
        if (
            result.request.anchor.source.item_revision_id
            != record.query.source_item_revision_ids[ordinal]
            or result.request.graph_snapshot != record.query.graph_snapshot
            or result.request.policy_revision_id != record.query.policy_revision_id
            or result.request.policy_sha256 != record.query.policy_sha256
            or result.request.consumer_purpose != "ITEM_DATABASE_SEARCH"
            or result.request.top_k != record.input.top_k
        ):
            raise ApiError(
                409,
                "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
                "Result differs",
                "The original completed result no longer matches this source and scope.",
            )
        return ItemDbSimilarityAnchorResult(
            search_id=search_id,
            ordinal=ordinal,
            source_item_revision_id=record.query.source_item_revision_ids[ordinal],
            status="PARTIAL" if result.status == "PARTIAL" else "READY",
            candidates=item_db_similarity_candidates(result, self.metadata),
            message="점수는 문항을 찾는 참고값이며 풀이가 같은 비율을 뜻하지 않습니다.",
        )
