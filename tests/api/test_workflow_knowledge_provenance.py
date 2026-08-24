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
