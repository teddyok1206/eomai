"""Ordered DB inputs for one existing finite QUERY; never an execution grant."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
    ItemDbGraphSelection,
    ItemDbSimilarityItemPin,
    ItemDbSimilaritySelection,
    ItemDbSimilaritySelectionErrorCode,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4


class _ListSelectionValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "item-db-similarity-selection-v2", MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES - 1
        )


def validate_item_db_selection_list(selections: tuple[ItemDbSimilaritySelection, ...]) -> None:
    """Pure input membership rule, not a fabricated actor or source-resolution grant."""
    identities = {
        ("GRAPH_ITEM", value.item_revision_id)
        if isinstance(value, ItemDbGraphSelection)
        else ("EXTERNAL_SOURCE", value.source_id, value.source_revision_id)
        for value in selections
    }
    if not 1 <= len(selections) <= 32 or len(identities) != len(selections):
        raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")


class ItemDbSimilaritySelectionRequestV2(_ListSelectionValue):
    schema_version: Literal["item-db-similarity-selection-request/2.0"]
    operation: Literal["RESOLVE_ITEM_DB_SIMILARITY_LIST"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    selections: tuple[ItemDbSimilaritySelection, ...] = Field(min_length=1, max_length=32)
    top_k: int = Field(strict=True, ge=1, le=64)
    pinned_query: ReferenceQueryPrepareRequestV4 | None

    @model_validator(mode="after")
    def exact_list(self) -> Self:
        validate_item_db_selection_list(self.selections)
        query = self.pinned_query
        if query is not None and (
            query.operation_id != self.operation_id
            or query.idempotency_key != self.idempotency_key
            or query.consumer_purpose != "ITEM_DATABASE_SEARCH"
            or query.top_k != self.top_k
            or len(query.source_item_revision_ids) != len(self.selections)
            or any(
                isinstance(value, ItemDbGraphSelection)
                and value.item_revision_id != query.source_item_revision_ids[ordinal]
                for ordinal, value in enumerate(self.selections)
            )
        ):
            raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
        return self


class ItemDbSimilarityPreparedSelectionV2(_ListSelectionValue):
    selection_sha256: Sha256
    anchors: tuple[ItemDbSimilarityItemPin, ...] = Field(min_length=1, max_length=32)
    query: ReferenceQueryPrepareRequestV4
    search_snapshot_sha256: Sha256

    @model_validator(mode="after")
    def exact_anchors(self) -> Self:
        if self.query.consumer_purpose != "ITEM_DATABASE_SEARCH" or (
            self.query.source_item_revision_ids
            != tuple(anchor.item_revision_id for anchor in self.anchors)
        ):
            raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
        return self


class ItemDbSimilaritySelectionReplyV2(_ListSelectionValue):
    schema_version: Literal["item-db-similarity-selection-reply/2.0"]
    operation: Literal["RESOLVE_ITEM_DB_SIMILARITY_LIST"]
    status: Literal["READY", "UNAVAILABLE", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: ItemDbSimilarityPreparedSelectionV2 | None
    error_code: ItemDbSimilaritySelectionErrorCode | None


def validate_item_db_similarity_selection_reply_v2(
    request: ItemDbSimilaritySelectionRequestV2, reply: ItemDbSimilaritySelectionReplyV2
) -> None:
    request = ItemDbSimilaritySelectionRequestV2.model_validate(request)
    reply = ItemDbSimilaritySelectionReplyV2.model_validate(reply)
    if reply.actor_id != request.actor_id or reply.request_sha256 != content_sha256(request):
        raise ValueError("ITEM_DB_SIMILARITY_REPLY_MISMATCH")
    result = reply.result
    if result is None:
        return
    if (
        result.selection_sha256 != content_sha256(request.selections)
        or len(result.anchors) != len(request.selections)
        or result.query.operation_id != request.operation_id
        or result.query.idempotency_key != request.idempotency_key
        or result.query.top_k != request.top_k
        or (request.pinned_query is not None and result.query != request.pinned_query)
        or any(
            isinstance(selected, ItemDbGraphSelection)
            and (
                selected.item_id != anchor.item_id
                or selected.item_revision_id != anchor.item_revision_id
                or selected.item_manifest_sha256 != anchor.item_manifest_sha256
            )
            for selected, anchor in zip(request.selections, result.anchors, strict=True)
        )
    ):
        raise ValueError("ITEM_DB_SIMILARITY_REPLY_MISMATCH")
