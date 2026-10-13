"""Pure synthetic plan construction; no source authority or numerical execution."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_identifiers import canonical_json_bytes

from tests.unit.local_embedding_admission_fixtures import native_fixture


def inputs() -> tuple[EmbeddingRegistryLookup, ResolvedEmbeddingLookup]:
    fixture = native_fixture()
    plan = fixture.plan
    return (
        EmbeddingRegistryLookup(
            plan.corpus_id,
            plan.namespace,
            plan.graph_snapshot,
            plan.access_policy_revision_id,
            plan.access_policy_sha256,
        ),
        ResolvedEmbeddingLookup(
            plan.corpus_id, plan.space, plan.recipe, plan.sources, fixture.entries
        ),
    )


def test_rebuilds_existing_contract_exactly_and_input_order_does_not_change_bytes() -> None:
    query, resolved = inputs()
    ids = tuple(source.item_revision_id for source in resolved.sources)
    expected = native_fixture().plan
    built = build_local_embedding_source_plan(query, resolved, target_revision_ids=ids)
    assert built == expected
    reversed_input = replace(
        resolved, sources=resolved.sources[::-1], entries=resolved.entries[::-1]
    )
    other = build_local_embedding_source_plan(query, reversed_input, target_revision_ids=ids[::-1])
    assert canonical_json_bytes(built.model_dump(mode="json")) == canonical_json_bytes(
        other.model_dump(mode="json")
    )


def test_bounded_seed_is_exact_subset_not_implicit_full_corpus() -> None:
    query, resolved = inputs()
    selected = resolved.sources[1].item_revision_id
    plan = build_local_embedding_source_plan(query, resolved, target_revision_ids=(selected,))
    assert tuple(source.item_revision_id for source in plan.sources) == (selected,)
    assert len(plan.demands) == 1
    assert plan.source_set_sha256 != native_fixture().plan.source_set_sha256


def test_missing_report_and_unavailable_content_are_distinct_exhaustive_coverage() -> None:
    query, resolved = inputs()
    ids = tuple(source.item_revision_id for source in resolved.sources)
    no_content = StagedExperimentEntry.model_validate(
        resolved.entries[0].model_dump(mode="json") | {"content": None}
    )
    plan = build_local_embedding_source_plan(
        query, replace(resolved, entries=(no_content,)), target_revision_ids=ids
    )
    assert plan.demands == ()
    assert plan.missing_solution_report_revision_ids == (ids[1],)
    assert [(value.source_revision_id, value.reason) for value in plan.unavailable_views] == [
        (ids[0], "VIEW_NOT_MATERIALIZED")
    ]


def test_newly_available_report_changes_plan_instead_of_preserving_false_missing() -> None:
    query, resolved = inputs()
    ids = tuple(source.item_revision_id for source in resolved.sources)
    before = build_local_embedding_source_plan(
        query, replace(resolved, entries=()), target_revision_ids=ids
    )
    after = build_local_embedding_source_plan(query, resolved, target_revision_ids=ids)
    assert before.plan_sha256 != after.plan_sha256
    assert before.missing_solution_report_revision_ids == ids
    assert after.missing_solution_report_revision_ids == ()


def test_same_encoding_keeps_distinct_source_profile_bindings() -> None:
    query, resolved = inputs()
    namespace = query.namespace.model_copy(update={"view": "METADATA_ONLY"})
    plan = build_local_embedding_source_plan(
        replace(query, namespace=namespace),
        resolved,
        target_revision_ids=tuple(source.item_revision_id for source in resolved.sources),
    )
    assert len(plan.demands) == 2
    assert plan.demands[0].encoding == plan.demands[1].encoding
    assert plan.demands[0].profile != plan.demands[1].profile


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_source",
        "duplicate_entry",
        "foreign_entry",
        "truncated",
        "corpus",
        "empty",
        "target_missing",
        "target_duplicate",
    ],
)
def test_invalid_capture_or_selection_fails_explicitly(case: str) -> None:
    query, resolved = inputs()
    ids = tuple(source.item_revision_id for source in resolved.sources)
    if case == "duplicate_source":
        resolved = replace(resolved, sources=(resolved.sources[0],) * 2)
    elif case == "duplicate_entry":
        resolved = replace(resolved, entries=(resolved.entries[0],) * 2)
    elif case == "foreign_entry":
        resolved = replace(resolved, sources=(resolved.sources[0],), entries=(resolved.entries[1],))
    elif case == "truncated":
        resolved = replace(resolved, truncated=True)
    elif case == "corpus":
        resolved = replace(resolved, corpus_id="corpus_" + "e" * 32)
    elif case == "empty":
        ids = ()
    elif case == "target_missing":
        ids = ("itemrev_" + "f" * 32,)
    else:
        ids = (ids[0], ids[0])
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        build_local_embedding_source_plan(query, resolved, target_revision_ids=ids)


@pytest.mark.parametrize("has_content", [True, False])
def test_source_hash_mismatch_rejected_even_if_view_is_unavailable(has_content: bool) -> None:
    query, resolved = inputs()
    original = resolved.sources[0]
    body = original.model_dump(mode="json")
    body["artifact_member"]["sha256"] = "sha256:" + "f" * 64
    source = type(original).model_validate(body)
    entry = resolved.entries[0]
    if not has_content:
        entry = StagedExperimentEntry.model_validate(
            entry.model_dump(mode="json") | {"content": None}
        )
    with pytest.raises(ValueError, match="exact source/Graph/projection"):
        build_local_embedding_source_plan(
            query,
            replace(resolved, sources=(source,), entries=(entry,)),
            target_revision_ids=(source.item_revision_id,),
        )
