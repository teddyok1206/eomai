"""Short PostgreSQL roots for owned history; no Catalog RPC or model execution inside locks."""

from eom_api_contracts.item_db_similarity import (
    ItemDbSimilarityListInput,
    ItemDbSimilaritySearchView,
)
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    ReferenceQueryPrepareRequestV4,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.item_db_similarity_models import ItemDbSimilaritySearchRecord
from eom_api.services.item_db_similarity_state import (
    ItemDbSimilaritySearchSnapshot,
    item_db_search_operation_id,
    merge_item_db_search_children,
)
from eom_api.services.pagination import CursorCodec, PageResult


def _conflict() -> ApiError:
    return ApiError(
        409,
        "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
        "Search differs",
        "Keep the original search identity and immutable inputs.",
    )


def _snapshot(row: ItemDbSimilaritySearchRecord) -> ItemDbSimilaritySearchSnapshot:
    value = ItemDbSimilarityListInput.model_validate(row.input_json)
    if content_sha256(value) != row.intent_sha256:
        raise _conflict()
    presentation = ItemDbSimilaritySearchView.model_validate(
        dict(
            search_id=row.search_id,
            created_at=row.created_at,
            selections=value.selections,
            top_k=value.top_k,
            status=row.state,
            device=row.device,
            children=row.children_json,
            error_code=row.error_code,
        )
    )
    result = ItemDbSimilaritySearchSnapshot(
        search_id=row.search_id,
        operator_id=row.operator_id,
        idempotency_key=row.idempotency_key,
        intent_sha256=row.intent_sha256,
        input=value,
        query=None
        if row.pinned_query is None
        else ReferenceQueryPrepareRequestV4.model_validate(row.pinned_query),
        children=presentation.children,
        state=presentation.status,
        device=presentation.device,
        error_code=row.error_code,
        created_at=row.created_at,
    )
    return result


class ItemDbSimilaritySearchStore:
    def __init__(self, engine: Engine, fingerprint_key: bytes) -> None:
        self.sessions = build_session_factory(engine)
        self.cursors = CursorCodec(fingerprint_key)

    def _owned(
        self, session: Session, actor_id: str, search_id: str
    ) -> ItemDbSimilaritySearchRecord:
        row = session.scalar(
            select(ItemDbSimilaritySearchRecord).where(
                ItemDbSimilaritySearchRecord.search_id == search_id,
                ItemDbSimilaritySearchRecord.operator_id == actor_id,
            )
        )
        if row is None:
            raise ApiError(
                404,
                "ITEM_DB_SIMILARITY_SEARCH_NOT_FOUND",
                "Search not found",
                "No accessible search exists with this identity.",
            )
        return row

    def get(self, actor_id: str, search_id: str) -> ItemDbSimilaritySearchSnapshot:
        with self.sessions.begin() as session:
            return _snapshot(self._owned(session, actor_id, search_id))

    def admit(
        self, actor_id: str, key: str, value: ItemDbSimilarityListInput
    ) -> ItemDbSimilaritySearchSnapshot:
        value = ItemDbSimilarityListInput.model_validate(value)
        digest = content_sha256(value)
        identity = content_sha256({"operator_id": actor_id, "key": key})
        with self.sessions.begin() as session:
            session.execute(
                insert(ItemDbSimilaritySearchRecord)
                .values(
                    search_id="dbsearch_" + identity[7:39],
                    operator_id=actor_id,
                    idempotency_key=key,
                    intent_sha256=digest,
                    input_json=value.model_dump(mode="json"),
                    pinned_query=None,
                    children_json=[],
                    state="PREPARING",
                )
                .on_conflict_do_nothing(index_elements=["operator_id", "idempotency_key"])
            )
            row = self._owned(session, actor_id, "dbsearch_" + identity[7:39])
            if row.intent_sha256 != digest or row.input_json != value.model_dump(mode="json"):
                raise _conflict()
            return _snapshot(row)

    def latch_query(
        self, actor_id: str, search_id: str, query: ReferenceQueryPrepareRequestV4
    ) -> ItemDbSimilaritySearchSnapshot:
        query = ReferenceQueryPrepareRequestV4.model_validate(query)
        with self.sessions.begin() as session:
            row = self._owned(session, actor_id, search_id)
            session.refresh(row, with_for_update=True)
            current = _snapshot(row)
            if (
                query.idempotency_key != row.idempotency_key
                or query.operation_id != item_db_search_operation_id(actor_id, row.idempotency_key)
                or query.consumer_purpose != "ITEM_DATABASE_SEARCH"
                or query.top_k != current.input.top_k
                or len(query.source_item_revision_ids) != len(current.input.selections)
            ):
                raise _conflict()
            if row.pinned_query is None:
                row.pinned_query = query.model_dump(mode="json")
                row.state, row.error_code = "PENDING", None
                session.flush()
            # Concurrent initial captures converge on the first committed pin, not latest.
            return _snapshot(row)

    def observe(
        self, actor_id: str, search_id: str, reply: ReferenceQueryPrepareReplyV4
    ) -> ItemDbSimilaritySearchSnapshot:
        with self.sessions.begin() as session:
            row = self._owned(session, actor_id, search_id)
            session.refresh(row, with_for_update=True)
            current = _snapshot(row)
            query = current.query
            if (
                query is None
                or reply.request_sha256 != query.request_sha256
                or reply.operation_id != query.operation_id
            ):
                raise _conflict()
            try:
                children = merge_item_db_search_children(current.children, reply.children, query)
            except ValueError:
                raise _conflict() from None
            if current.device is not None and reply.device not in {None, current.device}:
                raise _conflict()
            row.children_json = [child.model_dump(mode="json") for child in children]
            row.device = current.device or reply.device
            if children and all(child.state == "COMPLETED" for child in children):
                row.state, row.error_code = "READY", None
            elif any(child.state == "FAILED" for child in children):
                row.state, row.error_code = "FAILED", "REFERENCE_QUERY_EXECUTION_FAILED"
            elif current.state not in {"READY", "FAILED"}:
                row.state, row.error_code = reply.status, reply.error_code
            session.flush()
            return _snapshot(row)

    def capture_unavailable(
        self, actor_id: str, search_id: str, error_code: str
    ) -> ItemDbSimilaritySearchSnapshot:
        with self.sessions.begin() as session:
            row = self._owned(session, actor_id, search_id)
            session.refresh(row, with_for_update=True)
            if row.pinned_query is None:
                row.state, row.error_code = "UNAVAILABLE", error_code
                session.flush()
            return _snapshot(row)

    def list_recent(
        self, actor_id: str, *, limit: int, cursor: str | None
    ) -> PageResult[ItemDbSimilaritySearchSnapshot]:
        scope = "item-db-similarity:" + actor_id
        conditions = [ItemDbSimilaritySearchRecord.operator_id == actor_id]
        if cursor:
            created, identity = self.cursors.decode(cursor, scope)
            conditions.append(
                or_(
                    ItemDbSimilaritySearchRecord.created_at < created,
                    and_(
                        ItemDbSimilaritySearchRecord.created_at == created,
                        ItemDbSimilaritySearchRecord.search_id > identity,
                    ),
                )
            )
        with self.sessions.begin() as session:
            rows = tuple(
                session.scalars(
                    select(ItemDbSimilaritySearchRecord)
                    .where(*conditions)
                    .order_by(
                        ItemDbSimilaritySearchRecord.created_at.desc(),
                        ItemDbSimilaritySearchRecord.search_id,
                    )
                    .limit(limit + 1)
                )
            )
            more = len(rows) > limit
            values = tuple(_snapshot(row) for row in rows[:limit])
        return PageResult(
            values,
            self.cursors.encode(scope, values[-1].created_at, values[-1].search_id)
            if more
            else None,
            more,
        )
