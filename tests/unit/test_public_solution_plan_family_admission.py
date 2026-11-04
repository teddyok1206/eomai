"""Selected-only captures preserve exact public plan families, never fresh authority."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v4
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_request_v4 import parse_local_embedding_workflow_request_v4
from eom_workflow.local_embedding_source_plan_v4 import parse_local_embedding_source_plan_v4
from eom_workflow_runner import local_embedding_owner_admission as admission

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_source_plan_v4 import entries
from tests.unit.test_native_office_public_embedding import native_entry
from tests.unit.test_registered_public_solution_request import request_case


def case():
    original, request, plan = request_case()
    captured = tuple(
        native_entry(entry) if entry.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT" else entry
        for entry in entries(plan)
    )
    query = admission.EmbeddingRegistryLookup(
        plan.corpus_id,
        plan.namespace,
        plan.graph_snapshot,
        plan.access_policy_revision_id,
        plan.access_policy_sha256,
    )
    from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingLookup

    full = ResolvedEmbeddingLookup(
        plan.corpus_id,
        plan.space,
        plan.recipe,
        tuple(entry.source for entry in captured),
        captured,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in captured
        ),
    )
    selected = tuple(
        entry for entry in captured if entry.schema_version != "public-solution-embedding-entry/3.0"
    )
    targets = tuple(entry.source.item_revision_id for entry in selected)
    subset = replace(
        full,
        sources=tuple(entry.source for entry in selected),
        entries=selected,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in selected
        ),
    )
    return NS(**locals())


def test_selected_capture_rebuilds_original_discovery_family_without_changing_its_hash():
    value = case()
    full = build_local_embedding_source_plan_v4(
        value.query, value.full, target_revision_ids=value.targets
    )
    subset = build_local_embedding_source_plan_v4(
        value.query, value.subset, target_revision_ids=value.targets, plan_version="5.0"
    )
    assert full == subset
    assert full.schema_version == "local-embedding-source-plan/5.0"


def test_previously_valid_family5_legacy_subset_rebuilds_without_retagging_history():
    value = case()
    legacy = build_local_embedding_source_plan_v4(
        value.query, value.subset, target_revision_ids=value.targets
    )
    raw = legacy.model_dump(mode="json") | {"schema_version": "local-embedding-source-plan/5.0"}
    historical = parse_local_embedding_source_plan_v4(seal(raw, "plan_sha256"))
    rebuilt = build_local_embedding_source_plan_v4(
        value.query, value.subset, target_revision_ids=value.targets, plan_version="5.0"
    )
    assert rebuilt == historical and rebuilt.encoding_set_sha256 == legacy.encoding_set_sha256
    assert rebuilt.sources == legacy.sources and rebuilt.demands == legacy.demands


def test_owner_revalidates_original_request_family_instead_of_auto_downgrading(monkeypatch):
    value = case()
    # This is an exact, schema-valid historical plan5 with only legacy reports.
    legacy = build_local_embedding_source_plan_v4(
        value.query, value.subset, target_revision_ids=value.targets
    )
    plan = parse_local_embedding_source_plan_v4(
        seal(
            legacy.model_dump(mode="json") | {"schema_version": "local-embedding-source-plan/5.0"},
            "plan_sha256",
        )
    )
    request = parse_local_embedding_workflow_request_v4(
        seal(
            value.request.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-request/5.0",
                "source_plan": member(
                    "source-plan.json",
                    "eom://schemas/workflow/local-embedding-source-plan/5.0",
                    plan.model_dump(mode="json"),
                    "4",
                ),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    owner = object.__new__(admission.CatalogLocalEmbeddingOwnerAdmission)
    owner.configuration = NS(
        registry=NS(corpus_id=request.corpus_id, namespace=request.namespace, space=request.space),
        native_execution_policy=request.native_execution_policy,
        native_execution_policy_sha256=request.native_execution_policy_sha256,
    )
    owner.settings = Mock()
    owner.fence_current_actor = Mock()
    owner.registry_caller = Mock(return_value=Mock())
    owner.catalog = Mock()
    owner.catalog.resolve_selected_sources.return_value = value.subset
    owner._read_control = Mock(
        side_effect=(value.original["policy"].model_dump(mode="json"), plan.model_dump(mode="json"))
    )
    monkeypatch.setattr(admission, "PinnedArtifactReadContext", Mock())
    resolved = owner.resolve_sources(Mock(), request)
    assert resolved.admission.plan == plan and resolved.entries == value.selected
    assert owner.fence_current_actor.call_count == 2


@pytest.mark.parametrize("fault", ["source_hash", "missing_report"])
def test_explicit_family_rebuild_does_not_hide_genuine_source_drift(fault):
    value = case()
    expected = build_local_embedding_source_plan_v4(
        value.query, value.subset, target_revision_ids=value.targets
    )
    changed = value.subset
    if fault == "missing_report":
        changed = replace(changed, entries=changed.entries[1:])
    else:
        original = changed.entries[0]
        body = original.model_dump(mode="json")
        body["source"]["artifact_member"]["sha256"] = "sha256:" + "f" * 64
        body["entry_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "entry_sha256"}
        )
        entry = type(original).model_validate(body)
        changed = replace(
            changed,
            entries=(entry, *changed.entries[1:]),
            sources=(entry.source, *changed.sources[1:]),
        )
    actual = build_local_embedding_source_plan_v4(
        value.query, changed, target_revision_ids=value.targets, plan_version="4.0"
    )
    assert actual != expected
