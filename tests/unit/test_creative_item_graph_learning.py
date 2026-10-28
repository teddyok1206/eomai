"""Creative Graph learning reuses exact analysis identities and shared publication."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2
from eom_catalog_service import creative_item_graph_learning as learning
from eom_catalog_service.automatic_item_graph_publication_service import AutomaticItemGraphCandidate
from eom_catalog_service.creative_registered_report import RegisteredCreativeReport

from tests.unit.test_creative_registered_report import proposal


def case(monkeypatch, state="RUNNING", replay=False):
    resolved, lineage = proposal()
    item_revision = "itemrev_" + "7" * 32
    item_id = "item_" + "8" * 32
    run_id = "analysisrun_" + "9" * 32
    graph_id = "graphrev_" + "6" * 32
    revision = NS(
        item_revision_id=item_revision,
        revision_state="APPROVED",
        item_id=item_id,
        lifecycle_state="ACTIVE",
        current_revision_id=item_revision,
    )
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.get.return_value = revision
    session.scalar.return_value = NS(source_revision_id=item_revision)

    def sessions():
        return session

    service = object.__new__(learning.CreativeItemGraphLearningService)
    service.sessions = sessions
    service.artifacts = Mock()
    service.source = Mock()
    service.preset_key = "knowledge-analysis"
    service.preset_id = "execpreset_" + "4" * 32
    service.preset_revision_id = "execpresetrev_" + "5" * 32
    service.risk_policy_revision_id = "analysisriskrev_" + "3" * 32
    service.analyses = Mock()
    run = NS(analysis_run_id=run_id, state=state)
    service.analyses.create_with_pinned_preset.return_value = run
    service.analyses.reconcile.return_value = run
    service.analyses.accept_validated_without_review.return_value = run
    service.publication = Mock()
    service.publication.current_structure_context.return_value = NS(
        graph_snapshot_revision_id=graph_id,
        accepted_analysis_run_ids=(run_id,) if replay else (),
    )
    service.automatic = Mock()
    service.automatic.publish.return_value = NS(
        graph_publication=NS(graph_snapshot=NS(graph_snapshot_revision_id="graphrev_" + "a" * 32))
    )
    report = RegisteredCreativeReport(lineage, resolved)
    monkeypatch.setattr(learning, "load_registered_creative_report", lambda *args: report)
    monkeypatch.setattr(learning, "effective_permissions", lambda *args: learning._PERMISSIONS)
    return NS(**locals())


@pytest.mark.parametrize("state", ["RUNNING", "FAILED", "REJECTED", "CANCELLED"])
def test_unfinished_and_historical_failure_never_publish_or_become_success(monkeypatch, state):
    value = case(monkeypatch, state)
    progress = value.service.advance(
        item_revision_id=value.item_revision,
        requested_by_operator_id=value.lineage.requested_by_operator_id,
    )
    assert progress.analysis_state == state and progress.graph_snapshot_revision_id is None
    value.service.automatic.publish.assert_not_called()
    value.service.analyses.accept_validated_without_review.assert_not_called()


def test_accepted_creative_analysis_uses_shared_graph_and_exact_source_gate(monkeypatch):
    value = case(monkeypatch, "ACCEPTED")
    progress = value.service.advance(
        item_revision_id=value.item_revision,
        requested_by_operator_id=value.lineage.requested_by_operator_id,
    )
    assert progress.graph_snapshot_revision_id == "graphrev_" + "a" * 32
    invocation = value.service.automatic.publish.call_args
    assert invocation.args == (
        (
            AutomaticItemGraphCandidate(
                value.run_id, value.lineage.requested_by_operator_id, value.graph_id
            ),
        ),
    )
    assert invocation.kwargs["required_source_class"] == "APPROVED_ITEM"
    source = ApprovedItemKnowledgeSourceV2(
        source_class="APPROVED_ITEM",
        item_id=value.item_id,
        item_revision_id=value.item_revision,
        artifact_member={
            "artifact_id": "artifact_" + "b" * 32,
            "artifact_revision_id": "rev_" + "c" * 32,
            "member_path": "assessment-item-content.json",
            "materialized_path": "source/item.json",
            "sha256": value.lineage.registered_content_sha256,
            "bytes": 100,
            "schema_ref": "eom.assessment.item-content/1.0",
            "media_type": "application/json",
            "logical_name": "item.json",
        },
    )
    callback = invocation.kwargs["analysis_validator"]
    callback(value.session, (NS(analysis_run_id=value.run_id, source=source),))
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        callback(value.session, (NS(analysis_run_id="analysisrun_" + "0" * 32, source=source),))


def test_replayed_graph_membership_does_not_publish_again(monkeypatch):
    value = case(monkeypatch, "ACCEPTED", replay=True)
    result = value.service.advance(
        item_revision_id=value.item_revision,
        requested_by_operator_id=value.lineage.requested_by_operator_id,
    )
    assert result.graph_snapshot_revision_id == value.graph_id
    value.service.automatic.publish.assert_not_called()


def test_revoked_source_permission_prevents_new_analysis(monkeypatch):
    value = case(monkeypatch)
    monkeypatch.setattr(learning, "effective_permissions", lambda *args: frozenset())
    with pytest.raises(ValueError, match="PERMISSION_DENIED"):
        value.service.advance(
            item_revision_id=value.item_revision,
            requested_by_operator_id=value.lineage.requested_by_operator_id,
        )
    value.service.analyses.create_with_pinned_preset.assert_not_called()


def test_retired_item_is_not_reactivated_or_scheduled_again(monkeypatch):
    value = case(monkeypatch)
    value.revision.lifecycle_state = "RETIRED"
    with pytest.raises(ValueError, match="LIFECYCLE_INVALID"):
        value.service.advance(
            item_revision_id=value.item_revision,
            requested_by_operator_id=value.lineage.requested_by_operator_id,
        )
    value.service.analyses.create_with_pinned_preset.assert_not_called()
