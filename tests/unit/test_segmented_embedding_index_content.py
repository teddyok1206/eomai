"""Synthetic 1,025-row closure; no actor authorization, Artifact read or GPU execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
)
from eom_catalog_contracts.segmented_embedding_index import SegmentedEmbeddingIndexRoot
from eom_catalog_service.embedding_device_index_pair import canonical_embedding_index_targets
from eom_catalog_service.segmented_embedding_index_validation import (
    SegmentedEmbeddingIndexError,
    validate_segmented_embedding_index_content,
)
from eom_catalog_service.segmented_local_indexing_population_read import (
    CandidateSourcePageDescriptor,
    SegmentedSourceSelection,
    segmented_source_selection_sha256,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    index_manifest,
    index_pointer,
    seal,
    source_binding,
)
from tests.unit.inference_transfer_fixtures import NOW

SegmentedCase = tuple[
    SegmentedEmbeddingIndexRoot,
    tuple[tuple[ArtifactMemberPointer, EmbeddingIndexManifest], ...],
    SegmentedSourceSelection,
]


def _reseal_root(body: dict[str, Any]) -> dict[str, Any]:
    body["target_set_sha256"] = content_sha256(
        [
            {
                "first_source_revision_id": segment["first_source_revision_id"],
                "last_source_revision_id": segment["last_source_revision_id"],
                "binding_count": segment["binding_count"],
                "target_set_sha256": segment["target_set_sha256"],
            }
            for segment in body["segments"]
        ]
    )
    return seal(body, "root_sha256")


@pytest.fixture(scope="module")
def case() -> SegmentedCase:
    base = source_binding(embedding_entry("a", source_class="APPROVED_ITEM"))
    bindings = []
    for ordinal in range(1025):
        body = base.model_dump(mode="json")
        identifier = f"{ordinal:032x}"
        body["source"]["item_id"] = "item_" + identifier
        body["source"]["item_revision_id"] = "itemrev_" + identifier
        bindings.append(EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256")))
    first = index_manifest(*bindings[:1024], revision_seed="2")
    second = index_manifest(bindings[1024], revision_seed="3")
    second_body = second.model_dump(mode="json")
    second_body["index_id"] = "embeddingindex_" + "2" * 32
    second = EmbeddingIndexManifest.model_validate(seal(second_body, "index_sha256"))
    indexes = (first, second)
    resolved = tuple(
        (index_pointer(index, seed), index) for seed, index in zip(("4", "5"), indexes, strict=True)
    )
    segments = [
        {
            "index_manifest": member.model_dump(mode="json"),
            "first_source_revision_id": index.bindings[0].source.item_revision_id,
            "last_source_revision_id": index.bindings[-1].source.item_revision_id,
            "binding_count": len(index.bindings),
            "target_set_sha256": content_sha256(canonical_embedding_index_targets(index)),
        }
        for member, index in resolved
    ]
    selection_segments = tuple(
        CandidateSourcePageDescriptor(
            first_source_revision_id=index.bindings[0].source.item_revision_id,
            last_source_revision_id=index.bindings[-1].source.item_revision_id,
            source_count=len(index.bindings),
            source_analysis_sha256=content_sha256(
                [
                    {
                        "source_revision_id": binding.source.item_revision_id,
                        "analysis_run_id": binding.solution_evidence.base_analysis_run_id,
                    }
                    for binding in index.bindings
                ]
            ),
        )
        for index in indexes
    )
    selection = SegmentedSourceSelection(
        graph_snapshot_revision_id=base.graph_snapshot.graph_snapshot_revision_id,
        policy_revision_id=base.policy_revision_id,
        source_count=1025,
        segments=selection_segments,
        selection_sha256=segmented_source_selection_sha256(
            base.graph_snapshot.graph_snapshot_revision_id,
            base.policy_revision_id,
            selection_segments,
        ),
    )
    body = {
        "schema_version": "segmented-embedding-index/1.0",
        "index_id": "embeddingindex_" + "9" * 32,
        "index_revision_id": "embeddingindexrev_" + "9" * 32,
        "previous_root": None,
        "corpus_id": "corpus_" + "c" * 32,
        "graph_snapshot": base.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": base.policy_revision_id,
        "policy_sha256": base.policy_sha256,
        "storage_partition": PARTITION,
        "space": first.space.model_dump(mode="json"),
        "view": first.view,
        "recipe": first.recipe.model_dump(mode="json"),
        "segments": segments,
        "source_count": 1025,
        "source_selection_sha256": selection.selection_sha256,
        "binding_count": 1025,
        "target_set_sha256": "",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    return SegmentedEmbeddingIndexRoot.model_validate(_reseal_root(body)), resolved, selection


def test_exact_large_segment_content_closes_without_vector_copy(case: SegmentedCase) -> None:
    root, resolved, selection = case
    assert validate_segmented_embedding_index_content(root, resolved, selection) == root
    assert root.binding_count == 1025


def test_sparse_large_population_keeps_one_segment_without_truncating_source_scope(
    case: SegmentedCase,
) -> None:
    root, resolved, selection = case
    body = root.model_dump(mode="json")
    body["segments"] = [body["segments"][1]]
    body["binding_count"] = 1
    sparse = SegmentedEmbeddingIndexRoot.model_validate(_reseal_root(body))
    assert validate_segmented_embedding_index_content(sparse, (resolved[1],), selection) == sparse
    assert sparse.source_count == 1025 and sparse.binding_count == 1


def test_typed_descriptor_cannot_fake_a_segment_count(case: SegmentedCase) -> None:
    root, resolved, selection = case
    body = root.model_dump(mode="json")
    body["segments"][0]["binding_count"] = 1023
    body["segments"][1]["binding_count"] = 2
    forged = SegmentedEmbeddingIndexRoot.model_validate(_reseal_root(body))
    with pytest.raises(SegmentedEmbeddingIndexError):
        validate_segmented_embedding_index_content(forged, resolved, selection)


def test_modified_member_or_policy_is_not_a_compatible_segment(case: SegmentedCase) -> None:
    root, resolved, selection = case
    changed = resolved[1][0].model_copy(update={"sha256": "sha256:" + "0" * 64})
    with pytest.raises(SegmentedEmbeddingIndexError):
        validate_segmented_embedding_index_content(
            root, (resolved[0], (changed, resolved[1][1])), selection
        )
    body = root.model_dump(mode="json")
    body["policy_sha256"] = "sha256:" + "0" * 64
    forged = SegmentedEmbeddingIndexRoot.model_validate(_reseal_root(body))
    with pytest.raises(SegmentedEmbeddingIndexError):
        validate_segmented_embedding_index_content(forged, resolved, selection)


@pytest.mark.parametrize(
    "fault", ["source_count", "selection_hash", "policy", "graph", "page_count", "page_hash"]
)
def test_content_requires_the_exact_catalog_source_selection(
    case: SegmentedCase, fault: str
) -> None:
    root, resolved, selection = case
    if fault == "source_count":
        changed = replace(selection, source_count=1026)
    elif fault == "selection_hash":
        changed = replace(selection, selection_sha256="sha256:" + "0" * 64)
    elif fault == "policy":
        changed = replace(selection, policy_revision_id="accessrev_" + "f" * 32)
    elif fault == "page_count":
        changed = replace(
            selection,
            segments=(replace(selection.segments[0], source_count=1023), selection.segments[1]),
        )
    elif fault == "page_hash":
        changed = replace(
            selection,
            segments=(
                replace(selection.segments[0], source_analysis_sha256="sha256:" + "0" * 64),
                selection.segments[1],
            ),
        )
    else:
        changed = replace(selection, graph_snapshot_revision_id="graphrev_" + "f" * 32)
    with pytest.raises(SegmentedEmbeddingIndexError):
        validate_segmented_embedding_index_content(root, resolved, changed)
