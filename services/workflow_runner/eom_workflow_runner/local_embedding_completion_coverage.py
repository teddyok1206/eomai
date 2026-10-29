"""Typed registered-index coverage shared by active completion and completed reads."""

from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.mixed_embedding_index import MixedEmbeddingIndexManifest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionEmbeddingIndex
from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingRegistration
from eom_workflow.local_embedding_workflow_receipt import ResolvedNativeIndexCoverage
from eom_workflow.local_embedding_workflow_receipt_v2 import ResolvedNativeIndexCoverageV2
from eom_workflow.local_embedding_workflow_receipt_v3 import ResolvedNativeIndexCoverageV3


def resolved_native_index_coverage(
    resolved: ResolvedEmbeddingRegistration,
) -> ResolvedNativeIndexCoverage | ResolvedNativeIndexCoverageV2 | ResolvedNativeIndexCoverageV3:
    if isinstance(resolved.index, PublicSolutionEmbeddingIndex):
        public_previous = None
        if resolved.previous is not None:
            pointer, public_index = resolved.previous
            if not isinstance(public_index, PublicSolutionEmbeddingIndex):
                raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
            public_previous = (pointer, public_index)
        return ResolvedNativeIndexCoverageV3(resolved.index, resolved.sources, public_previous)
    if isinstance(resolved.index, MixedEmbeddingIndexManifest):
        mixed_previous = None
        if resolved.previous is not None:
            pointer, mixed_index = resolved.previous
            if not isinstance(mixed_index, (EmbeddingIndexManifest, MixedEmbeddingIndexManifest)):
                raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
            mixed_previous = (pointer, mixed_index)
        return ResolvedNativeIndexCoverageV2(resolved.index, resolved.sources, mixed_previous)
    previous = None
    if resolved.previous is not None:
        pointer, index = resolved.previous
        if not isinstance(index, EmbeddingIndexManifest):
            raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
        previous = (pointer, index)
    return ResolvedNativeIndexCoverage(resolved.index, resolved.sources, previous)
