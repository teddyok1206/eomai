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


def test_knowledge_plan_projection_fails_closed_on_invalid_canonical_document() -> None:
    workflow = SimpleNamespace(workflow_id="workflow_" + "1" * 32)
    malformed = SimpleNamespace(
        graph_snapshot_revision_id="graphrev_" + "2" * 32,
        evidence_bundle_revision_id="evidencerev_" + "3" * 32,
        canonical_document={"schema_version": "resolved-execution-plan/3.0"},
    )
    with pytest.raises(ApiError) as captured:
        QueryAdapter._knowledge_provenance(  # type: ignore[arg-type]
            workflow,
            malformed,
        )
    assert captured.value.error_code == "WORKFLOW_KNOWLEDGE_PROVENANCE_INVALID"


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
