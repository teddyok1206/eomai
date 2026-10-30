"""Small DB selection pointers; Catalog resolves them before the existing QUERY owner."""

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4

MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES = 64 * 1024
type ItemDbSimilaritySelectionErrorCode = Literal[
    "SOURCE_ACCESS_DENIED",
    "SOURCE_REVOKED",
    "SOURCE_POINTER_INVALID",
    "SOURCE_HASH_MISMATCH",
    "INDEX_POINTER_INVALID",
    "INDEX_HASH_MISMATCH",
    "QUERY_RESULT_INVALID",
    "AUTHORITY_UNAVAILABLE",
    "ITEM_DB_SIMILARITY_UNAVAILABLE",
    "ITEM_DB_SIMILARITY_REQUEST_INVALID",
    "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
    "ITEM_DB_SIMILARITY_NOT_REGISTERED",
    "ITEM_DB_SIMILARITY_NOT_INDEXED",
]


class _SelectionValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            "item-db-similarity-selection-v1",
            MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES - 1,
        )


class ItemDbGraphSelection(_SelectionValue):
    kind: Literal["GRAPH_ITEM"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256


class ItemDbExternalSelection(_SelectionValue):
    kind: Literal["EXTERNAL_SOURCE"]
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: Sha256


type ItemDbSimilaritySelection = Annotated[
    ItemDbGraphSelection | ItemDbExternalSelection,
    Field(discriminator="kind"),
]


class ItemDbSimilarityItemPin(_SelectionValue):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256


class ItemDbSimilaritySelectionRequest(_SelectionValue):
    schema_version: Literal["item-db-similarity-selection-request/1.0"]
    operation: Literal["RESOLVE_ITEM_DB_SIMILARITY"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    selection: ItemDbSimilaritySelection
    top_k: int = Field(strict=True, ge=1, le=64)
    pinned_query: ReferenceQueryPrepareRequestV4 | None

    @model_validator(mode="after")
    def exact_replay(self) -> Self:
        query = self.pinned_query
        if query is not None and (
            query.operation_id != self.operation_id
            or query.idempotency_key != self.idempotency_key
            or query.consumer_purpose != "ITEM_DATABASE_SEARCH"
            or query.top_k != self.top_k
            or len(query.source_item_revision_ids) != 1
            or (
                isinstance(self.selection, ItemDbGraphSelection)
                and query.source_item_revision_ids != (self.selection.item_revision_id,)
            )
        ):
            raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
        return self


class ItemDbSimilarityPreparedSelection(_SelectionValue):
    selection_sha256: Sha256
    anchor: ItemDbSimilarityItemPin
    query: ReferenceQueryPrepareRequestV4
    search_snapshot_sha256: Sha256

    @model_validator(mode="after")
    def exact_anchor(self) -> Self:
        if self.query.consumer_purpose != "ITEM_DATABASE_SEARCH" or (
            self.query.source_item_revision_ids != (self.anchor.item_revision_id,)
        ):
            raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
        return self


class ItemDbSimilaritySelectionReply(_SelectionValue):
    schema_version: Literal["item-db-similarity-selection-reply/1.0"]
    operation: Literal["RESOLVE_ITEM_DB_SIMILARITY"]
    status: Literal["READY", "UNAVAILABLE", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: ItemDbSimilarityPreparedSelection | None
    error_code: ItemDbSimilaritySelectionErrorCode | None


def validate_item_db_similarity_selection_reply(
    request: ItemDbSimilaritySelectionRequest,
    reply: ItemDbSimilaritySelectionReply,
) -> None:
    request = ItemDbSimilaritySelectionRequest.model_validate(request)
    reply = ItemDbSimilaritySelectionReply.model_validate(reply)
    if reply.actor_id != request.actor_id or reply.request_sha256 != content_sha256(request):
        raise ValueError("ITEM_DB_SIMILARITY_REPLY_MISMATCH")
    result = reply.result
    if result is None:
        return
    selected = request.selection
    if (
        result.selection_sha256 != content_sha256(selected)
        or result.query.operation_id != request.operation_id
        or result.query.idempotency_key != request.idempotency_key
        or result.query.top_k != request.top_k
        or (request.pinned_query is not None and result.query != request.pinned_query)
        or (
            isinstance(selected, ItemDbGraphSelection)
            and (
                result.anchor.item_id != selected.item_id
                or result.anchor.item_revision_id != selected.item_revision_id
                or result.anchor.item_manifest_sha256 != selected.item_manifest_sha256
            )
        )
    ):
        raise ValueError("ITEM_DB_SIMILARITY_REPLY_MISMATCH")
