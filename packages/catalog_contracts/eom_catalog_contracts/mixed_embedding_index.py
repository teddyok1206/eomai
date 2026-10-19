"""Additive registered-review bindings and mixed indices, never source authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    MAX_EMBEDDING_ROWS,
    SHARD_SCHEMA_REF,
    EmbeddingEncodingIdentity,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingSpace,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
    StoragePartition,
    parse_embedding_binding,
    parse_embedding_index,
    validate_embedding_index_layout,
    validate_embedding_index_reference_layout,
    validate_embedding_manifest_pointer,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    ExperimentMetadataField,
    ExperimentView,
    ExperimentViewRecipe,
    StagedExperimentEntry,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import (
    REGISTERED_REVIEW_EXTRACTOR_VERSION,
    RegisteredReviewProfile,
    RegisteredReviewProfilePointer,
    registered_review_profile_text,
)

MIXED_EMBEDDING_SCHEMA = "mixed-embedding-index-v2"
REGISTERED_REVIEW_BINDING_SCHEMA_REF = "eom://schemas/knowledge/embedding-source-binding/2.0"
MIXED_EMBEDDING_INDEX_SCHEMA_REF = "eom://schemas/knowledge/embedding-index-manifest/2.0"
MIXED_EMBEDDING_PROJECTION_VERSION = "mixed-solution-comparison/2.0"
MAX_MIXED_METADATA_BYTES = 64 * 1024**2


class _MixedEmbeddingContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_raw_contract(cls, value: object) -> object:
        return similarity_contract_document(value, MIXED_EMBEDDING_SCHEMA, MAX_MIXED_METADATA_BYTES)


class RegisteredReviewEmbeddingEntry(_MixedEmbeddingContract):
    """Bounded source-plan materialization, not an independent stored artifact."""

    profile: RegisteredReviewProfile
    content: CanonicalExperimentItemText | None
    metadata: tuple[ExperimentMetadataField, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def exact_original_source(self) -> RegisteredReviewEmbeddingEntry:
        source = self.profile.source_basis.source.artifact_member
        if self.content is not None and self.content.original_source != source:
            raise ValueError("registered-review question text source differs")
        keys = tuple((value.key, value.value, value.basis) for value in self.metadata)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("registered-review metadata must be sorted and unique")
        if any(
            value.basis != "ORIGINAL_ITEM" or value.source_sha256 != source.sha256
            for value in self.metadata
        ):
            raise ValueError("registered-review metadata must cite its exact original Item")
        return self


def registered_review_embedding_text(
    entry: RegisteredReviewEmbeddingEntry, view: ExperimentView
) -> str | None:
    """Original conclusions rather than fabricated facets; no internal IDs as features."""
    if view == "CONTENT_ONLY":
        return None if entry.content is None else entry.content.text
    if view == "CONCRETE_FACETS":
        return registered_review_profile_text(entry.profile)
    if view == "METADATA_ONLY":
        return "\n".join(f"{value.key}: {value.value}" for value in entry.metadata)
    raise ValueError("INFERENCE_EXPERIMENT_VIEW_INVALID")


def _exact_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("mixed embedding canonical content hash differs")


class RegisteredReviewEmbeddingSourceBinding(_MixedEmbeddingContract):
    """Real accepted V2 Graph base plus a separately verified registered REVIEW."""

    schema_version: Literal["embedding-source-binding/2.0"] = "embedding-source-binding/2.0"
    source: ApprovedItemKnowledgeSourceV2
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: RegisteredReviewProfilePointer
    review_evidence: RegisteredItemReviewSolutionEvidence
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    recipe: ExperimentViewRecipe
    view: ExperimentView
    projection_version: Literal["registered-item-review-comparison/1.0"] = (
        "registered-item-review-comparison/1.0"
    )
    encoding: EmbeddingEncodingIdentity
    row_ref: EmbeddingVectorRowRef
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_review_source_binding(self) -> RegisteredReviewEmbeddingSourceBinding:
        if (
            self.source != self.review_evidence.source
            or self.source.source_class != "APPROVED_ITEM"
            or self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.row_ref.encoding_sha256 != self.encoding.encoding_sha256
        ):
            raise ValueError("registered-review source, Graph or encoding binding differs")
        _exact_hash(self, "binding_sha256")
        return self


type MixedEmbeddingSourceBinding = Annotated[
    EmbeddingSourceBinding | RegisteredReviewEmbeddingSourceBinding,
    Field(discriminator="schema_version"),
]
type SupportedEmbeddingEntry = StagedExperimentEntry | RegisteredReviewEmbeddingEntry


class MixedEmbeddingIndexManifest(_MixedEmbeddingContract):
    """Ordered old/new associations; shard1 and numerical space remain unchanged."""

    schema_version: Literal["embedding-index-manifest/2.0"] = "embedding-index-manifest/2.0"
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    previous_manifest: ArtifactMemberPointer | None
    storage_partition: StoragePartition
    space: EmbeddingSpace
    view: ExperimentView
    recipe: ExperimentViewRecipe
    shards: tuple[ArtifactMemberPointer, ...] = Field(min_length=1, max_length=1024)
    bindings: tuple[MixedEmbeddingSourceBinding, ...] = Field(min_length=1, max_length=1024)
    created_at: UtcDatetime
    index_sha256: Sha256

    @model_validator(mode="after")
    def exact_mixed_index(self) -> MixedEmbeddingIndexManifest:
        validate_embedding_index_layout(
            previous_manifest=self.previous_manifest,
            previous_schema_refs=(INDEX_SCHEMA_REF, MIXED_EMBEDDING_INDEX_SCHEMA_REF),
            storage_partition=self.storage_partition,
            space=self.space,
            view=self.view,
            recipe=self.recipe,
            shards=self.shards,
            bindings=self.bindings,
        )
        _exact_hash(self, "index_sha256")
        return self


def validate_registered_review_embedding_binding(
    binding: RegisteredReviewEmbeddingSourceBinding,
    entry: RegisteredReviewEmbeddingEntry,
    shard_pointer: ArtifactMemberPointer,
    shard: EmbeddingVectorShardManifest,
) -> None:
    """Pure association/row closure; Graph/IAM/accepted-base checks stay with owner."""
    binding = RegisteredReviewEmbeddingSourceBinding.model_validate(
        raw_similarity_contract_value(binding)
    )
    entry = RegisteredReviewEmbeddingEntry.model_validate(raw_similarity_contract_value(entry))
    shard = EmbeddingVectorShardManifest.model_validate(raw_similarity_contract_value(shard))
    shard_pointer = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(shard_pointer)
    )
    validate_embedding_manifest_pointer(shard_pointer, SHARD_SCHEMA_REF, "shard.json")
    _validate_registered_review_binding_row(
        binding, entry, shard_pointer, shard, content_sha256(shard.model_dump(mode="json"))
    )


def _validate_registered_review_binding_row(
    binding: RegisteredReviewEmbeddingSourceBinding,
    entry: RegisteredReviewEmbeddingEntry,
    shard_pointer: ArtifactMemberPointer,
    shard: EmbeddingVectorShardManifest,
    shard_member_sha256: str,
) -> None:
    text = registered_review_embedding_text(entry, binding.view)
    basis = entry.profile.source_basis
    index = binding.row_ref.row_index
    if (
        binding.source != basis.source
        or binding.profile != RegisteredReviewProfilePointer.from_profile(entry.profile)
        or binding.review_evidence != basis.review_evidence
        or binding.graph_snapshot != basis.graph_snapshot
        or binding.projection_version != REGISTERED_REVIEW_EXTRACTOR_VERSION
        or binding.encoding.space_sha256 != shard.space.space_sha256
        or binding.row_ref.shard_manifest != shard_pointer
        or shard_pointer.sha256 != shard_member_sha256
        or index >= len(shard.rows)
        or shard.rows[index] != binding.encoding
        or text is None
        or not text.strip()
        or binding.encoding.input_text_sha256 != content_sha256(text)
    ):
        raise ValueError("registered-review binding differs from exact materialized source/row")


def parse_supported_embedding_entry(value: object) -> SupportedEmbeddingEntry:
    """Explicit profile-family dispatch; a forged/unknown version has no fallback."""
    raw = raw_similarity_contract_value(value)
    if not isinstance(raw, dict) or not isinstance(raw.get("profile"), dict):
        raise ValueError("embedding entry requires its exact profile")
    version = raw["profile"].get("schema_version")
    if version == "item-inference-transfer-profile/1.0":
        return StagedExperimentEntry.model_validate(raw)
    if version == "item-inference-transfer-profile/2.0":
        return RegisteredReviewEmbeddingEntry.model_validate(raw)
    raise ValueError("unsupported embedding entry profile family")


def parse_supported_embedding_binding(value: object) -> MixedEmbeddingSourceBinding:
    raw = raw_similarity_contract_value(value)
    if not isinstance(raw, dict):
        raise ValueError("embedding binding requires an object")
    if raw.get("schema_version") == "embedding-source-binding/1.0":
        return parse_embedding_binding(raw)
    if raw.get("schema_version") == "embedding-source-binding/2.0":
        return RegisteredReviewEmbeddingSourceBinding.model_validate(raw)
    raise ValueError("unsupported embedding source binding family")


def parse_supported_embedding_index(
    value: object,
) -> EmbeddingIndexManifest | MixedEmbeddingIndexManifest:
    raw = raw_similarity_contract_value(value)
    if not isinstance(raw, dict):
        raise ValueError("embedding index requires an object")
    if raw.get("schema_version") == "embedding-index-manifest/1.0":
        return parse_embedding_index(raw)
    if raw.get("schema_version") == "embedding-index-manifest/2.0":
        return MixedEmbeddingIndexManifest.model_validate(raw)
    raise ValueError("unsupported embedding index family")


def validate_mixed_embedding_index_references(
    index: MixedEmbeddingIndexManifest,
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest]
    | None = None,
) -> None:
    checked = MixedEmbeddingIndexManifest.model_validate(raw_similarity_contract_value(index))
    parent = (
        None if previous is None else (previous[0], parse_supported_embedding_index(previous[1]))
    )
    if parent is not None:
        expected_schema = (
            MIXED_EMBEDDING_INDEX_SCHEMA_REF
            if isinstance(parent[1], MixedEmbeddingIndexManifest)
            else INDEX_SCHEMA_REF
        )
        validate_embedding_manifest_pointer(parent[0], expected_schema, "index.json")
    validate_embedding_index_reference_layout(checked, shards, parent)


def validate_mixed_embedding_source_bindings(
    bindings: tuple[MixedEmbeddingSourceBinding, ...],
    entries: tuple[SupportedEmbeddingEntry, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
) -> None:
    """Bounded exact old/new associations; unique shard parsing/hashing is O(bytes).

    Legacy closures continue through their authoritative validator. Shared shards
    are parsed once per family, never once per source. No accepted base/IAM proof
    is inferred from the presence of a typed binding.
    """
    if any(len(values) > MAX_EMBEDDING_ROWS for values in (bindings, entries, shards)):
        raise ValueError("embedding source-binding capture exceeds its row budget")
    by_source = {}
    for original in entries:
        entry = parse_supported_embedding_entry(original)
        revision = entry.profile.source_basis.source.item_revision_id
        if revision in by_source:
            raise ValueError("binding entries contain duplicate source revisions")
        by_source[revision] = entry
    keys = tuple(
        (p.artifact_id, p.artifact_revision_id, p.member_path, p.sha256) for p, _ in shards
    )
    if keys != tuple(sorted(set(keys))):
        raise ValueError("index shard pointers must be sorted and unique")
    checked_bindings = tuple(parse_supported_embedding_binding(value) for value in bindings)
    digests = {value.binding_sha256 for value in checked_bindings}
    needed = {value.row_ref.shard_manifest for value in checked_bindings}
    if len(digests) != len(bindings) or needed != {p for p, _ in shards}:
        raise ValueError("mixed bindings contain duplicate or inconsistent shard references")
    legacy = tuple(value for value in checked_bindings if isinstance(value, EmbeddingSourceBinding))
    legacy_pointers = {value.row_ref.shard_manifest for value in legacy}
    validate_embedding_source_bindings(
        legacy,
        tuple(value for value in by_source.values() if isinstance(value, StagedExperimentEntry)),
        tuple((p, shard) for p, shard in shards if p in legacy_pointers),
    )
    review_bindings = tuple(
        value
        for value in checked_bindings
        if isinstance(value, RegisteredReviewEmbeddingSourceBinding)
    )
    review_pointers = {value.row_ref.shard_manifest for value in review_bindings}
    reviewed_shards = {}
    for pointer, original_shard in shards:
        if pointer not in review_pointers:
            continue
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
        validate_embedding_manifest_pointer(pointer, SHARD_SCHEMA_REF, "shard.json")
        shard = EmbeddingVectorShardManifest.model_validate(
            raw_similarity_contract_value(original_shard)
        )
        reviewed_shards[pointer] = shard, content_sha256(shard.model_dump(mode="json"))
    for binding in review_bindings:
        selected = by_source.get(binding.source.item_revision_id)
        if not isinstance(selected, RegisteredReviewEmbeddingEntry):
            raise ValueError("registered-review binding requires its own exact profile family")
        shard, digest = reviewed_shards[binding.row_ref.shard_manifest]
        _validate_registered_review_binding_row(
            binding, selected, binding.row_ref.shard_manifest, shard, digest
        )
