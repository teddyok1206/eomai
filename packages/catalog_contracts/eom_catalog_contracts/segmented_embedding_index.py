"""A bounded immutable root for larger embedding populations, never source authority.

The root is a successor contract only. Existing V1/V2 index readers and the selected
INDEX/QUERY services do not interpret it until a Catalog publication/read use case
validates every segment and the complete authorized population.
"""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingSpace,
    StoragePartition,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, ExperimentViewRecipe
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_index import MIXED_EMBEDDING_INDEX_SCHEMA_REF
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

SEGMENTED_EMBEDDING_INDEX_SCHEMA = "segmented-embedding-index-v1"
SEGMENTED_EMBEDDING_INDEX_SCHEMA_REF = "eom://schemas/knowledge/segmented-embedding-index/1.0"
MAX_SEGMENTS = 1024
MAX_SEGMENT_BINDINGS = 1024
MAX_SEGMENTED_BINDINGS = MAX_SEGMENTS * MAX_SEGMENT_BINDINGS


class SegmentedEmbeddingIndexSegment(FrozenModel):
    """One ordered range; the pointed manifest is resolved by Catalog, not here."""

    index_manifest: ArtifactMemberPointer
    first_source_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    last_source_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    binding_count: int = Field(strict=True, ge=1, le=MAX_SEGMENT_BINDINGS)
    target_set_sha256: Sha256

    @model_validator(mode="after")
    def exact_range(self) -> SegmentedEmbeddingIndexSegment:
        member = ArtifactMemberPointer.model_validate(
            raw_similarity_contract_value(self.index_manifest)
        )
        if (
            member.member_path != "index.json"
            or member.media_type != "application/json"
            or member.schema_ref not in {INDEX_SCHEMA_REF, MIXED_EMBEDDING_INDEX_SCHEMA_REF}
            or self.first_source_revision_id > self.last_source_revision_id
        ):
            raise ValueError("segmented index member or source range differs")
        return self


class SegmentedEmbeddingIndexRoot(FrozenModel):
    """Self-hashed ordered segment set; actual coverage requires trusted source reads."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["segmented-embedding-index/1.0"] = "segmented-embedding-index/1.0"
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    previous_root: ArtifactMemberPointer | None
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    storage_partition: StoragePartition
    space: EmbeddingSpace
    view: ExperimentView
    recipe: ExperimentViewRecipe
    segments: tuple[SegmentedEmbeddingIndexSegment, ...] = Field(
        min_length=2, max_length=MAX_SEGMENTS
    )
    binding_count: int = Field(strict=True, ge=MAX_SEGMENT_BINDINGS + 1, le=MAX_SEGMENTED_BINDINGS)
    target_set_sha256: Sha256
    created_at: UtcDatetime
    root_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(value, SEGMENTED_EMBEDDING_INDEX_SCHEMA, 4 * 1024**2)

    @model_validator(mode="after")
    def exact_segments(self) -> SegmentedEmbeddingIndexRoot:
        if self.previous_root is not None:
            previous = ArtifactMemberPointer.model_validate(
                raw_similarity_contract_value(self.previous_root)
            )
            if (
                previous.member_path != "root.json"
                or previous.media_type != "application/json"
                or previous.schema_ref != SEGMENTED_EMBEDDING_INDEX_SCHEMA_REF
            ):
                raise ValueError("segmented index predecessor pointer differs")
        if self.space.purpose != "DOCUMENT":
            raise ValueError("segmented index namespace differs")
        if sum(segment.binding_count for segment in self.segments) != self.binding_count:
            raise ValueError("segmented index binding count differs")
        if any(
            left.last_source_revision_id >= right.first_source_revision_id
            for left, right in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("segmented index ranges overlap or are unordered")
        pointers = tuple(segment.index_manifest for segment in self.segments)
        if len(set(pointers)) != len(pointers):
            raise ValueError("segmented index reuses an index member")
        descriptors = [
            {
                "first_source_revision_id": segment.first_source_revision_id,
                "last_source_revision_id": segment.last_source_revision_id,
                "binding_count": segment.binding_count,
                "target_set_sha256": segment.target_set_sha256,
            }
            for segment in self.segments
        ]
        if self.target_set_sha256 != content_sha256(descriptors):
            raise ValueError("segmented index target descriptor hash differs")
        if self.root_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"root_sha256"})
        ):
            raise ValueError("segmented index root hash differs")
        return self
