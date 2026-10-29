"""Public report plans preserve real families and reuse actual numerical inputs."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v3
from eom_catalog_service.public_solution_index_assembly import (
    assemble_public_solution_index_revision,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from eom_workflow.local_embedding_source_plan_v2 import parse_local_embedding_source_plan_v2
from eom_workflow.local_embedding_source_plan_v3 import (
    parse_local_embedding_source_plan_v3,
    validate_local_embedding_plan_entries_v3,
    validate_local_embedding_selected_index_coverage_v3,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record
from tests.unit.test_public_solution_encoding import public_entry
from tests.unit.test_public_solution_index_assembly import assemble, setup


def inputs():
    data = setup()
    entries, _rows, _shards, namespace, space = data
    first = entries[0]
    query = EmbeddingRegistryLookup(
        "corpus_" + "1" * 32,
        namespace,
        first.graph_snapshot,
        first.policy_revision_id,
        first.policy_sha256,
    )
    resolved = ResolvedEmbeddingLookup(
        query.corpus_id,
        space,
        first.recipe,
        tuple(entry.source for entry in entries),
        entries,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in entries
        ),
    )
    return query, resolved, data


def build(query, resolved):
    return build_local_embedding_source_plan_v3(
        query,
        resolved,
        target_revision_ids=tuple(sorted(source.item_revision_id for source in resolved.sources)),
    )


def test_plan_preserves_two_source_proofs_for_the_same_numeric_input():
    query, resolved, data = inputs()
    plan = build(query, resolved)
    assert len(plan.demands) == 2
    assert len({demand.encoding for demand in plan.demands}) == 1
    assert {demand.evidence.kind for demand in plan.demands} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
    }
    assert all("text" not in demand.model_dump(mode="json") for demand in plan.demands)
    assert parse_local_embedding_source_plan_v3(plan) == plan
    validate_local_embedding_plan_entries_v3(plan, resolved.entries)
    validate_local_embedding_selected_index_coverage_v3(plan, assemble(data).index)
    direct = assemble(data)
    metadata = assemble_public_solution_index_revision(
        plan,
        available_rows=data[1],
        shards=data[2],
        index_id=direct.index.index_id,
        index_revision_id=direct.index.index_revision_id,
        previous_manifest=None,
        created_at=NOW,
    )
    assert metadata == direct
    for parse_old in (parse_local_embedding_source_plan, parse_local_embedding_source_plan_v2):
        with pytest.raises(ValueError):
            parse_old(plan.model_dump(mode="json"))


def test_native_and_registry_serialization_keep_original_page_and_occurrence_provenance():
    record = snapshot_v3_record()
    value = public_entry().model_dump(mode="json")
    value["source"] = record.source.model_dump(mode="json")
    entry = PublicSolutionEmbeddingEntry.model_validate(seal(value, "entry_sha256"))
    assert entry.source == record.source
    assert entry.model_dump(mode="json")["source"] == value["source"]
    assert "page_inputs" in entry.model_dump(mode="json")["source"]
    query, resolved, _data = inputs()
    source = entry.source
    resolved = replace(
        resolved,
        sources=(source,),
        entries=(entry,),
        base_analysis_run_ids=((source.item_revision_id, entry.base_analysis_run_id),),
    )
    plan = build(query, resolved)
    assert plan.model_dump(mode="json")["sources"][0] == value["source"]
    assert parse_local_embedding_source_plan_v3(plan).sources[0] == source
    assert plan.source_set_sha256 == population_sha256((source,))


@pytest.mark.parametrize(
    "change",
    (
        "duplicate_base",
        "foreign_base",
        "missing_base",
        "wrong_base",
        "wrong_recipe",
        "wrong_policy",
        "duplicate_entry",
        "truncated",
    ),
)
def test_false_or_incomplete_capture_cannot_become_a_plan(change):
    query, resolved, _ = inputs()
    first = resolved.entries[0]
    if change == "duplicate_base":
        resolved = replace(resolved, base_analysis_run_ids=resolved.base_analysis_run_ids * 2)
    elif change == "foreign_base":
        resolved = replace(
            resolved,
            base_analysis_run_ids=(
                *resolved.base_analysis_run_ids,
                ("itemrev_" + "f" * 32, first.base_analysis_run_id),
            ),
        )
    elif change == "missing_base":
        resolved = replace(resolved, base_analysis_run_ids=())
    elif change == "wrong_base":
        resolved = replace(
            resolved,
            base_analysis_run_ids=tuple(
                (source, "analysisrun_" + "f" * 32) for source, _ in resolved.base_analysis_run_ids
            ),
        )
    elif change == "wrong_recipe":
        query = replace(
            query,
            namespace=query.namespace.model_copy(update={"recipe_sha256": "sha256:" + "f" * 64}),
        )
    elif change == "wrong_policy":
        query = replace(query, policy_sha256="sha256:" + "f" * 64)
    elif change == "duplicate_entry":
        resolved = replace(resolved, entries=resolved.entries * 2)
    else:
        resolved = replace(resolved, truncated=True)
    with pytest.raises(ValueError):
        build(query, resolved)


def test_missing_report_and_absent_public_text_are_distinct_without_fallback():
    query, resolved, _ = inputs()
    first = resolved.entries[0]
    value = first.model_dump(mode="json")
    value["public_solution"] = {
        "schema_version": "public-solution-text/1.0",
        "status": "UNAVAILABLE",
        "text": None,
        "text_sha256": None,
    }
    unavailable = PublicSolutionEmbeddingEntry.model_validate(seal(value, "entry_sha256"))
    plan = build(query, replace(resolved, entries=(unavailable,)))
    assert plan.demands == ()
    assert plan.missing_solution_report_revision_ids == (
        resolved.entries[1].source.item_revision_id,
    )
    assert tuple(row.source_revision_id for row in plan.unavailable_views) == (
        first.source.item_revision_id,
    )


def test_changed_staged_text_or_extra_source_is_rejected():
    query, resolved, _ = inputs()
    plan = build(query, resolved)
    value = resolved.entries[0].model_dump(mode="json")
    value["public_solution"]["text"] = "반대의 결론이다."
    value["public_solution"]["text_sha256"] = content_sha256(value["public_solution"]["text"])
    changed = PublicSolutionEmbeddingEntry.model_validate(seal(value, "entry_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_plan_entries_v3(plan, (changed, *resolved.entries[1:]))
    with pytest.raises(ValueError):
        validate_local_embedding_plan_entries_v3(plan, (*resolved.entries, resolved.entries[0]))


def test_new_plan_schema_is_a_pinned_package_resource():
    root = Path(__file__).resolve().parents[2]
    assert (root / "schemas/workflow/local-embedding-source-plan-v3.schema.json").read_bytes() == (
        root / "packages/workflow/eom_workflow/resources/local-embedding-source-plan-v3.schema.json"
    ).read_bytes()
    assert canonical_json_bytes(build(*inputs()[:2]))
