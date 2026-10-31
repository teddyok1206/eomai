"""Full source provenance and one encoding identity; no model or live storage."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_contract_values import (
    raw_public_solution_contract_value,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_service.embedding_incremental_plan import (
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan_v3 import (
    build_local_embedding_source_plan_v3,
    build_local_embedding_source_plan_v4,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_source_plan_v3 import parse_local_embedding_source_plan_v3
from eom_workflow.local_embedding_source_plan_v4 import (
    parse_local_embedding_source_plan_v4,
    validate_local_embedding_plan_entries_v4,
    validate_local_embedding_selected_index_coverage_v4,
)
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.test_public_solution_encoding import public_entry
from tests.unit.test_registered_public_solution_embedding import registered_entry
from tests.unit.test_registered_public_solution_index import successor


def plan_value():
    _parent, index, _pointer, _shards = successor()
    sources = tuple(binding.source for binding in index.bindings)
    encodings = {binding.encoding.encoding_sha256: binding.encoding for binding in index.bindings}
    body = dict(
        schema_version="local-embedding-source-plan/4.0",
        corpus_id="corpus_" + "1" * 32,
        graph_snapshot=index.bindings[0].graph_snapshot,
        access_policy_revision_id=index.bindings[0].policy_revision_id,
        access_policy_sha256=index.bindings[0].policy_sha256,
        namespace=PublicSolutionIndexNamespace(
            storage_partition=index.storage_partition,
            space_sha256=index.space.space_sha256,
            recipe_sha256=index.recipe.recipe_sha256,
        ),
        space=index.space,
        recipe=index.recipe,
        sources=sources,
        demands=tuple(
            dict(
                source_revision_id=binding.source.item_revision_id,
                base_analysis_run_id=binding.base_analysis_run_id,
                profile=binding.profile,
                evidence=binding.evidence,
                encoding=binding.encoding,
            )
            for binding in index.bindings
        ),
        missing_solution_report_revision_ids=(),
        unavailable_views=(),
        source_set_sha256=population_sha256(sources),
        encoding_set_sha256=embedding_input_set_sha256(
            tuple(encodings[key] for key in sorted(encodings))
        ),
    )
    return body | {"plan_sha256": content_sha256(body)}


def entries(plan):
    result = []
    for demand, source in zip(plan.demands, plan.sources, strict=True):
        registered = demand.evidence.kind == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
        value = (
            registered_entry()
            if registered
            else public_entry(creative=demand.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT")
        ).model_dump(mode="json")
        value["source"] = source.model_dump(mode="json")
        value["entry_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "entry_sha256"}
        )
        result.append(
            (
                RegisteredPublicSolutionEmbeddingEntry
                if registered
                else PublicSolutionEmbeddingEntry
            ).model_validate(value)
        )
    return tuple(result)


def test_past_creative_ai_demands_reuse_the_same_numeric_identity_but_exact_distinct_reports():
    plan = parse_local_embedding_source_plan_v4(plan_value())
    assert len(plan.sources) == len(plan.demands) == 3
    assert len({demand.encoding for demand in plan.demands}) == 1
    assert len({demand.evidence.kind for demand in plan.demands}) == 3
    staged = entries(plan)
    validate_local_embedding_plan_entries_v4(plan, staged)
    validate_local_embedding_selected_index_coverage_v4(plan, successor()[1])
    assert parse_local_embedding_source_plan_v4(plan.model_dump(mode="json")) == plan
    with pytest.raises(ValueError):
        parse_local_embedding_source_plan_v3(plan.model_dump(mode="json"))


def test_actual_plan_builder_and_delta_reuse_the_registered_numeric_row_for_all_three_sources():
    expected = parse_local_embedding_source_plan_v4(plan_value())
    captured = entries(expected)
    query = EmbeddingRegistryLookup(
        expected.corpus_id,
        expected.namespace,
        expected.graph_snapshot,
        expected.access_policy_revision_id,
        expected.access_policy_sha256,
    )
    resolved = ResolvedEmbeddingLookup(
        query.corpus_id,
        expected.space,
        expected.recipe,
        tuple(entry.source for entry in captured),
        captured,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in captured
        ),
    )
    plan = build_local_embedding_source_plan_v4(
        query,
        resolved,
        target_revision_ids=tuple(source.item_revision_id for source in resolved.sources),
    )
    assert plan == expected
    validate_local_embedding_plan_entries_v4(plan, captured)
    binding = successor()[1].bindings[0]
    existing = RegisteredEmbeddingRow(binding.encoding, binding.row_ref)
    delta = plan_embedding_delta(
        captured,
        space=plan.space,
        storage_partition=plan.namespace.storage_partition,
        registered_rows=(existing,),
        views=("CONCRETE_FACETS",),
    )
    assert len(delta.demands) == 3 and delta.reusable_rows == (existing,)
    assert not delta.new_inputs
    with pytest.raises(ValueError):
        build_local_embedding_source_plan_v3(
            query,
            resolved,
            target_revision_ids=tuple(source.item_revision_id for source in resolved.sources),
        )


@pytest.mark.parametrize(
    "change",
    [
        "wrong_profile",
        "wrong_base",
        "wrong_space",
        "duplicate",
        "missing_coverage",
        "stale_source_hash",
        "foreign_encoding",
        "forged_recipe",
    ],
)
def test_closed_plan_refuses_cross_family_mismatch_and_false_coverage(change):
    value = parse_local_embedding_source_plan_v4(plan_value()).model_dump(mode="json")
    demand = next(
        item
        for item in value["demands"]
        if item["evidence"]["kind"] == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    )
    if change == "wrong_profile":
        demand["profile"]["schema_ref"] = (
            "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
        )
    elif change == "wrong_base":
        demand["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif change == "wrong_space":
        value["namespace"]["space_sha256"] = "sha256:" + "0" * 64
    elif change == "duplicate":
        value["demands"].append(deepcopy(demand))
    elif change == "missing_coverage":
        value["demands"].remove(demand)
    elif change == "stale_source_hash":
        value["source_set_sha256"] = "sha256:" + "0" * 64
    elif change == "foreign_encoding":
        demand["encoding"]["encoding_sha256"] = "sha256:" + "0" * 64
    else:
        value["recipe"]["recipe_sha256"] = "sha256:" + "0" * 64
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError):
        parse_local_embedding_source_plan_v4(value)


def test_larger_metadata_population_is_bounded_without_widening_legacy_raw_contract():
    values = list(range(1025))
    assert raw_public_solution_contract_value(values) == values
    with pytest.raises(ValueError):
        raw_similarity_contract_value(values)
    with pytest.raises(ValueError):
        raw_public_solution_contract_value(list(range(16385)))
    with pytest.raises(ValueError):
        raw_public_solution_contract_value({"bytes": 512.0})
    value = parse_local_embedding_source_plan_v4(plan_value()).model_dump(mode="json")
    value["sources"][0]["artifact_member"]["bytes"] = float(
        value["sources"][0]["artifact_member"]["bytes"]
    )
    # Keep the original integer document hash: a coercing parser could otherwise
    # silently turn this raw float back into the hash's original integer value.
    with pytest.raises(ValueError):
        parse_local_embedding_source_plan_v4(value)
    value = plan_value()
    prototype = value["sources"][0]
    sources = tuple(
        prototype.model_copy(
            update={
                "item_id": "item_" + f"{index:032x}",
                "item_revision_id": "itemrev_" + f"{index:032x}",
            }
        )
        for index in range(1025)
    )
    value.update(
        sources=sources,
        demands=(),
        missing_solution_report_revision_ids=tuple(source.item_revision_id for source in sources),
        source_set_sha256=population_sha256(sources),
        encoding_set_sha256=embedding_input_set_sha256(()),
    )
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    plan = parse_local_embedding_source_plan_v4(value)
    assert len(plan.sources) == len(plan.missing_solution_report_revision_ids) == 1025
    assert not plan.demands  # Missing reports never become invented encodings.


def test_plan_entry_and_selected_index_require_exact_staged_profile_not_just_same_source():
    plan = parse_local_embedding_source_plan_v4(plan_value())
    value = plan.model_dump(mode="json")
    demand = next(
        item
        for item in value["demands"]
        if item["evidence"]["kind"] == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    )
    demand["profile"].update(
        profile_sha256="sha256:" + "f" * 64, profile_revision_id="inferenceprofilerev_" + "f" * 32
    )
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    changed = parse_local_embedding_source_plan_v4(value)
    with pytest.raises(ValueError, match="DEMAND_INVALID"):
        validate_local_embedding_plan_entries_v4(changed, entries(plan))
    with pytest.raises(ValueError, match="DEMAND_INVALID"):
        validate_local_embedding_selected_index_coverage_v4(changed, successor()[1])


def test_source4_schema_is_packaged_closed_and_2020_12():
    root = Path(__file__).resolve().parents[2]
    relative = "local-embedding-source-plan-v4.schema.json"
    assert (root / "schemas/workflow" / relative).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / relative
    ).read_bytes()
    Draft202012Validator.check_schema(
        load_local_embedding_admission_schema("registered-public-source-plan")
    )
