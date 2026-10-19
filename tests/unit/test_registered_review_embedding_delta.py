"""Pure source delta/replay tests; no installed index, model, DB or authority claim."""

from __future__ import annotations

from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    ExperimentMetadataField,
)
from eom_catalog_contracts.registered_review_profile import (
    RegisteredReviewProfilePointer,
    RegisteredReviewSourceBasis,
    build_registered_review_profile,
    registered_review_profile_text,
)
from eom_catalog_service.embedding_incremental_plan import (
    EmbeddingDeltaError,
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.registered_review_embedding_entry import (
    RegisteredReviewEmbeddingEntry,
    registered_review_embedding_view_text,
    validate_registered_review_embedding_entry,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_space,
    source_binding,
)
from tests.unit.inference_transfer_experiment_fixtures import entry as legacy_entry
from tests.unit.registered_review_fixtures import registered_review_profile


def replace(
    staged: RegisteredReviewEmbeddingEntry, **changes: Any
) -> RegisteredReviewEmbeddingEntry:
    """Build intentionally unchecked frozen values; public planning revalidates them."""
    return staged.model_copy(update=changes)


def _entry(version: str = "11.0") -> RegisteredReviewEmbeddingEntry:
    profile = registered_review_profile(version)
    source = profile.source_basis.source.artifact_member
    text = "마찰이 없다. 속도는 -2 m/s이며 질량은 3 kg이다. 옳지 않은 것은?"
    content = CanonicalExperimentItemText(
        text=text, original_source=source, text_sha256=content_sha256(text)
    )
    metadata = (
        ExperimentMetadataField(
            key="MATERIAL_FORM", value="TABLE", basis="ORIGINAL_ITEM", source_sha256=source.sha256
        ),
    )
    return RegisteredReviewEmbeddingEntry(profile=profile, content=content, metadata=metadata)


def _registered_rows(
    staged: RegisteredReviewEmbeddingEntry,
) -> tuple[RegisteredEmbeddingRow, ...]:
    first = plan_embedding_delta((staged,), space=embedding_space(), storage_partition=PARTITION)
    shard = source_binding(legacy_entry("a")).row_ref.shard_manifest
    return tuple(
        RegisteredEmbeddingRow(
            row.encoding,
            EmbeddingVectorRowRef(
                shard_manifest=shard,
                row_index=index,
                encoding_sha256=row.encoding.encoding_sha256,
            ),
        )
        for index, row in enumerate(first.new_inputs)
    )


@pytest.mark.parametrize("version", ("11.0", "12.0"))
def test_existing_delta_planner_accepts_explicit_review_profile_without_faking_v10(
    version: str,
) -> None:
    staged = _entry(version)
    plan = plan_embedding_delta((staged,), space=embedding_space(), storage_partition=PARTITION)
    assert len(plan.demands) == len(plan.new_inputs) == 3
    assert plan.unavailable_views == ()
    assert all(isinstance(d.profile, RegisteredReviewProfilePointer) for d in plan.demands)
    texts = {row.text for row in plan.new_inputs}
    assert staged.content is not None
    assert staged.content.text in texts
    assert registered_review_profile_text(staged.profile) in texts
    assert "MATERIAL_FORM: TABLE" in texts
    assert all("solutionstep_" not in text and "artifact_" not in text for text in texts)


def test_mixed_legacy_and_registered_sources_keep_separate_profile_families() -> None:
    old, new = legacy_entry("a"), _entry()
    plan = plan_embedding_delta((new, old), space=embedding_space(), storage_partition=PARTITION)
    assert len(plan.demands) == 6
    assert {d.profile.schema_ref for d in plan.demands} == {
        "eom://schemas/knowledge/item-inference-transfer/1.0",
        "eom://schemas/knowledge/item-inference-transfer/2.0",
    }
    assert len({d.source_revision_id for d in plan.demands}) == 2


def test_same_registered_inputs_replay_with_zero_new_encodings() -> None:
    staged = _entry()
    rows = _registered_rows(staged)
    plan = plan_embedding_delta(
        (staged,), space=embedding_space(), storage_partition=PARTITION, registered_rows=rows
    )
    assert len(plan.demands) == len(plan.reusable_rows) == 3
    assert plan.new_inputs == ()


def test_graph_only_change_reuses_numbers_but_changes_exact_profile_association() -> None:
    staged = _entry()
    basis_document = staged.profile.source_basis.model_dump(mode="json")
    basis_document["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    newer = build_registered_review_profile(
        source_basis=RegisteredReviewSourceBasis.model_validate(basis_document),
        claims=staged.profile.claims,
        created_at=staged.profile.created_at,
    )
    assert newer.profile_revision_id != staged.profile.profile_revision_id
    plan = plan_embedding_delta(
        (replace(staged, profile=newer),),
        space=embedding_space(),
        storage_partition=PARTITION,
        registered_rows=_registered_rows(staged),
    )
    assert plan.new_inputs == ()
    assert len(plan.reusable_rows) == 3
    assert all(d.profile.profile_sha256 == newer.profile_sha256 for d in plan.demands)


def test_identical_question_bytes_share_encoding_not_source_identity() -> None:
    old, new = legacy_entry("a"), _entry()
    assert old.content is not None and new.content is not None
    content = CanonicalExperimentItemText(
        text=old.content.text,
        original_source=new.content.original_source,
        text_sha256=old.content.text_sha256,
    )
    plan = plan_embedding_delta(
        (old, replace(new, content=content)),
        space=embedding_space(),
        storage_partition=PARTITION,
        views=("CONTENT_ONLY",),
    )
    assert len(plan.demands) == 2 and len(plan.new_inputs) == 1
    assert plan.demands[0].profile != plan.demands[1].profile


def test_missing_content_and_metadata_do_not_create_placeholder_features() -> None:
    staged = replace(_entry(), content=None, metadata=())
    plan = plan_embedding_delta((staged,), space=embedding_space(), storage_partition=PARTITION)
    assert len(plan.new_inputs) == len(plan.demands) == 1
    assert tuple((v.view, v.reason) for v in plan.unavailable_views) == (
        ("CONTENT_ONLY", "VIEW_NOT_MATERIALIZED"),
        ("METADATA_ONLY", "EMPTY_VIEW"),
    )


def test_registered_review_does_not_claim_accepted_solution_metadata() -> None:
    staged = _entry()
    forged_metadata = tuple(
        field.model_copy(update={"basis": "ACCEPTED_SOLUTION"}) for field in staged.metadata
    )
    with pytest.raises((ValueError, SchemaError)):
        validate_registered_review_embedding_entry(replace(staged, metadata=forged_metadata))


def test_foreign_content_and_forged_hash_are_rejected_before_planning() -> None:
    staged = _entry()
    assert staged.content is not None
    foreign = staged.content.original_source.model_copy(update={"sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="source differs"):
        validate_registered_review_embedding_entry(
            replace(staged, content=staged.content.model_copy(update={"original_source": foreign}))
        )
    with pytest.raises(ValueError, match="text hash"):
        validate_registered_review_embedding_entry(
            replace(staged, content=staged.content.model_copy(update={"text": "반대 결론"}))
        )


@pytest.mark.parametrize("target", ("profile", "content", "metadata"))
def test_undeclared_fields_in_frozen_copies_are_not_erased_before_validation(target: str) -> None:
    staged = _entry()
    if target == "profile":
        forged = replace(staged, profile=staged.profile.model_copy(update={"undeclared": "value"}))
    elif target == "content":
        assert staged.content is not None
        forged = replace(staged, content=staged.content.model_copy(update={"undeclared": "value"}))
    else:
        forged = replace(
            staged, metadata=(staged.metadata[0].model_copy(update={"undeclared": "value"}),)
        )
    with pytest.raises(ValueError, match="undeclared"):
        validate_registered_review_embedding_entry(forged)


def test_cpu_rows_are_not_silently_reused_in_cuda_space() -> None:
    staged = _entry()
    with pytest.raises(EmbeddingDeltaError, match="REGISTERED_ROW_INVALID"):
        plan_embedding_delta(
            (staged,),
            space=embedding_space(device="CUDA"),
            storage_partition=PARTITION,
            registered_rows=_registered_rows(staged),
        )


def test_view_text_preserves_negation_units_and_distinct_reference_values() -> None:
    staged = validate_registered_review_embedding_entry(_entry())
    assert staged.content is not None
    assert registered_review_embedding_view_text(staged, "CONTENT_ONLY") == staged.content.text
    concrete = registered_review_embedding_view_text(staged, "CONCRETE_FACETS")
    assert concrete is not None and "reviewclaim_" not in concrete
    with pytest.raises(ValueError, match="DUPLICATE_SOURCE"):
        plan_embedding_delta((staged, staged), space=embedding_space(), storage_partition=PARTITION)
