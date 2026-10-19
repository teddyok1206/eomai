"""Pure mixed assembly; source authorization and numeric verification remain outside."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingSourceBinding,
    validate_mixed_embedding_source_bindings,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_assembly import assemble_embedding_index_revision
from eom_catalog_service.embedding_index_assembly_v2 import (
    AssembledMixedEmbeddingIndex,
    assemble_embedding_index_revision_v2,
)
from eom_catalog_service.local_embedding_source_plan_v2 import build_local_embedding_source_plan_v2
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_selected_index_coverage_v2,
)

from tests.unit.inference_transfer_embedding_fixtures import seal, shard_pointer, vector_shard
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_local_embedding_source_plan_v2 import build, inputs


def rows_for(
    plan: LocalEmbeddingSourcePlanV2, seed: str = "a"
) -> tuple[
    tuple[RegisteredEmbeddingRow, ...], tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest]
]:
    unique = {demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands}
    shard = vector_shard(tuple(unique[key] for key in sorted(unique)), space=plan.space)
    pointer = shard_pointer(shard, seed)
    rows = tuple(
        RegisteredEmbeddingRow(
            encoding,
            EmbeddingVectorRowRef(
                shard_manifest=pointer, row_index=index, encoding_sha256=encoding.encoding_sha256
            ),
        )
        for index, encoding in enumerate(shard.rows)
    )
    return rows, (pointer, shard)


def pointer(index: MixedEmbeddingIndexManifest | EmbeddingIndexManifest) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="index.json",
        schema_ref=MIXED_EMBEDDING_INDEX_SCHEMA_REF
        if isinstance(index, MixedEmbeddingIndexManifest)
        else "eom://schemas/knowledge/embedding-index-manifest/1.0",
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )


def assemble(
    plan: LocalEmbeddingSourcePlanV2,
    rows: tuple[RegisteredEmbeddingRow, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    *,
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest]
    | None = None,
    revision: str = "2",
) -> AssembledMixedEmbeddingIndex:
    return assemble_embedding_index_revision_v2(
        plan,
        available_rows=rows,
        shards=shards,
        index_id="embeddingindex_" + "1" * 32,
        index_revision_id="embeddingindexrev_" + revision * 32,
        previous=previous,
        created_at=NOW,
    )


def test_mixed_seed_is_deterministic_and_exact_original_branches_are_valid() -> None:
    plan = build()
    rows, shard = rows_for(plan)
    first = assemble(plan, rows, (shard,))
    assert assemble(plan, rows[::-1], (shard,)) == first
    assert len(first.index.bindings) == 2
    assert first.index.schema_version == "embedding-index-manifest/2.0"
    assert {binding.projection_version for binding in first.index.bindings} == {
        "accepted-solution-comparison/1.0",
        "registered-item-review-comparison/1.0",
    }
    validate_mixed_embedding_source_bindings(
        first.index.bindings, inputs()[1].entries, first.shards
    )
    validate_local_embedding_selected_index_coverage_v2(plan, first.index)
    registered = first.index.bindings[0]
    assert isinstance(registered, RegisteredReviewEmbeddingSourceBinding)
    assert registered.base_analysis_run_id == "analysisrun_" + "c" * 32
    assert not hasattr(registered, "solution_evidence")


def test_partial_rows_remain_partial_and_later_delta_uses_the_same_rows() -> None:
    plan = build()
    rows, shard = rows_for(plan)
    first = assemble(plan, rows[:1], (shard,))
    assert len(first.index.bindings) == 1
    second = assemble(
        plan, rows, (shard,), previous=(pointer(first.index), first.index), revision="3"
    )
    assert len(second.index.bindings) == 2
    assert second.index.previous_manifest == pointer(first.index)
    old = first.index.bindings[0]
    assert old in second.index.bindings
    assert old.row_ref in tuple(binding.row_ref for binding in second.index.bindings)


def test_one_encoding_row_preserves_distinct_legacy_and_review_associations() -> None:
    query, resolved, bases = inputs("METADATA_ONLY")
    old, new = resolved.entries
    assert isinstance(old, StagedExperimentEntry)
    metadata = new.metadata[0].model_copy(
        update={"source_sha256": old.profile.source_basis.source.artifact_member.sha256}
    )
    old = StagedExperimentEntry.model_validate(old.model_copy(update={"metadata": (metadata,)}))
    entries = (old, new)
    plan = build_local_embedding_source_plan_v2(
        query,
        replace(resolved, entries=entries),
        target_revision_ids=tuple(bases),
        base_analysis_run_ids=bases,
    )
    assert len(plan.demands) == 2 and plan.demands[0].encoding == plan.demands[1].encoding
    rows, shard = rows_for(plan)
    assert len(rows) == 1
    result = assemble(plan, rows, (shard,))
    assert len(result.index.bindings) == 2
    assert result.index.bindings[0].row_ref == result.index.bindings[1].row_ref
    assert result.index.bindings[0].profile != result.index.bindings[1].profile
    validate_mixed_embedding_source_bindings(result.index.bindings, entries, result.shards)


def test_graph_change_rebuilds_both_associations_without_changing_numbers() -> None:
    plan = build()
    rows, shard = rows_for(plan)
    first = assemble(plan, rows, (shard,))
    document = plan.model_dump(mode="json")
    document["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    changed = parse_local_embedding_source_plan_v2(seal(document, "plan_sha256"))
    second = assemble(
        changed, rows, (shard,), previous=(pointer(first.index), first.index), revision="3"
    )
    for old, new in zip(first.index.bindings, second.index.bindings, strict=True):
        assert old.encoding == new.encoding and old.row_ref == new.row_ref
        assert old.binding_sha256 != new.binding_sha256
        assert new.graph_snapshot == changed.graph_snapshot


def test_revoked_or_missing_review_is_not_copied_from_prior_index() -> None:
    query, resolved, bases = inputs()
    plan = build()
    rows, shard = rows_for(plan)
    first = assemble(plan, rows, (shard,))
    legacy_id = resolved.sources[0].item_revision_id
    selected = build_local_embedding_source_plan_v2(
        query, resolved, target_revision_ids=(legacy_id,), base_analysis_run_ids=bases
    )
    selected_rows = tuple(row for row in rows if row.encoding == selected.demands[0].encoding)
    second = assemble(
        selected,
        selected_rows,
        (shard,),
        previous=(pointer(first.index), first.index),
        revision="3",
    )
    assert tuple(binding.source.item_revision_id for binding in second.index.bindings) == (
        legacy_id,
    )
    with pytest.raises(ValueError, match="ROW_INVALID"):
        assemble(selected, rows, (shard,))


def test_missing_report_never_creates_a_placeholder_binding() -> None:
    query, resolved, bases = inputs()
    selected = build_local_embedding_source_plan_v2(
        query,
        replace(resolved, entries=resolved.entries[:1]),
        target_revision_ids=tuple(bases),
        base_analysis_run_ids=bases,
    )
    rows, shard = rows_for(selected)
    result = assemble(selected, rows, (shard,))
    assert len(selected.sources) == 2 and len(result.index.bindings) == 1
    assert selected.missing_solution_report_revision_ids == (resolved.sources[1].item_revision_id,)


def test_legacy_binding_bytes_equal_released_assembler_for_the_same_values() -> None:
    query, resolved, bases = inputs()
    plan2 = build_local_embedding_source_plan_v2(
        query,
        resolved,
        target_revision_ids=(resolved.sources[0].item_revision_id,),
        base_analysis_run_ids=bases,
    )
    document = plan2.model_dump(mode="json")
    document["schema_version"] = "local-embedding-source-plan/1.0"
    document["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    document["demands"] = [
        {
            key: value
            for key, value in demand.items()
            if key not in {"evidence_kind", "base_analysis_run_id"}
        }
        for demand in document["demands"]
    ]
    plan1 = parse_local_embedding_source_plan(seal(document, "plan_sha256"))
    rows, shard = rows_for(plan2)
    mixed = assemble(plan2, rows, (shard,))
    old = assemble_embedding_index_revision(
        plan1,
        available_rows=rows,
        shards=(shard,),
        index_id=mixed.index.index_id,
        index_revision_id=mixed.index.index_revision_id,
        previous=None,
        created_at=NOW,
    )
    assert canonical_json_bytes(mixed.index.bindings[0]) == canonical_json_bytes(
        old.index.bindings[0]
    )
    # A genuine same-logical-index predecessor1 can be resolved explicitly;
    # normal namespace2 registration starts a new ID and therefore uses None.
    successor = assemble(
        plan2, rows, (shard,), previous=(pointer(old.index), old.index), revision="3"
    )
    assert successor.index.previous_manifest == pointer(old.index)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_row",
        "foreign_row",
        "wrong_row",
        "missing_shard",
        "duplicate_shard",
        "hash",
        "empty",
        "oversize",
    ],
)
def test_invalid_rows_and_shards_never_produce_a_success_index(fault: str) -> None:
    plan = build()
    rows, shard = rows_for(plan)
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...] = (shard,)
    if fault == "duplicate_row":
        rows = (*rows, rows[0])
    elif fault == "foreign_row":
        foreign_plan = build("CONTENT_ONLY")
        rows = rows_for(foreign_plan)[0]
    elif fault == "wrong_row":
        rows = (
            replace(rows[0], row_ref=rows[0].row_ref.model_copy(update={"row_index": 1000})),
            *rows[1:],
        )
    elif fault == "missing_shard":
        shards = ()
    elif fault == "duplicate_shard":
        shards = (shard, shard)
    elif fault == "hash":
        shards = ((shard[0].model_copy(update={"sha256": sha("0")}), shard[1]),)
    elif fault == "empty":
        rows, shards = (), ()
    else:
        rows = (rows[0],) * 1025
    with pytest.raises(ValueError):
        assemble(plan, rows, shards)


@pytest.mark.parametrize("fault", ["foreign_index", "same_revision", "wrong_hash", "unresolved"])
def test_exact_predecessor_identity_is_required(fault: str) -> None:
    plan = build()
    rows, shard = rows_for(plan)
    first = assemble(plan, rows, (shard,))
    parent = first.index
    ref = pointer(parent)
    revision = "3"
    if fault == "foreign_index":
        document = parent.model_dump(mode="json")
        document["index_id"] = "embeddingindex_" + "f" * 32
        parent = MixedEmbeddingIndexManifest.model_validate(seal(document, "index_sha256"))
        ref = pointer(parent)
    elif fault == "same_revision":
        revision = "2"
    elif fault == "wrong_hash":
        ref = ref.model_copy(update={"sha256": sha("0")})
    else:
        ref = ref.model_copy(
            update={"schema_ref": "eom://schemas/knowledge/embedding-index-manifest/1.0"}
        )
    with pytest.raises(ValueError):
        assemble(plan, rows, (shard,), previous=(ref, parent), revision=revision)
