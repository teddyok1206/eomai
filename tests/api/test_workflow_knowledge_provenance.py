from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_api.errors import ApiError
from eom_api.services.query_adapter import QueryAdapter


def test_historical_workflow_without_knowledge_plan_has_no_projection() -> None:
    workflow = SimpleNamespace(workflow_id="workflow_" + "1" * 32)
    assert QueryAdapter._knowledge_provenance(workflow, None) is None  # type: ignore[arg-type]
    legacy = SimpleNamespace(
        graph_snapshot_revision_id="graphrev_" + "2" * 32,
        evidence_bundle_revision_id="evidencerev_" + "3" * 32,
        canonical_document={"schema_version": "resolved-execution-plan/1.0"},
    )
    assert (
        QueryAdapter._knowledge_provenance(  # type: ignore[arg-type]
            workflow,
            legacy,
        )
        is None
    )


@pytest.mark.parametrize(
    "schema_version",
    ("resolved-execution-plan/3.0", "resolved-execution-plan/11.0"),
)
def test_knowledge_plan_projection_fails_closed_on_invalid_canonical_document(
    schema_version: str,
) -> None:
    workflow = SimpleNamespace(workflow_id="workflow_" + "1" * 32)
    malformed = SimpleNamespace(
        graph_snapshot_revision_id="graphrev_" + "2" * 32,
        evidence_bundle_revision_id="evidencerev_" + "3" * 32,
        canonical_document={"schema_version": schema_version},
    )
    with pytest.raises(ApiError) as captured:
        QueryAdapter._knowledge_provenance(  # type: ignore[arg-type]
            workflow,
            malformed,
        )
    assert captured.value.error_code == "WORKFLOW_KNOWLEDGE_PROVENANCE_INVALID"


def test_solution_enriched_v11_plan_projects_the_same_pinned_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "workflow_" + "1" * 32
    requirement = SimpleNamespace(
        corpus_key="integrated-science-textbooks",
        query_kind="ITEM_PREPARATION",
        curriculum_root_key=None,
        required_item_elements=("choice", "paragraph", "table"),
        source_classes=("PAST_EXAM",),
    )
    graph_snapshot = SimpleNamespace(graph_snapshot_revision_id="graphrev_" + "2" * 32)
    plan = SimpleNamespace(
        plan_id="execplan_" + "3" * 32,
        plan_sha256="sha256:" + "4" * 64,
        workflow_id=workflow_id,
        preset_id="execpreset_" + "5" * 32,
        preset_revision_id="execpresetrev_" + "6" * 32,
        capacity_policy_revision_id="capacityrev_" + "7" * 32,
        graph_snapshot=graph_snapshot,
        evidence_bundle_revision_id="evidencerev_" + "8" * 32,
        retrieval_requirement=requirement,
        retrieval_request_id="retrieval_" + "9" * 32,
        retrieval_request_sha256="sha256:" + "a" * 64,
        access_policy_revision_id="accessrev_" + "b" * 32,
        access_policy_sha256="sha256:" + "c" * 64,
        evidence_manifest_sha256="sha256:" + "d" * 64,
        resolved_at="2026-09-19T15:00:00Z",
    )
    monkeypatch.setattr(
        "eom_api.services.query_adapter.ResolvedExecutionPlanV11.model_validate",
        lambda _value: plan,
    )
    record = SimpleNamespace(
        plan_id=plan.plan_id,
        workflow_id=workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=plan.evidence_bundle_revision_id,
        plan_sha256=plan.plan_sha256,
        resolved_at=plan.resolved_at,
        canonical_document={"schema_version": "resolved-execution-plan/11.0"},
    )

    projected = QueryAdapter._knowledge_provenance(  # type: ignore[arg-type]
        SimpleNamespace(workflow_id=workflow_id),
        record,
    )

    assert projected is not None
    assert projected.plan_id == plan.plan_id
    assert projected.preset_revision_id == plan.preset_revision_id
    assert projected.graph_snapshot_revision_id == plan.graph_snapshot.graph_snapshot_revision_id
    assert projected.source_classes == ("PAST_EXAM",)


def test_completed_workflow_projects_only_the_registered_item_revision_pointer() -> None:
    registration = {
        "item_id": "item_" + "1" * 32,
        "item_revision_id": "itemrev_" + "2" * 32,
        "revision_number": 3,
        "manifest_artifact_id": "artifact_" + "3" * 32,
        "manifest_artifact_revision_id": "rev_" + "4" * 32,
        "manifest_sha256": "sha256:" + "5" * 64,
    }
    workflow = SimpleNamespace(runtime_context={"item_registration": registration})

    projected = QueryAdapter._item_registration(workflow)  # type: ignore[arg-type]

    assert projected is not None
    assert projected.item_revision_id == registration["item_revision_id"]
    assert "content" not in projected.model_dump(mode="json")
    assert "path" not in projected.model_dump(mode="json")


def test_workflow_item_registration_projection_fails_closed_on_malformed_pointer() -> None:
    assert (
        QueryAdapter._item_registration(  # type: ignore[arg-type]
            SimpleNamespace(runtime_context={})
        )
        is None
    )
    workflow = SimpleNamespace(
        runtime_context={
            "item_registration": {
                "item_id": "item_" + "1" * 32,
                "item_revision_id": "itemrev_" + "2" * 32,
                "revision_number": 1,
                "manifest_artifact_id": "artifact_" + "3" * 32,
                "manifest_artifact_revision_id": "rev_" + "4" * 32,
                "manifest_sha256": "sha256:" + "0" * 63,
            }
        }
    )
    with pytest.raises(ApiError) as captured:
        QueryAdapter._item_registration(workflow)  # type: ignore[arg-type]
    assert captured.value.error_code == "WORKFLOW_ITEM_REGISTRATION_INVALID"


def _accepted_resolution() -> dict[str, object]:
    return {
        "schema_version": "workflow-expected-resolution/1.0",
        "workflow_definition_key": "generic-item-development",
        "workflow_definition_version": "1.8.0",
        "workflow_definition_sha256": "sha256:" + "1" * 64,
        "content_pack_release_id": "packrel_" + "2" * 32,
        "content_pack_key": "generated-knowledge-item",
        "content_pack_version": "1.13.0",
        "content_pack_bundle_sha256": "sha256:" + "3" * 64,
        "content_pack_source_tree_sha256": "sha256:" + "4" * 64,
        "execution_preset_id": "execpreset_" + "5" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "6" * 32,
        "execution_preset_key": "knowledge-grounded-item",
        "execution_preset_content_sha256": "sha256:" + "7" * 64,
    }


def test_workflow_accepted_resolution_projects_only_matching_exact_pointers() -> None:
    resolution = _accepted_resolution()
    workflow = SimpleNamespace(
        definition_key=resolution["workflow_definition_key"],
        definition_version=resolution["workflow_definition_version"],
        definition_hash=resolution["workflow_definition_sha256"],
        runtime_context={
            "accepted_resolution": resolution,
            "content_pack": {
                "release_id": resolution["content_pack_release_id"],
                "pack_key": resolution["content_pack_key"],
                "version": resolution["content_pack_version"],
                "release_sha256": resolution["content_pack_bundle_sha256"],
                "source_tree_sha256": resolution["content_pack_source_tree_sha256"],
            },
        },
    )
    record = SimpleNamespace(
        canonical_document={
            "workflow_definition_key": resolution["workflow_definition_key"],
            "workflow_definition_version": resolution["workflow_definition_version"],
            "workflow_definition_sha256": resolution["workflow_definition_sha256"],
            "content_pack_release_id": resolution["content_pack_release_id"],
            "content_pack_sha256": resolution["content_pack_bundle_sha256"],
            "preset_id": resolution["execution_preset_id"],
            "preset_revision_id": resolution["execution_preset_revision_id"],
            "preset_sha256": resolution["execution_preset_content_sha256"],
        }
    )

    projected = QueryAdapter._accepted_resolution(workflow, record)  # type: ignore[arg-type]

    assert projected is not None
    assert projected.model_dump(mode="json") == resolution


def test_workflow_accepted_resolution_fails_closed_on_runtime_or_plan_drift() -> None:
    resolution = _accepted_resolution()
    workflow = SimpleNamespace(
        definition_key=resolution["workflow_definition_key"],
        definition_version=resolution["workflow_definition_version"],
        definition_hash=resolution["workflow_definition_sha256"],
        runtime_context={
            "accepted_resolution": resolution,
            "content_pack": {
                "release_id": resolution["content_pack_release_id"],
                "pack_key": resolution["content_pack_key"],
                "version": resolution["content_pack_version"],
                "release_sha256": resolution["content_pack_bundle_sha256"],
                "source_tree_sha256": "sha256:" + "f" * 64,
            },
        },
    )
    record = SimpleNamespace(canonical_document={})

    with pytest.raises(ApiError) as captured:
        QueryAdapter._accepted_resolution(workflow, record)  # type: ignore[arg-type]
    assert captured.value.error_code == "WORKFLOW_ACCEPTED_RESOLUTION_INVALID"
