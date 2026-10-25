"""Typed registered-index coverage shared by active completion and completed reads."""

from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.mixed_embedding_index import MixedEmbeddingIndexManifest
from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingRegistration
from eom_workflow.local_embedding_workflow_receipt import ResolvedNativeIndexCoverage
from eom_workflow.local_embedding_workflow_receipt_v2 import ResolvedNativeIndexCoverageV2


def resolved_native_index_coverage(
    resolved: ResolvedEmbeddingRegistration,
) -> ResolvedNativeIndexCoverage | ResolvedNativeIndexCoverageV2:
    if isinstance(resolved.index, MixedEmbeddingIndexManifest):
        return ResolvedNativeIndexCoverageV2(resolved.index, resolved.sources, resolved.previous)
    previous = None
    if resolved.previous is not None:
        pointer, index = resolved.previous
        if not isinstance(index, EmbeddingIndexManifest):
            raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
        previous = (pointer, index)
    return ResolvedNativeIndexCoverage(resolved.index, resolved.sources, previous)
