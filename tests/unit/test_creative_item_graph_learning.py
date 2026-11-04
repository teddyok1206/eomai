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


@pytest.mark.parametrize("size", [2, 4])
def test_bounded_publication_uses_one_graph_owner_without_resubmitting_analysis(monkeypatch, size):
    value = case(monkeypatch, "ACCEPTED")
    revisions = {}
    entries = []
    for index in range(size):
        revision = NS(**vars(value.revision))
        revision.item_revision_id = revision.current_revision_id = f"itemrev_{index:032x}"
        revision.item_id = f"item_{index:032x}"
        revisions[revision.item_revision_id] = revision
        entries.append(
            learning.CreativeGraphLearningProgress(
                revision.item_revision_id, f"analysisrun_{index:032x}", "ACCEPTED", None
            )
        )
    lookup = {**revisions, **{row.item_id: row for row in revisions.values()}}
    value.session.get.side_effect = lambda _model, identity, **_kwargs: lookup.get(identity)
    progress = tuple(entries)
    result = value.service.publish_accepted(
        progress, requested_by_operator_id=value.lineage.requested_by_operator_id
    )
    assert (
        len(result) == size
        and result[0].graph_snapshot_revision_id == result[1].graph_snapshot_revision_id
    )
    invocation = value.service.automatic.publish.call_args
    assert tuple(entry.analysis_run_id for entry in invocation.args[0]) == tuple(
        entry.analysis_run_id for entry in progress
    )
    assert len({entry.graph_snapshot_revision_id for entry in invocation.args[0]}) == 1
    value.service.analyses.create_with_pinned_preset.assert_not_called()


@pytest.mark.parametrize("fault", ["empty", "duplicate", "unaccepted", "oversized"])
def test_graph_batch_rejects_ambiguous_or_unaccepted_members_before_any_io(monkeypatch, fault):
    value = case(monkeypatch)
    entry = learning.CreativeGraphLearningProgress(
        value.item_revision, value.run_id, "ACCEPTED", None
    )
    progress = (entry,)
    if fault == "empty":
        progress = ()
    elif fault == "duplicate":
        progress = (entry, entry)
    elif fault == "unaccepted":
        progress = (
            learning.CreativeGraphLearningProgress(
                value.item_revision, value.run_id, "RUNNING", None
            ),
        )
    else:
        progress = tuple(
            learning.CreativeGraphLearningProgress(
                f"itemrev_{index:032x}", f"analysisrun_{index:032x}", "ACCEPTED", None
            )
            for index in range(5)
        )
    with pytest.raises(ValueError, match="ANALYSIS_INVALID"):
        value.service.publish_accepted(
            progress, requested_by_operator_id=value.lineage.requested_by_operator_id
        )
    value.service.automatic.publish.assert_not_called()
    value.service.analyses.create_with_pinned_preset.assert_not_called()


def test_stale_graph_retries_same_accepted_analysis_with_explicit_new_base(monkeypatch):
    value = case(monkeypatch, "ACCEPTED")
    from eom_catalog_service.knowledge_graph_publication_service import (
        KnowledgeGraphPublicationError,
    )

    next_graph = "graphrev_" + "b" * 32
    value.service.publication.current_structure_context.side_effect = (
        NS(graph_snapshot_revision_id=value.graph_id, accepted_analysis_run_ids=()),
        NS(graph_snapshot_revision_id=next_graph, accepted_analysis_run_ids=()),
    )
    success = value.service.automatic.publish.return_value
    value.service.automatic.publish.side_effect = (
        KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_STALE_CURRENT", "synthetic competing append"
        ),
        success,
    )
    result = value.service.advance(
        item_revision_id=value.item_revision,
        requested_by_operator_id=value.lineage.requested_by_operator_id,
    )
    calls = value.service.automatic.publish.call_args_list
    assert result.graph_snapshot_revision_id == "graphrev_" + "a" * 32
    assert [call.args[0][0].graph_snapshot_revision_id for call in calls] == [
        value.graph_id,
        next_graph,
    ]
    assert all(call.args[0][0].analysis_run_id == value.run_id for call in calls)
    assert value.service.analyses.create_with_pinned_preset.call_count == 1
    assert value.service.source.reauthorize.call_count == 3


def test_racing_writer_already_published_exact_analysis_is_reused(monkeypatch):
    value = case(monkeypatch, "ACCEPTED")
    from eom_catalog_service.knowledge_graph_publication_service import (
        KnowledgeGraphPublicationError,
    )

    next_graph = "graphrev_" + "b" * 32
    value.service.publication.current_structure_context.side_effect = (
        NS(graph_snapshot_revision_id=value.graph_id, accepted_analysis_run_ids=()),
        NS(graph_snapshot_revision_id=next_graph, accepted_analysis_run_ids=(value.run_id,)),
    )
    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(
        "KNOWLEDGE_GRAPH_STALE_CURRENT", "synthetic existing publication"
    )
    result = value.service.advance(
        item_revision_id=value.item_revision,
        requested_by_operator_id=value.lineage.requested_by_operator_id,
    )
    assert result.graph_snapshot_revision_id == next_graph
    assert value.service.automatic.publish.call_count == 1
    assert value.service.analyses.create_with_pinned_preset.call_count == 1


@pytest.mark.parametrize(
    "code,expected_attempts",
    [("KNOWLEDGE_GRAPH_STALE_CURRENT", 3), ("KNOWLEDGE_GRAPH_HASH_MISMATCH", 1)],
)
def test_publication_retry_is_bounded_and_only_for_exact_cas_conflict(
    monkeypatch, code, expected_attempts
):
    value = case(monkeypatch, "ACCEPTED")
    from eom_catalog_service.knowledge_graph_publication_service import (
        KnowledgeGraphPublicationError,
    )

    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(
        code, "synthetic failure"
    )
    with pytest.raises(KnowledgeGraphPublicationError) as failure:
        value.service.advance(
            item_revision_id=value.item_revision,
            requested_by_operator_id=value.lineage.requested_by_operator_id,
        )
    assert failure.value.code == code
    assert value.service.automatic.publish.call_count == expected_attempts
    assert value.service.analyses.create_with_pinned_preset.call_count == 1


@pytest.mark.parametrize("fault", ["permission", "source_hash"])
def test_stale_retry_reauthorizes_and_stops_on_new_source_or_permission_failure(monkeypatch, fault):
    value = case(monkeypatch, "ACCEPTED")
    from eom_catalog_service.knowledge_graph_publication_service import (
        KnowledgeGraphPublicationError,
    )

    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(
        "KNOWLEDGE_GRAPH_STALE_CURRENT", "synthetic race"
    )
    if fault == "permission":
        monkeypatch.setattr(
            learning,
            "effective_permissions",
            Mock(side_effect=(learning._PERMISSIONS, learning._PERMISSIONS, frozenset())),
        )
        code = "PERMISSION_DENIED"
    else:
        value.service.source.reauthorize.side_effect = (
            None,
            None,
            ValueError("SOURCE_HASH_MISMATCH"),
        )
        code = "SOURCE_HASH_MISMATCH"
    with pytest.raises(ValueError, match=code):
        value.service.advance(
            item_revision_id=value.item_revision,
            requested_by_operator_id=value.lineage.requested_by_operator_id,
        )
    assert value.service.automatic.publish.call_count == 1
    assert value.service.analyses.create_with_pinned_preset.call_count == 1
