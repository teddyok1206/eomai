"""Pure branch-aware identities for Catalog's existing embedding ledger.

An accepted-base ID is an association, not proof of acceptance. The official
source owner must resolve it in the current authorized Graph transaction.
"""

from __future__ import annotations

import re

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingBinding,
    embedding_entry_profile,
    parse_supported_embedding_entry,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSourceBinding,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import same_approved_item_source_identity
from eom_catalog_contracts.mixed_embedding_index import (
    RegisteredReviewEmbeddingEntry,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingSourceBinding,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionSourceBinding,
)
from eom_identifiers import content_sha256

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    PublicSolutionEmbeddingBindingLookupKey,
    RegisteredReviewEmbeddingBindingLookupKey,
    SupportedEmbeddingBindingLookupKey,
    SupportedEmbeddingEntry,
)


def embedding_binding_lookup_key(
    binding: SupportedEmbeddingBinding,
) -> SupportedEmbeddingBindingLookupKey:
    common = (
        binding.source.item_revision_id,
        binding.graph_snapshot.graph_snapshot_revision_id,
        binding.policy_revision_id,
        binding.recipe.recipe_sha256,
        binding.view,
        binding.projection_version,
    )
    if isinstance(
        binding, PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding
    ):
        return PublicSolutionEmbeddingBindingLookupKey(
            *common,
            binding.base_analysis_run_id,
            binding.profile.profile_revision_id,
            binding.encoding.encoding_sha256,
            content_sha256(binding.evidence),
        )
    if isinstance(binding, EmbeddingSourceBinding):
        return EmbeddingBindingLookupKey(
            *common,
            binding.solution_evidence.base_analysis_run_id,
            binding.profile.profile_revision_id,
            binding.solution_evidence.solution_analysis_run_id,
            binding.encoding.encoding_sha256,
        )
    return RegisteredReviewEmbeddingBindingLookupKey(
        *common,
        binding.base_analysis_run_id,
        binding.profile.profile_revision_id,
        binding.encoding.encoding_sha256,
        binding.review_evidence.review.job_id,
        binding.review_evidence.evidence_sha256,
    )


def validated_embedding_base_associations(
    sources: tuple[PopulationSource, ...],
    entries: tuple[SupportedEmbeddingEntry, ...],
    associations: tuple[tuple[str, str], ...],
    *,
    require_explicit: bool,
) -> dict[str, str]:
    """Exact bounded selected identities; never infer a base from a REVIEW job."""
    by_source = {source.item_revision_id: source for source in sources}
    base_ids = dict(associations)
    if (
        len(by_source) != len(sources)
        or len(base_ids) != len(associations)
        or len(set(base_ids.values())) != len(base_ids)
        or not set(base_ids).issubset(by_source)
        or any(
            re.fullmatch(r"analysisrun_[0-9a-f]{32}", value) is None for value in base_ids.values()
        )
        or (require_explicit and set(base_ids) != set(by_source))
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    for original in entries:
        entry = parse_supported_embedding_entry(original)
        if isinstance(entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry):
            revision = entry.source.item_revision_id
            if (
                by_source.get(revision) != entry.source
                or base_ids.get(revision) != entry.base_analysis_run_id
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            continue
        basis = entry.profile.source_basis
        revision = basis.source.item_revision_id
        source = by_source.get(revision)
        if source is None or not same_approved_item_source_identity(source, basis.source):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        if isinstance(entry, RegisteredReviewEmbeddingEntry):
            if revision not in base_ids:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        elif (
            revision in base_ids
            and base_ids[revision]
            != entry.profile.source_basis.solution_evidence.base_analysis_run_id
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        else:
            base_ids[revision] = entry.profile.source_basis.solution_evidence.base_analysis_run_id
    return base_ids


def embedding_entry_lookup_key(
    entry: SupportedEmbeddingEntry,
    encoding: EmbeddingEncodingIdentity,
    scope: EmbeddingRegistryLookup,
    base_analysis_run_id: str,
) -> SupportedEmbeddingBindingLookupKey:
    if isinstance(entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry):
        if entry.base_analysis_run_id != base_analysis_run_id:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return PublicSolutionEmbeddingBindingLookupKey(
            entry.source.item_revision_id,
            scope.graph_snapshot.graph_snapshot_revision_id,
            scope.policy_revision_id,
            scope.namespace.recipe_sha256,
            scope.namespace.view,
            "public-solution-text/1.0",
            entry.base_analysis_run_id,
            embedding_entry_profile(entry).profile_revision_id,
            encoding.encoding_sha256,
            content_sha256(entry.evidence),
        )
    basis = entry.profile.source_basis
    common = (
        basis.source.item_revision_id,
        scope.graph_snapshot.graph_snapshot_revision_id,
        scope.policy_revision_id,
        scope.namespace.recipe_sha256,
        scope.namespace.view,
    )
    if isinstance(entry, RegisteredReviewEmbeddingEntry):
        return RegisteredReviewEmbeddingBindingLookupKey(
            *common,
            entry.profile.extractor_version,
            base_analysis_run_id,
            entry.profile.profile_revision_id,
            encoding.encoding_sha256,
            entry.profile.source_basis.review_evidence.review.job_id,
            entry.profile.source_basis.review_evidence.evidence_sha256,
        )
    return EmbeddingBindingLookupKey(
        *common,
        entry.profile.extraction.extractor_version,
        base_analysis_run_id,
        entry.profile.profile_revision_id,
        entry.profile.source_basis.solution_evidence.solution_analysis_run_id,
        encoding.encoding_sha256,
    )
