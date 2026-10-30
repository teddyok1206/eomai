"""Public INDEX pointers reuse resource frames without masquerading as legacy evidence."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_text import build_public_solution_text
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v3
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.embedding_batch_plan import EmbeddingBatchPlanRequest, EmbeddingBatchSelection
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_selection_read_maximum,
    embedding_batch_selection_schema_ref,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
)
from eom_workflow.embedding_batch_plan_v11 import (
    MAX_BULK_BATCH_SELECTION_BYTES,
    EmbeddingBatchPlanRequestV11,
    EmbeddingBatchSelectionV11,
)
from eom_workflow.embedding_batch_plan_v12 import (
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_batch_plan_v13 import (
    BATCH_PLAN_V13_PROTOCOL,
    BATCH_PLAN_V13_SCHEMA_REF,
    BATCH_PLAN_V13_SCHEMA_SHA256,
    BATCH_SELECTION_V13_SCHEMA_REF,
    EmbeddingBatchPlanRequestV13,
    EmbeddingBatchSelectionV13,
    PublicSolutionBatchAnchor,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow_runner.embedding_batch_plan_admission import CatalogEmbeddingBatchPlanAdmission
from eom_workflow_runner.local_embedding_submission import LocalEmbeddingCoverageOnly

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_local_embedding_source_plan_v3 import inputs

ROOT = Path(__file__).resolve().parents[2]


def public_case():
    query, resolved, _ = inputs()
    original = planning_case(purpose="INDEX")
    selection = EmbeddingBatchSelectionV13.model_validate(
        seal(
            original.selection.model_dump(mode="json")
            | {
                "schema_version": BATCH_PLAN_V13_PROTOCOL,
                "anchors": [
                    PublicSolutionBatchAnchor.from_entry(entry).model_dump(mode="json")
                    for entry in resolved.entries
                ],
                "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
                "access_policy_revision_id": query.policy_revision_id,
                "recipe": resolved.recipe.model_dump(mode="json"),
                "views": ["CONCRETE_FACETS"],
            },
            "selection_sha256",
        )
    )
    policy = EmbeddingDeviceRoutingPolicy.model_validate(
        seal(
            original.policy.model_dump(mode="json")
            | {"view_recipe_sha256": resolved.recipe.recipe_sha256},
            "policy_sha256",
        )
    )
    request = EmbeddingBatchPlanRequestV13.model_validate(
        seal(
            original.request.model_dump(mode="json")
            | {
                "schema_version": BATCH_PLAN_V13_PROTOCOL,
                "selection_manifest": member(
                    "selection.json", BATCH_SELECTION_V13_SCHEMA_REF, selection, "1"
                ).model_dump(mode="json"),
                "selection_sha256": selection.selection_sha256,
                "routing_policy": member(
                    "policy.json", policy_pointer_schema(), policy, "2"
                ).model_dump(mode="json"),
                "routing_policy_sha256": policy.policy_sha256,
                "child_selection_sha256s": list(selection.child_selection_sha256s),
            },
            "request_sha256",
        )
    )
    return selection, request, policy, resolved


def policy_pointer_schema():
    return "eom://schemas/workflow/embedding-device-routing/1.0"


def test_public_index_roundtrip_and_old_wire_rejection():
    selection, request, policy, resolved = public_case()
    assert parse_embedding_batch_selection(selection) == selection
    assert parse_embedding_batch_plan_request(request) == request
    assert embedding_batch_selection_schema_ref(selection) == BATCH_SELECTION_V13_SCHEMA_REF
    assert embedding_batch_plan_schema_identity(request) == (
        BATCH_PLAN_V13_PROTOCOL,
        BATCH_PLAN_V13_SCHEMA_SHA256,
    )
    assert embedding_batch_selection_read_maximum(request) == MAX_BULK_BATCH_SELECTION_BYTES
    validate_embedding_batch_plan_controls(request, selection, policy)
    CatalogEmbeddingBatchPlanAdmission._validate_sources(selection, resolved)
    assert {anchor.evidence.kind for anchor in selection.anchors} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
    }
    assert "public_solution" not in canonical_json_bytes(selection).decode()
    for parser, body in (
        (EmbeddingBatchSelection, selection),
        (EmbeddingBatchSelectionV11, selection),
        (EmbeddingBatchSelectionV12, selection),
        (EmbeddingBatchPlanRequest, request),
        (EmbeddingBatchPlanRequestV11, request),
        (EmbeddingBatchPlanRequestV12, request),
    ):
        with pytest.raises(ValueError):
            parser.model_validate(body.model_dump(mode="json"))


def test_schema_mirror_and_pin():
    name = "embedding-batch-plan-v1.3.schema.json"
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == BATCH_PLAN_V13_SCHEMA_SHA256
    assert BATCH_SELECTION_V13_SCHEMA_REF == BATCH_PLAN_V13_SCHEMA_REF + "#/$defs/selection"


@pytest.mark.parametrize(
    "fault", ["query", "view", "duplicate", "legacy_recipe", "hash", "unknown"]
)
def test_public_selection_is_closed(fault):
    selection, _, _, _ = public_case()
    body = selection.model_dump(mode="json")
    if fault == "query":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "view":
        body["views"] = ["CONTENT_ONLY"]
    elif fault == "duplicate":
        body["anchors"].append(deepcopy(body["anchors"][0]))
    elif fault == "legacy_recipe":
        body["recipe"] = planning_case(purpose="INDEX").selection.recipe.model_dump(mode="json")
    elif fault == "unknown":
        body["latest"] = True
    else:
        body["selection_sha256"] = "sha256:" + "f" * 64
    if fault != "hash":
        body = seal(body, "selection_sha256")
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV13.model_validate(body)


@pytest.mark.parametrize(
    "fault", ["entry", "source", "base", "lineage", "graph", "missing", "duplicate", "truncated"]
)
def test_admission_rechecks_exact_report_identity_and_graph(fault):
    selection, _, _, resolved = public_case()
    entries = list(resolved.entries)
    creative_index = next(
        index
        for index, entry in enumerate(entries)
        if entry.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT"
    )
    body = entries[creative_index].model_dump(mode="json")
    if fault == "entry":
        body["public_solution"] = build_public_solution_text(("다른 풀이",)).model_dump(mode="json")
    if fault == "source":
        resolved = replace(resolved, sources=resolved.sources[:1])
    elif fault == "base":
        body["base_analysis_run_id"] = "analysisrun_" + "f" * 32
    elif fault == "lineage":
        body["evidence"]["lineage_sha256"] = "sha256:" + "f" * 64
    elif fault == "graph":
        body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif fault == "missing":
        entries.pop()
    elif fault == "duplicate":
        entries.append(entries[1])
    else:
        resolved = replace(resolved, truncated=True)
    if fault in {"entry", "base", "lineage", "graph"}:
        entries[creative_index] = PublicSolutionEmbeddingEntry.model_validate(
            seal(body, "entry_sha256")
        )
    resolved = replace(resolved, entries=tuple(entries))
    with pytest.raises(ValueError):
        CatalogEmbeddingBatchPlanAdmission._validate_sources(selection, resolved)


def test_same_text_does_not_merge_source_proof_or_original_order():
    selection, request, _, resolved = public_case()
    assert resolved.entries[0].public_solution == resolved.entries[1].public_solution
    assert selection.anchors[0].profile != selection.anchors[1].profile
    reordered = EmbeddingBatchSelectionV13.model_validate(
        seal(
            selection.model_dump(mode="json")
            | {
                "anchors": [
                    anchor.model_dump(mode="json") for anchor in reversed(selection.anchors)
                ]
            },
            "selection_sha256",
        )
    )
    assert reordered.selection_sha256 != request.selection_sha256
    assert reordered.child_selection_sha256s != selection.child_selection_sha256s
    assert content_sha256(selection.model_dump(mode="json")) != selection.selection_sha256


def test_public_coverage_only_does_not_submit_zero_vector_work():
    query, resolved, _ = inputs()
    entries = tuple(
        PublicSolutionEmbeddingEntry.model_validate(
            seal(
                entry.model_dump(mode="json")
                | {"public_solution": build_public_solution_text(()).model_dump(mode="json")},
                "entry_sha256",
            )
        )
        for entry in resolved.entries
    )
    resolved = replace(resolved, entries=entries)
    plan = build_local_embedding_source_plan_v3(
        query,
        resolved,
        target_revision_ids=tuple(sorted(source.item_revision_id for source in resolved.sources)),
    )
    assert not plan.demands
    assert LocalEmbeddingCoverageOnly(plan).plan == plan


def test_public_batch_has_1024_pointer_limit_independent_of_16384_member_index_head():
    selection, _, _, _ = public_case()
    template = selection.anchors[0].model_dump(mode="json")
    anchors = []
    for ordinal in range(1024):
        source = template["source"] | {
            "item_id": "item_" + f"{ordinal:032x}",
            "item_revision_id": "itemrev_" + f"{ordinal:032x}",
        }
        logical = content_sha256(
            {
                "item_id": source["item_id"],
                "projection_version": "public-solution-text/1.0",
            }
        )
        anchors.append(
            template
            | {
                "source": source,
                "profile": template["profile"]
                | {"profile_id": "inferenceprofile_" + logical[7:39]},
            }
        )
    body = seal(selection.model_dump(mode="json") | {"anchors": anchors}, "selection_sha256")
    checked = EmbeddingBatchSelectionV13.model_validate(body)
    assert len(checked.anchors) == 1024
    assert len(canonical_json_bytes(checked)) < MAX_BULK_BATCH_SELECTION_BYTES
    body["anchors"].append(anchors[0])
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV13.model_validate(seal(body, "selection_sha256"))
