"""Small immutable search metadata and monotonic child observation rules."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_api_contracts.item_db_similarity import (
    ItemDbSimilarityListInput,
    ItemDbSimilaritySearchView,
)
from eom_catalog_contracts.reference_query_prepare import (
    PublicRoutedReferenceQueryChild,
    ReferenceQueryPrepareRequestV4,
)
from eom_identifiers import content_sha256


def item_db_search_operation_id(operator_id: str, key: str) -> str:
    return (
        "queryprepare_"
        + content_sha256(
            {
                "purpose": "ITEM_DATABASE_LIST_SEARCH/1.0",
                "owner": operator_id,
                "key": key,
            }
        )[7:39]
    )


@dataclass(frozen=True, slots=True)
class ItemDbSimilaritySearchSnapshot:
    search_id: str
    operator_id: str
    idempotency_key: str
    intent_sha256: str
    input: ItemDbSimilarityListInput
    query: ReferenceQueryPrepareRequestV4 | None
    children: tuple[PublicRoutedReferenceQueryChild, ...]
    state: Literal["PREPARING", "PENDING", "READY", "FAILED", "UNAVAILABLE"]
    device: Literal["CPU", "CUDA"] | None
    error_code: str | None
    created_at: datetime

    def view(self) -> ItemDbSimilaritySearchView:
        return ItemDbSimilaritySearchView(
            search_id=self.search_id,
            created_at=self.created_at,
            selections=self.input.selections,
            top_k=self.input.top_k,
            status=self.state,
            device=self.device,
            children=self.children,
            error_code=self.error_code,
        )


def merge_item_db_search_children(
    current: tuple[PublicRoutedReferenceQueryChild, ...],
    observed: tuple[PublicRoutedReferenceQueryChild, ...],
    query: ReferenceQueryPrepareRequestV4,
) -> tuple[PublicRoutedReferenceQueryChild, ...]:
    """Late PENDING reads cannot erase an already linked completion or failed history."""
    if not observed:
        return current
    if (
        len(observed) != len(query.source_item_revision_ids)
        or tuple(child.ordinal for child in observed) != tuple(range(len(observed)))
        or tuple(child.source_item_revision_id for child in observed)
        != query.source_item_revision_ids
        or (current and len(current) != len(observed))
    ):
        raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
    if not current:
        return observed
    merged = []
    for old, new in zip(current, observed, strict=True):
        if old.workflow_id is not None and new.workflow_id not in {None, old.workflow_id}:
            raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
        if old.state in {"COMPLETED", "FAILED"}:
            if new.state != "PENDING" and new != old:
                raise ValueError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
            merged.append(old)
        elif old.workflow_id is not None and new.workflow_id is None:
            merged.append(old)
        else:
            merged.append(new)
    return tuple(merged)
