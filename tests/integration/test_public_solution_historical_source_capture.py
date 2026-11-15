"""Real pg_temp revision locks with synthetic admitted-source and report IO ports.

Only the guarded disposable fixture is used. Source admission, report bytes and
Artifact provenance are explicit synthetic ports, not NAS/production acceptance.
The actual capture reads locked ORM revisions and applies the shared history rule.
"""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_service import public_solution_source_capture as capture_module
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.public_solution_source_capture import CatalogPublicSolutionSourceCapture
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_identifiers import canonical_json_bytes, content_sha256
from sqlalchemy import event, text

from tests.integration.test_inference_transfer_candidate_admission import (
    pool_database as pool_database,
)
from tests.unit.inference_transfer_fixtures import NOW, profile, report
from tests.unit.test_public_solution_encoding import public_recipe

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]

ITEM_ID = "item_" + "8".zfill(32)
OLD_REVISION_ID = "itemrev_" + "8".zfill(32)
SUCCESSOR_REVISION_ID = "itemrev_" + "9".zfill(32)
BASE_ANALYSIS_RUN_ID = "analysisrun_" + "8".zfill(32)


@pytest.fixture
def historical_capture(pool_database, monkeypatch):
    session = pool_database
    # These rows already exist in the guarded fixture. Its pg_temp shadows have
    # no production immutability triggers; no canonical row is changed here.
    session.execute(
        text(
            "UPDATE pg_temp.item_revisions SET metadata_json='{}'::jsonb, "
            "approved_at=:now, approved_by='synthetic-approver', "
            "superseded_at=:now, superseded_by_revision_id=:successor "
            "WHERE item_revision_id=:old"
        ),
        {"now": NOW, "successor": SUCCESSOR_REVISION_ID, "old": OLD_REVISION_ID},
    )
    session.execute(
        text("UPDATE pg_temp.items SET current_revision_id=:successor WHERE item_id=:item"),
        {"successor": SUCCESSOR_REVISION_ID, "item": ITEM_ID},
    )

    basis = profile().source_basis
    source = ApprovedItemKnowledgeSourceV2.model_validate(
        basis.source.model_dump(mode="json")
        | {"item_id": ITEM_ID, "item_revision_id": OLD_REVISION_ID}
    )
    pointer_body = basis.solution_evidence.model_dump(mode="json", exclude={"pointer_sha256"})
    pointer_body["base_analysis_run_id"] = BASE_ANALYSIS_RUN_ID
    pointer = type(basis.solution_evidence).model_validate(
        pointer_body | {"pointer_sha256": content_sha256(pointer_body)}
    )
    original_report = report()
    candidate = NS(source=source, analysis_run_id=BASE_ANALYSIS_RUN_ID)
    pool = NS(candidates=(candidate,), graph_snapshot=basis.graph_snapshot)
    scope = NS(
        access_policy_revision_id="accessrev_" + "a" * 32,
        access_policy_sha256="sha256:" + "b" * 64,
    )
    owner = object.__new__(CatalogPublicSolutionSourceCapture)
    owner.sources, owner.artifacts = Mock(), Mock()
    owner.sources.capture_public_solution_pool_in_session.return_value = scope, pool
    owner.sources.authorize_scope_in_session.return_value = scope
    solution = NS(source=source, report=original_report, pointer=pointer)
    solutions = Mock(return_value={BASE_ANALYSIS_RUN_ID: solution})
    registered_solutions = Mock(return_value={})
    creative_reports = Mock()
    monkeypatch.setattr(capture_module, "resolve_solution_evidence_by_base_run", solutions)
    monkeypatch.setattr(
        capture_module, "resolve_registered_solution_evidence_by_base_run", registered_solutions
    )
    monkeypatch.setattr(capture_module, "load_registered_creative_reports", creative_reports)
    reader, fence, command = Mock(), Mock(), Mock()
    locked_reads = []
    connection = session.connection()

    def observe_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "FROM item_revisions" in statement and "FOR SHARE" in statement:
            locked_reads.append(statement)

    event.listen(connection, "before_cursor_execute", observe_lock)
    try:
        yield NS(**locals())
    finally:
        event.remove(connection, "before_cursor_execute", observe_lock)


def capture(value):
    return value.owner.capture_in_session(
        value.session,
        value.command,
        public_recipe(),
        identity_fence=value.fence,
        artifact_reader=value.reader,
    )


def set_historical_state(value, state):
    value.session.execute(
        text("UPDATE pg_temp.item_revisions SET revision_state=:state WHERE item_revision_id=:old"),
        {"state": state, "old": OLD_REVISION_ID},
    )


@pytest.mark.parametrize("state", ["SUPERSEDED", "RETIRED"])
def test_locked_historical_revision_keeps_original_source_report_and_pointer(
    historical_capture, state
):
    value = historical_capture
    set_historical_state(value, state)
    before = canonical_json_bytes(value.original_report)

    result = capture(value)

    old = value.session.get(ItemRevisionRecord, OLD_REVISION_ID)
    successor = value.session.get(ItemRevisionRecord, SUCCESSOR_REVISION_ID)
    item = value.session.get(ItemRecord, ITEM_ID)
    assert isinstance(old, ItemRevisionRecord) and old.revision_state == state
    assert isinstance(successor, ItemRevisionRecord) and successor.revision_state == "APPROVED"
    assert successor.item_id == old.item_id == ITEM_ID
    assert item.current_revision_id == SUCCESSOR_REVISION_ID
    assert len(value.locked_reads) == 1
    assert result.source_revision_ids == (OLD_REVISION_ID,)
    assert result.missing_report_revision_ids == () and len(result.entries) == 1
    entry = result.entries[0]
    assert entry.source == value.source
    assert entry.source.artifact_member.sha256 == value.source.artifact_member.sha256
    assert entry.source.item_revision_id != item.current_revision_id
    assert entry.base_analysis_run_id == BASE_ANALYSIS_RUN_ID
    assert entry.evidence.solution == value.pointer
    assert entry.public_solution == project_public_solution_text(value.original_report)
    assert entry.graph_snapshot == value.basis.graph_snapshot
    assert entry.policy_revision_id == value.scope.access_policy_revision_id
    assert entry.policy_sha256 == value.scope.access_policy_sha256
    assert canonical_json_bytes(value.original_report) == before
    value.solutions.assert_called_once_with(
        value.session, value.reader, base_analysis_run_ids=(BASE_ANALYSIS_RUN_ID,)
    )
    value.creative_reports.assert_not_called()
    value.reader.revalidate_provenance.assert_called_once()


@pytest.mark.parametrize(
    "state,missing",
    [
        ("SUPERSEDED", "approved_at"),
        ("SUPERSEDED", "approved_by"),
        ("SUPERSEDED", "superseded_at"),
        ("SUPERSEDED", "superseded_by_revision_id"),
        ("RETIRED", "approved_at"),
        ("RETIRED", "approved_by"),
    ],
)
def test_locked_historical_revision_with_incomplete_history_is_explicitly_rejected(
    historical_capture, state, missing
):
    value = historical_capture
    set_historical_state(value, state)
    # The column name comes only from the finite parametrization above.
    value.session.execute(
        text(f"UPDATE pg_temp.item_revisions SET {missing}=NULL WHERE item_revision_id=:old"),
        {"old": OLD_REVISION_ID},
    )

    with pytest.raises(ValueError, match=r"^PUBLIC_SOLUTION_SOURCE_SET_INVALID$"):
        capture(value)

    assert len(value.locked_reads) == 1
    value.solutions.assert_not_called()
    value.registered_solutions.assert_not_called()
    value.creative_reports.assert_not_called()


@pytest.mark.parametrize("state", ["SUPERSEDED", "RETIRED"])
@pytest.mark.parametrize("fault", ["source_hash", "authority"])
def test_historical_eligibility_does_not_waive_source_identity_or_final_authority(
    historical_capture, state, fault
):
    value = historical_capture
    set_historical_state(value, state)
    before = canonical_json_bytes(value.original_report)
    if fault == "source_hash":
        changed = value.source.model_dump(mode="json")
        changed["artifact_member"]["sha256"] = "sha256:" + "f" * 64
        value.solution.source = ApprovedItemKnowledgeSourceV2.model_validate(changed)
        expected = "PUBLIC_SOLUTION_SOURCE_POINTER_MISMATCH"
    else:
        value.owner.sources.authorize_scope_in_session.return_value = NS(
            access_policy_revision_id="accessrev_" + "f" * 32
        )
        expected = "PUBLIC_SOLUTION_AUTHORITY_CHANGED"

    with pytest.raises(ValueError, match="^" + expected + "$"):
        capture(value)

    assert len(value.locked_reads) == 1
    assert canonical_json_bytes(value.original_report) == before
    assert value.session.get(ItemRecord, ITEM_ID).current_revision_id == SUCCESSOR_REVISION_ID
    value.solutions.assert_called_once()
    value.creative_reports.assert_not_called()
