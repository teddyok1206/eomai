"""DB search presentation; exact source selection and numerical context remain canonical."""

from datetime import datetime
from typing import Literal, Self

from eom_catalog_contracts.item_db_similarity_selection import ItemDbSimilaritySelection
from eom_catalog_contracts.item_db_similarity_selection_v2 import (
    validate_item_db_selection_list,
)
from eom_catalog_contracts.reference_query_prepare import (
    PublicRoutedReferenceQueryChild,
    ReferenceQueryPrepareRequestV4,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field, ModelWrapValidatorHandler, model_validator

from eom_api_contracts.common import ApiModel
from eom_api_contracts.item_bank import ProductionItemCandidateViewContract


class ItemDbSimilarityInput(ApiModel):
    schema_version: Literal["item-db-similarity-input/1.0"] = "item-db-similarity-input/1.0"
    selection: ItemDbSimilaritySelection
    top_k: int = Field(default=5, strict=True, ge=1, le=64)
    pinned_query: ReferenceQueryPrepareRequestV4 | None = None

    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        try:
            return handler(value)
        except SchemaError:
            raise ValueError("invalid exact DB similarity input") from None


class ItemDbSimilarityCandidate(ApiModel):
    kind: Literal["GRAPH_ITEM"] = "GRAPH_ITEM"
    entry: ProductionItemCandidateViewContract
    label: str = Field(min_length=1, max_length=512)
    unit_label: str = Field(max_length=512)
    cosine_millionths: int = Field(strict=True, ge=-1_000_000, le=1_000_000)


class ItemDbSimilarityView(ApiModel):
    schema_version: Literal["item-db-similarity-view/1.0"] = "item-db-similarity-view/1.0"
    status: Literal["READY", "PARTIAL", "PENDING", "UNAVAILABLE", "FAILED"]
    phase: Literal["PREPARING", "WAITING_FOR_RESOURCE", "COMPUTING", "READING_RESULTS"]
    candidates: tuple[ItemDbSimilarityCandidate, ...] = Field(max_length=64)
    pinned_query: ReferenceQueryPrepareRequestV4 | None
    search_snapshot_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    message: str = Field(max_length=1000)
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{1,127}$")

    @model_validator(mode="after")
    def coherent_state(self) -> Self:
        ready = self.status in {"READY", "PARTIAL"}
        if (
            (not ready and self.candidates)
            or ((self.status in {"UNAVAILABLE", "FAILED"}) != (self.error_code is not None))
            or (
                self.status in {"PENDING", "READY", "PARTIAL"}
                and (self.pinned_query is None or self.search_snapshot_sha256 is None)
            )
        ):
            raise ValueError("DB similarity state and its pointers differ")
        revisions = {candidate.entry.item_revision_id for candidate in self.candidates}
        if len(revisions) != len(self.candidates) or (
            self.pinned_query is not None
            and revisions.intersection(self.pinned_query.source_item_revision_ids)
        ):
            raise ValueError("DB similarity repeats a candidate or its anchor")
        return self


class ItemDbSimilarityListInput(ApiModel):
    schema_version: Literal["item-db-similarity-list-input/1.0"] = (
        "item-db-similarity-list-input/1.0"
    )
    selections: tuple[ItemDbSimilaritySelection, ...] = Field(min_length=1, max_length=32)
    top_k: int = Field(default=5, strict=True, ge=1, le=64)

    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except SchemaError:
            raise ValueError("invalid DB similarity list input") from None

    @model_validator(mode="after")
    def unique_inputs(self) -> Self:
        # Reuse the list rule instead of creating a weaker HTTP-only variant.
        validate_item_db_selection_list(self.selections)
        return self


class ItemDbSimilaritySearchView(ApiModel):
    schema_version: Literal["item-db-similarity-search-view/1.0"] = (
        "item-db-similarity-search-view/1.0"
    )
    search_id: str = Field(pattern=r"^dbsearch_[0-9a-f]{32}$")
    created_at: datetime
    selections: tuple[ItemDbSimilaritySelection, ...] = Field(min_length=1, max_length=32)
    top_k: int = Field(strict=True, ge=1, le=64)
    status: Literal["PREPARING", "PENDING", "READY", "FAILED", "UNAVAILABLE"]
    device: Literal["CPU", "CUDA"] | None
    children: tuple[PublicRoutedReferenceQueryChild, ...] = Field(max_length=32)
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{1,127}$")

    @model_validator(mode="after")
    def ordered_children(self) -> Self:
        if tuple(child.ordinal for child in self.children) != tuple(range(len(self.children))):
            raise ValueError("search child order differs")
        if self.children and len(self.children) != len(self.selections):
            raise ValueError("search child count differs")
        if self.status == "READY" and (
            not self.children or any(child.selection is None for child in self.children)
        ):
            raise ValueError("completed search lacks immutable selectors")
        return self


class ItemDbSimilarityAnchorResult(ApiModel):
    schema_version: Literal["item-db-similarity-anchor-result/1.0"] = (
        "item-db-similarity-anchor-result/1.0"
    )
    search_id: str = Field(pattern=r"^dbsearch_[0-9a-f]{32}$")
    ordinal: int = Field(strict=True, ge=0, le=31)
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    status: Literal["READY", "PARTIAL"]
    candidates: tuple[ItemDbSimilarityCandidate, ...] = Field(max_length=64)
    message: str = Field(max_length=1000)

    @model_validator(mode="after")
    def distinct_candidates(self) -> Self:
        revisions = {candidate.entry.item_revision_id for candidate in self.candidates}
        if len(revisions) != len(self.candidates) or self.source_item_revision_id in revisions:
            raise ValueError("result repeats a candidate or its own anchor")
        return self
