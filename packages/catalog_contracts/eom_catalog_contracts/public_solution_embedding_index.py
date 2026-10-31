"""Successor public-solution associations over unchanged numeric vector shards."""

from typing import Any, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    EmbeddingVectorRowRef,
    StoragePartition,
    validate_embedding_index_layout,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import (
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding import (
    PUBLIC_SOLUTION_EMBEDDING_SCHEMA_REF,
    AcceptedPublicSolutionEvidence,
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingEvidence,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.validation import validate_contract

PUBLIC_SOLUTION_INDEX_SCHEMA = "public-solution-embedding-index-v3"
PUBLIC_SOLUTION_INDEX_SCHEMA_REF = "eom://schemas/knowledge/embedding-index-manifest/3.0"
PUBLIC_SOLUTION_BINDING_SCHEMA_REF = "eom://schemas/knowledge/embedding-source-binding/3.0"
MAX_PUBLIC_SOLUTION_SOURCES = 16384


def validate_public_solution_binding_identity(document: dict[str, Any]) -> None:
    """One identity rule AFTER binding3/4's distinct closed schema validation.

    This small JSON-mode view is internal validation, not a cross-service payload
    or authority. It preserves the historical canonical binding hash exactly.
    """
    logical = content_sha256(
        {
            "item_id": document["source"]["item_id"],
            "projection_version": document["projection_version"],
        }
    )
    profile, graph = document["profile"], document["graph_snapshot"]
    if (
        graph["manifest_sha256"] != graph["manifest_artifact"]["sha256"]
        or document["encoding"]["encoding_sha256"] != document["row_ref"]["encoding_sha256"]
        or profile["profile_id"] != "inferenceprofile_" + logical[7:39]
        or profile["profile_revision_id"]
        != "inferenceprofilerev_" + profile["profile_sha256"][7:39]
        or document["binding_sha256"]
        != content_sha256(
            {key: value for key, value in document.items() if key != "binding_sha256"}
        )
    ):
        raise ValueError("PUBLIC_SOLUTION_BINDING_MISMATCH")


class PublicSolutionProfilePointer(FrozenModel):
    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    profile_sha256: Sha256
    schema_ref: Literal["eom://schemas/knowledge/public-solution-embedding-entry/1.0"] = (
        PUBLIC_SOLUTION_EMBEDDING_SCHEMA_REF
    )

    @classmethod
    def from_entry(cls, entry: PublicSolutionEmbeddingEntry) -> Self:
        entry = PublicSolutionEmbeddingEntry.model_validate(entry.model_dump(mode="json"))
        logical = content_sha256(
            {"item_id": entry.source.item_id, "projection_version": "public-solution-text/1.0"}
        )
        return cls(
            profile_id="inferenceprofile_" + logical[7:39],
            profile_revision_id="inferenceprofilerev_" + entry.entry_sha256[7:39],
            profile_sha256=entry.entry_sha256,
        )


class PublicSolutionIndexNamespace(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    storage_partition: StoragePartition
    space_sha256: Sha256
    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    recipe_sha256: Sha256
    projection_version: Literal["public-solution-text/1.0"] = "public-solution-text/1.0"
    population_scope: Literal["ALL_ADMITTED_GRAPH_ITEMS"] = "ALL_ADMITTED_GRAPH_ITEMS"

    def accepts_projection(self, projection_version: str) -> bool:
        return projection_version == self.projection_version


class _PublicSolutionIndexValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        value = raw_similarity_contract_value(value)
        if not isinstance(value, dict) or len(canonical_json_bytes(value)) > 64 * 1024**2:
            raise ValueError("PUBLIC_SOLUTION_INDEX_METADATA_INVALID")
        validate_contract(PUBLIC_SOLUTION_INDEX_SCHEMA, value)
        return value


class PublicSolutionEmbeddingSourceBinding(_PublicSolutionIndexValue):
    schema_version: Literal["embedding-source-binding/3.0"] = "embedding-source-binding/3.0"
    source: PopulationSource
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: PublicSolutionProfilePointer
    evidence: PublicSolutionEmbeddingEvidence
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    recipe: PublicSolutionEmbeddingRecipe
    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    projection_version: Literal["public-solution-text/1.0"] = "public-solution-text/1.0"
    encoding: EmbeddingEncodingIdentity
    row_ref: EmbeddingVectorRowRef
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_binding(self) -> Self:
        validate_public_solution_binding_identity(self.model_dump(mode="json"))
        if isinstance(self.evidence, AcceptedPublicSolutionEvidence):
            if self.base_analysis_run_id != self.evidence.solution.base_analysis_run_id:
                raise ValueError("PUBLIC_SOLUTION_BASE_ANALYSIS_MISMATCH")
        elif self.source.source_class != "APPROVED_ITEM":
            raise ValueError("PUBLIC_SOLUTION_CREATIVE_SOURCE_CLASS_INVALID")
        return self


class PublicSolutionEmbeddingIndex(_PublicSolutionIndexValue):
    schema_version: Literal["embedding-index-manifest/3.0"] = "embedding-index-manifest/3.0"
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    previous_manifest: ArtifactMemberPointer | None
    storage_partition: StoragePartition
    space: EmbeddingSpace
    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    recipe: PublicSolutionEmbeddingRecipe
    shards: tuple[ArtifactMemberPointer, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    bindings: tuple[PublicSolutionEmbeddingSourceBinding, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    created_at: UtcDatetime
    index_sha256: Sha256

    @model_validator(mode="after")
    def exact_index(self) -> Self:
        validate_embedding_index_layout(
            previous_manifest=self.previous_manifest,
            previous_schema_refs=(PUBLIC_SOLUTION_INDEX_SCHEMA_REF,),
            storage_partition=self.storage_partition,
            space=self.space,
            view=self.view,
            recipe=self.recipe,
            shards=self.shards,
            bindings=self.bindings,
        )
        if self.index_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"index_sha256"})
        ):
            raise ValueError("PUBLIC_SOLUTION_INDEX_HASH_MISMATCH")
        return self
