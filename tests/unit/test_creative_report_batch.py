"""Actual primaries are batch-read, not reserialized into counterfeit Artifact bytes."""

from unittest.mock import Mock

import pytest
from eom_catalog_service import creative_report_batch as batch
from eom_catalog_service.creative_report_batch import load_registered_creative_reports
from sqlalchemy.dialects.postgresql import dialect

from tests.unit.test_creative_registration_v2 import v2_registered


def batch_case(monkeypatch):
    session, artifacts, revision, components, resolved, lineage, _ = v2_registered(monkeypatch)
    session.in_nested_transaction.return_value = False
    for component in components:
        component.item_revision_id = revision.item_revision_id
    artifacts.load_json_revisions.return_value = {
        components[1].artifact_revision_id: lineage.model_dump(mode="json"),
        components[2].artifact_revision_id: resolved.role.model_dump(mode="json"),
    }
    capture = Mock()
    monkeypatch.setattr(batch, "capture_creative_proposal_read_set", capture)
    resolved_reader = Mock(return_value=resolved)
    monkeypatch.setattr(batch, "resolve_completed_creative_learning_proposal", resolved_reader)
    return session, artifacts, revision, resolved, lineage, capture, resolved_reader


def test_batch_preserves_public_report_and_exact_lineage_pointer(monkeypatch):
    session, artifacts, revision, resolved, lineage, capture, reader = batch_case(monkeypatch)
    result = load_registered_creative_reports(session, artifacts, (revision,))
    value = result[revision.item_revision_id]
    assert value.report.lineage == lineage and value.report.proposal == resolved
    assert value.lineage_pointer.member_path == "lineage.json"
    assert "ANSWER_DISAGREEMENT" in value.report.context_text()
    assert value.report.proposal.role.output.learning_result.status == "NEEDS_DECISION"
    assert session.scalars.call_count == 1 and artifacts.load_json_revisions.call_count == 1
    sql = str(session.scalars.call_args.args[0].compile(dialect=dialect()))
    assert "FOR SHARE" not in sql and " IN " in sql
    artifacts.read_member.assert_not_called()
    assert reader.call_args.kwargs["read_set"] is capture.return_value
    loaded = reader.call_args.args[1].load_json_revision(
        artifact_id=resolved.pointer.artifact_id,
        revision_id=resolved.pointer.artifact_revision_id,
        content_hash=resolved.pointer.sha256,
        max_bytes=4 * 1024 * 1024,
    )
    assert loaded == resolved.role.model_dump(mode="json")


def test_batch_reader_refuses_a_different_hash_before_returning_cached_values(monkeypatch):
    session, artifacts, revision, resolved, _, _, reader = batch_case(monkeypatch)
    load_registered_creative_reports(session, artifacts, (revision,))
    with pytest.raises(ValueError, match="BATCH_POINTER_INVALID"):
        reader.call_args.args[1].load_json_revision(
            artifact_id=resolved.pointer.artifact_id,
            revision_id=resolved.pointer.artifact_revision_id,
            content_hash="sha256:" + "0" * 64,
            max_bytes=4 * 1024 * 1024,
        )


def test_empty_batch_is_noop_but_duplicate_and_nested_batches_fail(monkeypatch):
    session, artifacts, revision, *_ = batch_case(monkeypatch)
    assert load_registered_creative_reports(session, artifacts, ()) == {}
    for revisions in ((revision, revision), (revision,) * 17):
        with pytest.raises(ValueError, match="BATCH_SELECTION_INVALID"):
            load_registered_creative_reports(session, artifacts, revisions)
    session.in_nested_transaction.return_value = True
    with pytest.raises(ValueError, match="BATCH_SELECTION_INVALID"):
        load_registered_creative_reports(session, artifacts, (revision,))
    artifacts.load_json_revisions.assert_not_called()
