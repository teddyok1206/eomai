"""Index4 adds true registered report provenance, not a new numerical vector space."""

from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    EmbeddingVectorRowRef,
    StoragePartition,
    validate_embedding_index_layout,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingSourceBinding,
    validate_public_solution_binding_identity,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
    RegisteredPublicSolutionEvidence,
)
from eom_catalog_contracts.validation import validate_contract

REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA = "public-solution-embedding-index-v4"
REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF = "eom://schemas/knowledge/embedding-index-manifest/4.0"
REGISTERED_PUBLIC_SOLUTION_BINDING_SCHEMA_REF = (
    "eom://schemas/knowledge/embedding-source-binding/4.0"
)


class _RegisteredPublicIndexValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_public_solution_contract_value(value)
        if not isinstance(document, dict) or len(canonical_json_bytes(document)) > 64 * 1024**2:
            raise ValueError("REGISTERED_PUBLIC_INDEX_METADATA_INVALID")
        try:
            validate_contract(REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA, document)
        except JsonSchemaValidationError:
            raise ValueError("REGISTERED_PUBLIC_INDEX_SCHEMA_INVALID") from None
        return document


class RegisteredPublicSolutionProfilePointer(_RegisteredPublicIndexValue):
    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    profile_sha256: Sha256
    schema_ref: Literal["eom://schemas/knowledge/public-solution-embedding-entry/2.0"] = (
        "eom://schemas/knowledge/public-solution-embedding-entry/2.0"
    )

    @classmethod
    def from_entry(cls, entry: RegisteredPublicSolutionEmbeddingEntry) -> Self:
        entry = RegisteredPublicSolutionEmbeddingEntry.model_validate(entry)
        logical = content_sha256(
            {"item_id": entry.source.item_id, "projection_version": "public-solution-text/1.0"}
        )
        return cls(
            profile_id="inferenceprofile_" + logical[7:39],
            profile_revision_id="inferenceprofilerev_" + entry.entry_sha256[7:39],
            profile_sha256=entry.entry_sha256,
            schema_ref="eom://schemas/knowledge/public-solution-embedding-entry/2.0",
        )


class RegisteredPublicSolutionSourceBinding(_RegisteredPublicIndexValue):
    schema_version: Literal["embedding-source-binding/4.0"] = "embedding-source-binding/4.0"
    source: ApprovedItemKnowledgeSourceV2
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: RegisteredPublicSolutionProfilePointer
    evidence: RegisteredPublicSolutionEvidence
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
        document = self.model_dump(mode="json")
        validate_public_solution_binding_identity(document)
        evidence = RegisteredPublicSolutionEvidence.model_validate(document["evidence"])
        PublicSolutionEmbeddingRecipe.model_validate(document["recipe"])
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.base_analysis_run_id != evidence.solution.base_analysis_run_id
        ):
            raise ValueError("REGISTERED_PUBLIC_BINDING_SOURCE_MISMATCH")
        return self


type PublicSolutionBindingV4 = Annotated[
    PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding,
    Field(discriminator="schema_version"),
]


class PublicSolutionEmbeddingIndexV4(_RegisteredPublicIndexValue):
    schema_version: Literal["embedding-index-manifest/4.0"] = "embedding-index-manifest/4.0"
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
    bindings: tuple[PublicSolutionBindingV4, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    created_at: UtcDatetime
    index_sha256: Sha256

    @model_validator(mode="after")
    def exact_index(self) -> Self:
        validate_embedding_index_layout(
            previous_manifest=self.previous_manifest,
            previous_schema_refs=(
                PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
                REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
            ),
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
            raise ValueError("REGISTERED_PUBLIC_INDEX_HASH_MISMATCH")
        return self
