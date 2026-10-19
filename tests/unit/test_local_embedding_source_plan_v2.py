"""Mixed metadata-only source plans; no source authority, DB, IO or numerical execution."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingEntry,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan_v2 import build_local_embedding_source_plan_v2
from eom_identifiers import sha256_bytes
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan
from eom_workflow.local_embedding_source_plan_v2 import (
    AcceptedSolutionEncodingDemandV2,
    LocalEmbeddingSourcePlanV2,
    RegisteredReviewEncodingDemandV2,
    local_embedding_source_plan_v2_bytes,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_entry_source_v2,
    validate_local_embedding_plan_entries_v2,
    validate_local_embedding_selected_index_coverage_v2,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    load_local_embedding_admission_schema,
    validate_local_embedding_admission_message,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_space,
    seal,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_registered_review_embedding_delta import _entry


def inputs(
    view: ExperimentView = "CONCRETE_FACETS",
) -> tuple[EmbeddingRegistryLookup, ResolvedEmbeddingLookup, dict[str, str]]:
    old, new = embedding_entry(), _entry()
    space, recipe = embedding_space(), view_recipe()
    namespace = MixedEmbeddingIndexNamespace(
        storage_partition=PARTITION,
        space_sha256=space.space_sha256,
        view=view,
        recipe_sha256=recipe.recipe_sha256,
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    query = EmbeddingRegistryLookup(
        "corpus_" + "1" * 32,
        namespace,
        old.profile.source_basis.graph_snapshot,
        "accessrev_" + "e" * 32,
        sha("e"),
    )
    sources = tuple(entry.profile.source_basis.source for entry in (old, new))
    return (
        query,
        ResolvedEmbeddingLookup(query.corpus_id, space, recipe, sources, (old, new)),
        {
            old.profile.source_basis.source.item_revision_id: (
                old.profile.source_basis.solution_evidence.base_analysis_run_id
            ),
            new.profile.source_basis.source.item_revision_id: "analysisrun_" + "c" * 32,
        },
    )


def build(view: ExperimentView = "CONCRETE_FACETS") -> LocalEmbeddingSourcePlanV2:
    query, resolved, bases = inputs(view)
    return build_local_embedding_source_plan_v2(
        query,
        resolved,
        target_revision_ids=tuple(source.item_revision_id for source in resolved.sources),
        base_analysis_run_ids=bases,
    )


@pytest.mark.parametrize("view", ["CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"])
def test_two_genuine_branches_roundtrip_without_fake_v10_or_duplicate_text(
    view: ExperimentView,
) -> None:
    query, resolved, bases = inputs(view)
    plan = build(view)
    assert parse_local_embedding_source_plan_v2(plan) == plan
    assert json.loads(local_embedding_source_plan_v2_bytes(plan)) == plan.model_dump(mode="json")
    assert isinstance(plan.demands[0], RegisteredReviewEncodingDemandV2)
    assert isinstance(plan.demands[1], AcceptedSolutionEncodingDemandV2)
    assert all(
        demand.base_analysis_run_id == bases[demand.source_revision_id] for demand in plan.demands
    )
    assert plan.namespace == query.namespace
    assert plan.space == resolved.space
    assert all("text" not in demand.model_dump(mode="json") for demand in plan.demands)
    review = plan.demands[0]
    assert not hasattr(review, "solution_evidence")
    assert review.base_analysis_run_id != review.review_evidence.review.job_id
    validate_local_embedding_plan_entries_v2(plan, resolved.entries)


def test_selection_order_and_dictionary_order_do_not_change_canonical_bytes() -> None:
    query, resolved, bases = inputs()
    plan = build()
    other = build_local_embedding_source_plan_v2(
        query,
        replace(resolved, entries=resolved.entries[::-1], sources=resolved.sources[::-1]),
        target_revision_ids=tuple(source.item_revision_id for source in resolved.sources[::-1]),
        base_analysis_run_ids=dict(reversed(tuple(bases.items()))),
    )
    assert local_embedding_source_plan_v2_bytes(plan) == local_embedding_source_plan_v2_bytes(other)


def test_seed_subset_accepts_full_current_base_map_without_expanding_population() -> None:
    query, resolved, bases = inputs()
    selected = resolved.sources[1].item_revision_id
    plan = build_local_embedding_source_plan_v2(
        query, resolved, target_revision_ids=(selected,), base_analysis_run_ids=bases
    )
    assert tuple(source.item_revision_id for source in plan.sources) == (selected,)
    assert len(plan.demands) == 1
    assert isinstance(plan.demands[0], RegisteredReviewEncodingDemandV2)


def test_missing_report_and_unavailable_original_view_remain_distinct() -> None:
    query, resolved, bases = inputs("CONTENT_ONLY")
    new = resolved.entries[1]
    assert isinstance(new, RegisteredReviewEmbeddingEntry)
    new = new.model_copy(update={"content": None})
    plan = build_local_embedding_source_plan_v2(
        query,
        replace(resolved, entries=(new,)),
        target_revision_ids=tuple(bases),
        base_analysis_run_ids=bases,
    )
    assert plan.demands == ()
    assert plan.missing_solution_report_revision_ids == (resolved.sources[0].item_revision_id,)
    assert tuple((row.source_revision_id, row.reason) for row in plan.unavailable_views) == (
        (resolved.sources[1].item_revision_id, "VIEW_NOT_MATERIALIZED"),
    )


@pytest.mark.parametrize(
    "failure",
    [
        "truncated",
        "duplicate_source",
        "duplicate_entry",
        "foreign_entry",
        "foreign_target",
        "duplicate_target",
        "missing_base",
        "foreign_base",
        "review_job_as_base",
        "wrong_old_base",
        "old_namespace",
        "wrong_corpus",
    ],
)
def test_invalid_capture_selection_and_genuine_base_mapping_fail(failure: str) -> None:
    query, resolved, bases = inputs()
    selected = tuple(bases)
    if failure == "truncated":
        resolved = replace(resolved, truncated=True)
    elif failure == "duplicate_source":
        resolved = replace(resolved, sources=resolved.sources + resolved.sources[:1])
    elif failure == "duplicate_entry":
        resolved = replace(resolved, entries=resolved.entries + resolved.entries[:1])
    elif failure == "foreign_entry":
        resolved = replace(resolved, sources=resolved.sources[:1])
    elif failure == "foreign_target":
        selected = ("itemrev_" + "f" * 32,)
    elif failure == "duplicate_target":
        selected = (selected[0], selected[0])
    elif failure == "missing_base":
        del bases[selected[0]]
    elif failure == "foreign_base":
        bases["itemrev_" + "f" * 32] = "analysisrun_" + "f" * 32
    elif failure == "review_job_as_base":
        new = resolved.entries[1]
        assert isinstance(new, RegisteredReviewEmbeddingEntry)
        bases[selected[1]] = new.profile.source_basis.review_evidence.review.job_id
    elif failure == "wrong_old_base":
        bases[selected[0]] = "analysisrun_" + "f" * 32
    elif failure == "old_namespace":
        query = replace(query, namespace=native_fixture().plan.namespace)
    else:
        resolved = replace(resolved, corpus_id="corpus_" + "f" * 32)
    with pytest.raises(ValueError):
        build_local_embedding_source_plan_v2(
            query, resolved, target_revision_ids=selected, base_analysis_run_ids=bases
        )


@pytest.mark.parametrize("family", ["legacy", "review"])
@pytest.mark.parametrize("has_content", [True, False])
def test_source_hash_rejected_even_when_original_view_is_unavailable(
    family: str, has_content: bool
) -> None:
    query, resolved, bases = inputs("CONTENT_ONLY")
    index = 0 if family == "legacy" else 1
    source = resolved.sources[index]
    document = source.model_dump(mode="json")
    document["artifact_member"]["sha256"] = sha("f")
    changed_source = type(source).model_validate(document)
    entry = resolved.entries[index]
    if not has_content:
        entry = entry.model_copy(update={"content": None})
    sources = list(resolved.sources)
    sources[index] = changed_source
    entries = list(resolved.entries)
    entries[index] = entry
    with pytest.raises(ValueError, match="exact source/Graph/projection"):
        build_local_embedding_source_plan_v2(
            query,
            replace(resolved, sources=tuple(sources), entries=tuple(entries)),
            target_revision_ids=tuple(bases),
            base_analysis_run_ids=bases,
        )


@pytest.mark.parametrize("failure", ["graph", "projection"])
def test_entry_exact_graph_and_namespace_projection_fences(failure: str) -> None:
    query, resolved, _bases = inputs()
    graph = query.graph_snapshot
    projection = query.namespace.projection_version
    if failure == "graph":
        graph = graph.model_copy(update={"graph_snapshot_revision_id": "graphrev_" + "f" * 32})
    else:
        projection = "accepted-solution-comparison/1.0"
    for source, entry in zip(resolved.sources, resolved.entries, strict=True):
        with pytest.raises(ValueError):
            validate_local_embedding_entry_source_v2(
                source, entry, graph_snapshot=graph, projection_version=projection
            )


@pytest.mark.parametrize(
    "failure",
    ["hash", "namespace", "coverage", "source", "old_base", "cross_branch", "extra", "bool"],
)
def test_schema_and_semantic_tampering_fail_after_resealing(failure: str) -> None:
    body = copy.deepcopy(build().model_dump(mode="json"))
    review, old = body["demands"]
    if failure == "hash":
        body["plan_sha256"] = sha("f")
    elif failure == "namespace":
        body["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    elif failure == "coverage":
        body["demands"] = []
    elif failure == "source":
        review["review_evidence"]["source"]["item_id"] = "item_" + "f" * 32
    elif failure == "old_base":
        old["base_analysis_run_id"] = "analysisrun_" + "f" * 32
    elif failure == "cross_branch":
        review["solution_evidence"] = old["solution_evidence"]
    elif failure == "extra":
        review["authority"] = "ADMIN"
    else:
        old["base_analysis_run_id"] = True
    if failure != "hash":
        body = seal(body, "plan_sha256")
    with pytest.raises(LocalEmbeddingAdmissionContractError, match="CONTRACT_INVALID"):
        parse_local_embedding_source_plan_v2(body)


@pytest.mark.parametrize(
    "failure", ["extra", "profile", "encoding", "wrong_family", "missing", "duplicate"]
)
def test_staged_entries_are_exact_not_lossy_model_copy_or_foreign_family(failure: str) -> None:
    query, resolved, _bases = inputs()
    entries = list(resolved.entries)
    if failure == "extra":
        entries[1] = entries[1].model_copy(update={"undeclared_authority": True})
    elif failure == "profile":
        plan = build().model_copy(update={"demands": tuple(reversed(build().demands))})
        with pytest.raises(LocalEmbeddingAdmissionContractError):
            validate_local_embedding_plan_entries_v2(plan, tuple(entries))
        return
    elif failure == "encoding":
        body = build().model_dump(mode="json")
        body["demands"][0]["encoding"]["input_text_sha256"] = sha("f")
        body["demands"][0]["encoding"] = seal(body["demands"][0]["encoding"], "encoding_sha256")
        from eom_catalog_contracts.inference_transfer_embedding import (
            EmbeddingEncodingIdentity,
            embedding_input_set_sha256,
        )

        encodings = tuple(
            sorted(
                (EmbeddingEncodingIdentity.model_validate(d["encoding"]) for d in body["demands"]),
                key=lambda row: row.encoding_sha256,
            )
        )
        body["encoding_set_sha256"] = embedding_input_set_sha256(encodings)
        plan = parse_local_embedding_source_plan_v2(seal(body, "plan_sha256"))
        with pytest.raises(ValueError, match="view text"):
            validate_local_embedding_plan_entries_v2(plan, tuple(entries))
        return
    elif failure == "wrong_family":
        entries[1] = entries[0]
    elif failure == "missing":
        entries.pop()
    else:
        entries.append(entries[0])
    with pytest.raises((ValueError, TypeError)):
        validate_local_embedding_plan_entries_v2(build(), tuple(entries))
    assert query.namespace.projection_version == "mixed-solution-comparison/2.0"


def test_selected_mixed_index_covers_exact_original_branches_and_real_bases() -> None:
    _new, _binding, _shard, _pointer, index = mixed_embedding_case()
    plan = build()
    # This fixture demonstrates both wire branches; registration here must use
    # one current policy, unlike its independent default legacy binding fixture.
    document = index.model_dump(mode="json")
    document["bindings"] = [
        seal(
            value
            | {
                "policy_revision_id": plan.access_policy_revision_id,
                "policy_sha256": plan.access_policy_sha256,
            },
            "binding_sha256",
        )
        for value in document["bindings"]
    ]
    index = MixedEmbeddingIndexManifest.model_validate(seal(document, "index_sha256"))
    validate_local_embedding_selected_index_coverage_v2(plan, index)
    document = index.model_dump(mode="json")
    review = document["bindings"][0]
    review["base_analysis_run_id"] = "analysisrun_" + "f" * 32
    document["bindings"][0] = seal(review, "binding_sha256")
    changed = MixedEmbeddingIndexManifest.model_validate(seal(document, "index_sha256"))
    with pytest.raises(ValueError, match="review evidence"):
        validate_local_embedding_selected_index_coverage_v2(plan, changed)


def test_schema_mirror_and_released_plan1_hash_and_parser_are_unchanged() -> None:
    root = Path(__file__).resolve().parents[2]
    canonical = root / "schemas/workflow/local-embedding-source-plan-v2.schema.json"
    mirror = (
        root / "packages/workflow/eom_workflow/resources/local-embedding-source-plan-v2.schema.json"
    )
    assert canonical.read_bytes() == mirror.read_bytes()
    assert (
        sha256_bytes(canonical.read_bytes())
        == "sha256:cbf7c6647484bc59efa1a857669ebb67aa6cf49a2a1bfaa28a326bca364f88d0"
    )
    schema = load_local_embedding_admission_schema("mixed-source-plan")
    Draft202012Validator.check_schema(schema)
    validate_local_embedding_admission_message("mixed-source-plan", build().model_dump(mode="json"))
    old_path = (
        root / "packages/workflow/eom_workflow/resources/local-embedding-source-plan-v1.schema.json"
    )
    assert (
        sha256_bytes(old_path.read_bytes())
        == "sha256:8ba4b285504c2c0c4ad668def7b276c71d900bf889a498c7cb6d6c24d822372e"
    )
    original = native_fixture().plan
    assert parse_local_embedding_source_plan(original.model_dump(mode="json")) == original
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_source_plan(build().model_dump(mode="json"))
