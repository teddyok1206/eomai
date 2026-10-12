"""Synthetic delta planning only; no published source, model or DB invocation."""

from __future__ import annotations

import pytest
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile
from eom_catalog_service.embedding_incremental_plan import (
    EmbeddingDeltaError,
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_space,
    seal,
    source_binding,
)
from tests.unit.inference_transfer_experiment_fixtures import entry


def registered(staged: StagedExperimentEntry) -> RegisteredEmbeddingRow:
    binding = source_binding(staged)
    return RegisteredEmbeddingRow(binding.encoding, binding.row_ref)


def test_same_text_is_encoded_once_without_merging_two_source_identities() -> None:
    a, b = entry("a"), entry("b")
    result = plan_embedding_delta(
        (b, a), space=embedding_space(), storage_partition=PARTITION, views=("METADATA_ONLY",)
    )
    assert len(result.new_inputs) == 1
    assert len(result.demands) == 2
    assert tuple(value.source_revision_id for value in result.demands) == (
        a.profile.source_basis.source.item_revision_id,
        b.profile.source_basis.source.item_revision_id,
    )
    assert result.demands[0].encoding == result.demands[1].encoding
    assert result.demands[0].profile != result.demands[1].profile


def test_existing_encoding_is_reused_for_a_new_source_without_claiming_binding_ready() -> None:
    a, b = entry("a"), entry("b")
    result = plan_embedding_delta(
        (a, b),
        space=embedding_space(),
        storage_partition=PARTITION,
        views=("METADATA_ONLY",),
        registered_rows=(registered(a),),
    )
    assert result.new_inputs == ()
    assert len(result.reusable_rows) == 1
    assert len(result.demands) == 2


def test_only_missing_views_become_new_inputs() -> None:
    a = entry("a")
    result = plan_embedding_delta(
        (a,), space=embedding_space(), storage_partition=PARTITION, registered_rows=(registered(a),)
    )
    assert len(result.demands) == 3
    assert len(result.new_inputs) == 2
    assert len(result.reusable_rows) == 1
    assert all(row.encoding != registered(a).encoding for row in result.new_inputs)


def test_graph_only_revision_change_reuses_numbers_and_keeps_new_profile_association() -> None:
    old = entry("a")
    body = old.profile.model_dump(mode="json", exclude={"profile_sha256"})
    graph = body["source_basis"]["graph_snapshot"]
    graph["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    body["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
    new_profile = InferenceTransferProfile.model_validate(seal(body, "profile_sha256"))
    newer = StagedExperimentEntry(
        profile=new_profile,
        content=old.content,
        metadata=old.metadata,
        limitations=old.limitations,
    )
    result = plan_embedding_delta(
        (newer,),
        space=embedding_space(),
        storage_partition=PARTITION,
        views=("METADATA_ONLY",),
        registered_rows=(registered(old),),
    )
    assert result.new_inputs == ()
    assert len(result.reusable_rows) == 1
    assert result.demands[0].profile.profile_sha256 == new_profile.profile_sha256
    assert result.demands[0].profile.profile_sha256 != old.profile.profile_sha256


def test_cpu_vectors_cannot_be_silently_reused_in_a_cuda_space() -> None:
    a = entry("a")
    with pytest.raises(EmbeddingDeltaError, match="REGISTERED_ROW_INVALID"):
        plan_embedding_delta(
            (a,),
            space=embedding_space(device="CUDA"),
            storage_partition=PARTITION,
            registered_rows=(registered(a),),
        )
    result = plan_embedding_delta(
        (a,), space=embedding_space(device="CUDA"), storage_partition=PARTITION
    )
    assert len(result.new_inputs) == 3


def test_foreign_storage_partition_is_not_an_available_encoding() -> None:
    a = entry("a")
    with pytest.raises(EmbeddingDeltaError, match="REGISTERED_ROW_INVALID"):
        plan_embedding_delta(
            (a,),
            space=embedding_space(),
            storage_partition="other",
            registered_rows=(registered(a),),
        )


def test_empty_or_missing_view_is_recorded_not_filled_with_fake_content() -> None:
    a = entry("a")
    without_text = StagedExperimentEntry(
        profile=a.profile, content=None, metadata=(), limitations=a.limitations
    )
    result = plan_embedding_delta(
        (without_text,), space=embedding_space(), storage_partition=PARTITION
    )
    assert len(result.demands) == 1
    assert len(result.new_inputs) == 1
    assert tuple((value.view, value.reason) for value in result.unavailable_views) == (
        ("CONTENT_ONLY", "VIEW_NOT_MATERIALIZED"),
        ("METADATA_ONLY", "EMPTY_VIEW"),
    )


def test_empty_eligible_entries_do_not_invent_a_population_or_encoder_input() -> None:
    result = plan_embedding_delta((), space=embedding_space(), storage_partition=PARTITION)
    assert result.demands == ()
    assert result.new_inputs == ()
    assert result.reusable_rows == ()
    assert result.unavailable_views == ()


def test_duplicate_sources_are_not_silently_merged() -> None:
    a = entry("a")
    with pytest.raises(EmbeddingDeltaError, match="DUPLICATE_SOURCE"):
        plan_embedding_delta((a, a), space=embedding_space(), storage_partition=PARTITION)


def test_duplicate_or_foreign_row_mapping_fails_explicitly() -> None:
    a = entry("a")
    known = registered(a)
    with pytest.raises(EmbeddingDeltaError, match="REGISTERED_ROW_INVALID"):
        plan_embedding_delta(
            (a,),
            space=embedding_space(),
            storage_partition=PARTITION,
            registered_rows=(known, known),
        )
    corrupted = RegisteredEmbeddingRow(
        known.encoding, known.row_ref.model_copy(update={"encoding_sha256": "sha256:" + "0" * 64})
    )
    with pytest.raises(EmbeddingDeltaError, match="REGISTERED_ROW_INVALID"):
        plan_embedding_delta(
            (a,), space=embedding_space(), storage_partition=PARTITION, registered_rows=(corrupted,)
        )


def test_reordered_sources_and_view_selection_have_identical_plans() -> None:
    a, b = entry("a"), entry("b")
    left = plan_embedding_delta(
        (a, b),
        space=embedding_space(),
        storage_partition=PARTITION,
        views=("METADATA_ONLY", "CONTENT_ONLY"),
    )
    right = plan_embedding_delta(
        (b, a),
        space=embedding_space(),
        storage_partition=PARTITION,
        views=("CONTENT_ONLY", "METADATA_ONLY"),
    )
    assert left == right


def test_views_are_unique_and_document_space_is_required() -> None:
    a = entry("a")
    with pytest.raises(EmbeddingDeltaError, match="SELECTION_INVALID"):
        plan_embedding_delta(
            (a,),
            space=embedding_space(),
            storage_partition=PARTITION,
            views=("CONTENT_ONLY", "CONTENT_ONLY"),
        )
    with pytest.raises(EmbeddingDeltaError, match="PURPOSE_INVALID"):
        plan_embedding_delta(
            (a,), space=embedding_space(purpose="QUERY"), storage_partition=PARTITION
        )
