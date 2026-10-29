"""Closed version dispatch; predecessor parsers and schema bytes remain unchanged."""

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingVectorShardManifest,
    validate_embedding_index_reference_layout,
    validate_embedding_index_references,
    validate_embedding_manifest_pointer,
)
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingEntry,
    RegisteredReviewEmbeddingSourceBinding,
    validate_mixed_embedding_index_references,
    validate_mixed_embedding_source_bindings,
)
from eom_catalog_contracts.mixed_embedding_index import (
    parse_supported_embedding_binding as parse_legacy_binding,
)
from eom_catalog_contracts.mixed_embedding_index import (
    parse_supported_embedding_entry as parse_legacy_entry,
)
from eom_catalog_contracts.mixed_embedding_index import (
    parse_supported_embedding_index as parse_legacy_index,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionIndexNamespace,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer

type SupportedEmbeddingIndex = (
    EmbeddingIndexManifest | MixedEmbeddingIndexManifest | PublicSolutionEmbeddingIndex
)
type SupportedEmbeddingBinding = (
    EmbeddingSourceBinding
    | RegisteredReviewEmbeddingSourceBinding
    | PublicSolutionEmbeddingSourceBinding
)
type SupportedEmbeddingEntry = (
    StagedExperimentEntry | RegisteredReviewEmbeddingEntry | PublicSolutionEmbeddingEntry
)
type SupportedEmbeddingProfilePointer = (
    InferenceTransferProfilePointer | RegisteredReviewProfilePointer | PublicSolutionProfilePointer
)

type SupportedEmbeddingNamespace = (
    EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | PublicSolutionIndexNamespace
)


def parse_supported_embedding_namespace(value: object) -> SupportedEmbeddingNamespace:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("embedding namespace requires a declared projection family")
    match document.get("projection_version"):
        case "accepted-solution-comparison/1.0":
            return EmbeddingIndexNamespace.model_validate(document)
        case "mixed-solution-comparison/2.0":
            return MixedEmbeddingIndexNamespace.model_validate(document)
        case "public-solution-text/1.0":
            return PublicSolutionIndexNamespace.model_validate(document)
        case _:
            raise ValueError("unsupported embedding namespace family")


def parse_supported_embedding_index(value: object) -> SupportedEmbeddingIndex:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "embedding-index-manifest/3.0"
    ):
        return PublicSolutionEmbeddingIndex.model_validate(document)
    return parse_legacy_index(document)


def parse_supported_embedding_binding(value: object) -> SupportedEmbeddingBinding:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "embedding-source-binding/3.0"
    ):
        return PublicSolutionEmbeddingSourceBinding.model_validate(document)
    return parse_legacy_binding(document)


def parse_supported_embedding_entry(value: object) -> SupportedEmbeddingEntry:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "public-solution-embedding-entry/1.0"
    ):
        return PublicSolutionEmbeddingEntry.model_validate(document)
    return parse_legacy_entry(document)


def embedding_entry_source(entry: SupportedEmbeddingEntry) -> ApprovedItemKnowledgeSourceV2:
    return (
        entry.source
        if isinstance(entry, PublicSolutionEmbeddingEntry)
        else entry.profile.source_basis.source
    )


def embedding_entry_graph(entry: SupportedEmbeddingEntry) -> KnowledgeGraphSnapshotPointer:
    return (
        entry.graph_snapshot
        if isinstance(entry, PublicSolutionEmbeddingEntry)
        else entry.profile.source_basis.graph_snapshot
    )


def embedding_entry_profile(entry: SupportedEmbeddingEntry) -> SupportedEmbeddingProfilePointer:
    if isinstance(entry, PublicSolutionEmbeddingEntry):
        return PublicSolutionProfilePointer.from_entry(entry)
    if isinstance(entry, RegisteredReviewEmbeddingEntry):
        return RegisteredReviewProfilePointer.from_profile(entry.profile)
    return InferenceTransferProfilePointer.from_profile(entry.profile)


def validate_supported_embedding_index_references(
    index: SupportedEmbeddingIndex,
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    previous: tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None,
) -> None:
    index = parse_supported_embedding_index(index)
    if isinstance(index, PublicSolutionEmbeddingIndex):
        if previous is not None:
            if not isinstance(previous[1], PublicSolutionEmbeddingIndex):
                raise ValueError("PUBLIC_SOLUTION_INDEX_PREDECESSOR_INVALID")
            validate_embedding_manifest_pointer(
                previous[0], PUBLIC_SOLUTION_INDEX_SCHEMA_REF, "index.json"
            )
        validate_embedding_index_reference_layout(index, shards, previous)
    else:
        if isinstance(index, MixedEmbeddingIndexManifest):
            parent = None
            if previous is not None:
                if not isinstance(
                    previous[1], (EmbeddingIndexManifest, MixedEmbeddingIndexManifest)
                ):
                    raise ValueError("LEGACY_INDEX_PREDECESSOR_INVALID")
                parent = previous[0], previous[1]
            validate_mixed_embedding_index_references(index, shards, parent)
        else:
            old_parent = None
            if previous is not None:
                if not isinstance(previous[1], EmbeddingIndexManifest):
                    raise ValueError("LEGACY_INDEX_PREDECESSOR_INVALID")
                old_parent = previous[0], previous[1]
            validate_embedding_index_references(index, shards, old_parent)


def validate_supported_embedding_source_bindings(
    bindings: tuple[SupportedEmbeddingBinding, ...],
    entries: tuple[SupportedEmbeddingEntry, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
) -> None:
    """One bounded family join; metadata validation is not numerical/source admission."""
    public = all(
        isinstance(value, PublicSolutionEmbeddingSourceBinding) for value in bindings
    ) and all(isinstance(value, PublicSolutionEmbeddingEntry) for value in entries)
    maximum = MAX_PUBLIC_SOLUTION_SOURCES if public else 1024
    if any(len(values) > maximum for values in (bindings, entries, shards)):
        raise ValueError("EMBEDDING_BINDING_SCOPE_LIMIT")
    checked_entries = tuple(parse_supported_embedding_entry(entry) for entry in entries)
    by_source = {embedding_entry_source(entry).item_revision_id: entry for entry in checked_entries}
    if len(by_source) != len(entries):
        raise ValueError("EMBEDDING_BINDING_SOURCE_DUPLICATE")
    checked = tuple(parse_supported_embedding_binding(binding) for binding in bindings)
    needed = {binding.row_ref.shard_manifest for binding in checked}
    if len({binding.binding_sha256 for binding in checked}) != len(checked) or needed != {
        p for p, _ in shards
    }:
        raise ValueError("EMBEDDING_BINDING_SHARDS_INVALID")
    legacy = tuple(
        binding
        for binding in checked
        if not isinstance(binding, PublicSolutionEmbeddingSourceBinding)
    )
    legacy_shards = {binding.row_ref.shard_manifest for binding in legacy}
    validate_mixed_embedding_source_bindings(
        legacy,
        tuple(
            entry
            for entry in checked_entries
            if not isinstance(entry, PublicSolutionEmbeddingEntry)
        ),
        tuple((pointer, shard) for pointer, shard in shards if pointer in legacy_shards),
    )
    manifests = {}
    for pointer, shard in shards:
        shard = EmbeddingVectorShardManifest.model_validate(shard.model_dump(mode="json"))
        if pointer in manifests:
            raise ValueError("EMBEDDING_BINDING_SHARDS_INVALID")
        manifests[pointer] = shard
        if pointer.sha256 != content_sha256(shard.model_dump(mode="json")):
            raise ValueError("EMBEDDING_BINDING_SHARD_HASH_INVALID")
    for binding in checked:
        if not isinstance(binding, PublicSolutionEmbeddingSourceBinding):
            continue
        entry = by_source.get(binding.source.item_revision_id)
        if not isinstance(entry, PublicSolutionEmbeddingEntry):
            raise ValueError("PUBLIC_SOLUTION_BINDING_ENTRY_REQUIRED")
        shard = manifests[binding.row_ref.shard_manifest]
        text = entry.public_solution.text
        if (
            binding.source != entry.source
            or binding.profile != PublicSolutionProfilePointer.from_entry(entry)
            or binding.evidence != entry.evidence
            or binding.base_analysis_run_id != entry.base_analysis_run_id
            or binding.graph_snapshot != entry.graph_snapshot
            or binding.policy_revision_id != entry.policy_revision_id
            or binding.policy_sha256 != entry.policy_sha256
            or binding.recipe != entry.recipe
            or text is None
            or len(text.encode("utf-8")) > entry.recipe.maximum_text_bytes
            or binding.encoding.input_text_sha256 != entry.public_solution.text_sha256
            or shard.space.purpose != "DOCUMENT"
            or binding.encoding.space_sha256 != shard.space.space_sha256
            or binding.row_ref.row_index >= len(shard.rows)
            or shard.rows[binding.row_ref.row_index] != binding.encoding
        ):
            raise ValueError("PUBLIC_SOLUTION_BINDING_ENTRY_MISMATCH")
