"""DB search presentation; exact source selection and numerical context remain canonical."""

from typing import Literal, Self

from eom_catalog_contracts.item_db_similarity_selection import ItemDbSimilaritySelection
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
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
