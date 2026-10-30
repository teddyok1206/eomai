"""Small BFF projection; API owns QUERY/schema/source rules and reauthorizes every replay."""

import json
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from eom_web_gui.contracts import GraphItemDbEntry, WebModel


class GraphSelection(WebModel):
    kind: Literal["GRAPH_ITEM"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ExternalSelection(WebModel):
    kind: Literal["EXTERNAL_SOURCE"]
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


# This is a bounded opaque metadata echo, not locally interpreted QUERY authority.
# Keeping API-owned complex controls opaque preserves independent Web packaging.
type QueryPin = Annotated[dict[str, JsonValue], Field(max_length=16)]


def _bounded_query(value: QueryPin | None) -> QueryPin | None:
    if value is not None and (
        value.get("schema_version") != "system-rag-reference-query-prepare-request/4.0"
        or len(json.dumps(value, ensure_ascii=True).encode()) > 60 * 1024
    ):
        raise ValueError("invalid bounded public query metadata")
    return value


class ItemDbSimilaritySubmission(WebModel):
    selection: Annotated[GraphSelection | ExternalSelection, Field(discriminator="kind")]
    pinned_query: QueryPin | None = None
    top_k: int = Field(default=5, strict=True, ge=1, le=64)

    _query = field_validator("pinned_query")(_bounded_query)


class ItemDbSimilarityCandidate(WebModel):
    kind: Literal["GRAPH_ITEM"]
    entry: GraphItemDbEntry
    label: str = Field(min_length=1, max_length=512)
    unit_label: str = Field(max_length=512)
    cosine_millionths: int = Field(strict=True, ge=-1_000_000, le=1_000_000)


class ItemDbSimilarityResult(WebModel):
    schema_version: Literal["item-db-similarity-view/1.0"]
    status: Literal["READY", "PARTIAL", "PENDING", "UNAVAILABLE", "FAILED"]
    phase: Literal["PREPARING", "WAITING_FOR_RESOURCE", "COMPUTING", "READING_RESULTS"]
    candidates: tuple[ItemDbSimilarityCandidate, ...] = Field(max_length=64)
    pinned_query: QueryPin | None
    search_snapshot_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    message: str = Field(max_length=1000)
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{1,127}$")

    _query = field_validator("pinned_query")(_bounded_query)

    @model_validator(mode="after")
    def safe_presentation(self) -> Self:
        revisions = {candidate.entry.item_revision_id for candidate in self.candidates}
        if len(revisions) != len(self.candidates) or (
            self.status not in {"READY", "PARTIAL"} and self.candidates
        ):
            raise ValueError("invalid search result presentation")
        return self
