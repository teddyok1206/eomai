"""A retry is an exact indexed lineage, never a latest/success-first lookup."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import knowledge_analysis_service as analysis
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey


def run(index, state="FAILED", **changes):
    request = {
        "schema_version": "knowledge-analysis-request/9.0",
        "source": {"source_revision_id": "itemrev_" + "a" * 32},
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "risk_policy_revision_id": "analysisriskrev_" + "b" * 32,
        "analysis_request_id": f"analysisrequest_{index:032x}",
    }
    values = dict(
        analysis_run_id=f"analysisrun_{index:032x}",
        workflow_id=f"workflow_{index:032x}",
        state=state,
        lock_version=1,
        created_by_operator_id="operator_" + "c" * 32,
        source_kind="APPROVED_ITEM",
        source_revision_id="itemrev_" + "a" * 32,
        source_artifact_id="artifact_" + "d" * 32,
        source_artifact_revision_id="rev_" + "e" * 32,
        source_sha256="sha256:" + "f" * 64,
        preset_id="execpreset_" + "1" * 32,
        preset_revision_id="execpresetrev_" + "2" * 32,
        risk_policy_revision_id=request["risk_policy_revision_id"],
        canonical_request=request,
        request_sha256=content_sha256(request),
        proposal_artifact_revision_id=None,
        accepted_result_artifact_revision_id=None,
    )
    values.update(changes)
    return NS(**values)


def case(monkeypatch, rows):
    service = object.__new__(analysis.KnowledgeAnalysisApplicationService)
    session = Mock()
    session.get.return_value = rows[0]
    session.scalars.side_effect = [tuple((row,)) for row in rows[1:]] + [()]
    service.sessions = lambda: nullcontext(session)
    monkeypatch.setattr(
        analysis, "effective_permissions", lambda *_: {PermissionKey.KNOWLEDGE_ANALYSIS_CREATE}
    )
    return service, session


@pytest.mark.parametrize("state", ["RUNNING", "QUEUED", "VALIDATING", "NEEDS_REVIEW", "ACCEPTED"])
def test_exact_supported_successor_is_reused_without_mutating_failed_root(monkeypatch, state):
    rows = [run(1), run(2, state)]
    original = deepcopy(vars(rows[0]))
    service, session = case(monkeypatch, rows)
    for _ in range(2):
        session.scalars.side_effect = [(rows[1],)]
        result = service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )
        assert (result.analysis_run_id, result.state) == (rows[1].analysis_run_id, state)
        assert vars(rows[0]) == original
    assert session.add.call_count == session.flush.call_count == session.commit.call_count == 0
    statement = session.scalars.call_args.args[0]
    assert "predecessor_analysis_run_id =" in str(statement) and statement._limit_clause.value == 2


def test_retry_of_retry_is_resolved_by_explicit_links(monkeypatch):
    rows = [run(1), run(2), run(3, "ACCEPTED")]
    service, _ = case(monkeypatch, rows)
    assert (
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        ).analysis_run_id
        == rows[2].analysis_run_id
    )


def test_real_request_self_hash_field_is_excluded_from_digest(monkeypatch):
    rows = [run(1), run(2, "ACCEPTED")]
    for row in rows:
        row.canonical_request["request_sha256"] = row.request_sha256
    service, _ = case(monkeypatch, rows)
    result = service.resolve_retry(
        analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
    )
    assert result.analysis_run_id == rows[1].analysis_run_id


def test_unrecovered_failed_root_remains_failed(monkeypatch):
    root = run(1)
    service, _ = case(monkeypatch, [root])
    assert (
        service.resolve_retry(
            analysis_run_id=root.analysis_run_id, requested_by=root.created_by_operator_id
        ).state
        == "FAILED"
    )


@pytest.mark.parametrize(
    "field",
    [
        "created_by_operator_id",
        "source_kind",
        "source_revision_id",
        "source_artifact_id",
        "source_artifact_revision_id",
        "source_sha256",
        "preset_id",
        "preset_revision_id",
        "risk_policy_revision_id",
    ],
)
def test_changed_identity_or_pins_cannot_be_used_as_recovery(monkeypatch, field):
    rows = [run(1), run(2, "ACCEPTED", **{field: "different"})]
    service, _ = case(monkeypatch, rows)
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="dependencies differ"):
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )


@pytest.mark.parametrize(
    "field", ["source", "schema_version", "general_knowledge_mode", "risk_policy_revision_id"]
)
def test_changed_request_semantics_are_not_a_retry(monkeypatch, field):
    rows = [run(1), run(2, "ACCEPTED")]
    rows[1].canonical_request[field] = "different"
    rows[1].request_sha256 = content_sha256(rows[1].canonical_request)
    service, _ = case(monkeypatch, rows)
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="dependencies differ"):
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )


def test_permission_revocation_and_wrong_owner_are_rejected(monkeypatch):
    root = run(1)
    service, _ = case(monkeypatch, [root])
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="owner is unavailable"):
        service.resolve_retry(analysis_run_id=root.analysis_run_id, requested_by="another")
    monkeypatch.setattr(analysis, "effective_permissions", lambda *_: set())
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="owner is unavailable"):
        service.resolve_retry(
            analysis_run_id=root.analysis_run_id, requested_by=root.created_by_operator_id
        )


def test_missing_root_is_explicit(monkeypatch):
    service, session = case(monkeypatch, [run(1)])
    session.get.return_value = None
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="does not exist"):
        service.resolve_retry(
            analysis_run_id=run(1).analysis_run_id, requested_by=run(1).created_by_operator_id
        )


@pytest.mark.parametrize("root_hash", [True, False])
def test_hash_mismatch_is_not_hidden_by_an_accepted_successor(monkeypatch, root_hash):
    rows = [run(1), run(2, "ACCEPTED")]
    rows[0 if root_hash else 1].request_sha256 = "sha256:" + "0" * 64
    service, _ = case(monkeypatch, rows)
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="hash differs"):
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )


def test_ambiguous_branches_do_not_pick_newest_or_accepted(monkeypatch):
    rows = [run(1), run(2, "ACCEPTED"), run(3)]
    service, session = case(monkeypatch, rows)
    session.scalars.side_effect = [(rows[1], rows[2])]
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match="ambiguous"):
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )


@pytest.mark.parametrize("cycle", [True, False])
def test_cycle_and_chain_limit_are_explicit(monkeypatch, cycle):
    rows = [run(i) for i in range(1, 35)]
    if cycle:
        rows = [rows[0], rows[1], rows[0]]
    service, _ = case(monkeypatch, rows)
    with pytest.raises(analysis.KnowledgeAnalysisServiceError, match=r"cycle|bound"):
        service.resolve_retry(
            analysis_run_id=rows[0].analysis_run_id, requested_by=rows[0].created_by_operator_id
        )
