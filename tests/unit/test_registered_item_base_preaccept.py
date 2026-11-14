"""Source-bound pre-acceptance checks; local immutable fixtures, no DB or model."""

import json
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts import KnowledgeAnalysisProposalReceipt
from eom_catalog_contracts.knowledge import knowledge_proposal_member_set_sha256
from eom_catalog_service import knowledge_analysis_service as owner
from eom_catalog_service.knowledge_proposal_resolution import KnowledgeProposalResolutionError
from eom_catalog_service.registered_item_solution_base import RegisteredItemSolutionAnchorError
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_registered_item_solution_application import accepted_chain


class StopAtCommit(Exception):
    pass


def acceptance_case(tmp_path, monkeypatch, fault=None):
    fixture = accepted_chain(tmp_path, canonical_receipt=True)
    receipt = fixture.receipt
    if fault in {"hash", "locator"}:
        document = receipt.model_dump(mode="json")
        member = document["members"]["anchors"]
        path = (
            fixture.fixture.root
            / member["artifact_id"]
            / member["artifact_revision_id"]
            / member["member_path"]
        )
        anchors = [json.loads(line) for line in path.read_bytes().splitlines()]
        if fault == "hash":
            anchors[0]["excerpt_sha256"] = "sha256:" + "0" * 64
        else:
            anchors[0]["locator"] = "/missing"
        raw = b"".join(canonical_json_bytes(row) + b"\n" for row in anchors)
        path.write_bytes(raw)
        member.update(bytes=len(raw), sha256=sha256_bytes(raw))
        document["content_set_sha256"] = knowledge_proposal_member_set_sha256(
            tuple(
                type(receipt.members.anchors).model_validate(value)
                for value in document["members"].values()
            )
        )
        receipt = KnowledgeAnalysisProposalReceipt.model_validate(document)
    request = fixture.request
    run = NS(
        analysis_run_id=fixture.run.analysis_run_id,
        state="VALIDATING",
        workflow_id="workflow_" + "8" * 32,
        canonical_request=request.model_dump(mode="json"),
        risk_policy_revision_id=request.risk_policy_revision_id,
        lock_version=4,
        request_sha256=request.request_sha256,
        proposal_content_set_sha256=receipt.content_set_sha256,
        created_by_operator_id="operator_" + "5" * 32,
    )
    session = Mock()
    session.get.return_value = run
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = session
    monkeypatch.setattr(owner, "transaction", lambda _sessions: nullcontext(session))
    service = object.__new__(owner.KnowledgeAnalysisApplicationService)
    service.sessions = sessions
    service.artifacts = fixture.reader
    service._stored_receipt = Mock(return_value=receipt)
    service._proposal_receipt_pointer = Mock(return_value=fixture.receipt_pointer)
    service.risk_policy = Mock(
        return_value=NS(
            risk_policy_revision_id=request.risk_policy_revision_id,
            content_sha256="sha256:" + "8" * 64,
        )
    )
    service._locked_run = Mock(return_value=run)
    service._transition = Mock(
        side_effect=lambda _s, row, state, *_args, **_kw: setattr(row, "state", state)
    )
    service._projection = Mock(side_effect=lambda row: row)
    service._commit_json_artifact = Mock(side_effect=StopAtCommit)
    return service, run, fixture


def accept(service, run, *, actor=None):
    return service._accept(
        run.analysis_run_id,
        acceptance_mode="AUTO_POLICY",
        review_pointer=None,
        actor_id=actor or run.created_by_operator_id,
    )


@pytest.mark.parametrize("fault", ("hash", "locator"))
def test_bad_model_anchor_fails_before_acceptance_without_artifact_repair(
    tmp_path, monkeypatch, fault
):
    service, run, fixture = acceptance_case(tmp_path, monkeypatch, fault)
    before = fixture.receipt.model_dump(mode="json")
    result = accept(service, run)
    assert result.state == "FAILED"
    assert result.error_code == RegisteredItemSolutionAnchorError.code
    service._commit_json_artifact.assert_not_called()
    assert fixture.receipt.model_dump(mode="json") == before
    assert (
        run.proposal_content_set_sha256 == service._stored_receipt.return_value.content_set_sha256
    )


def test_valid_registered_base_reaches_existing_canonical_acceptance(tmp_path, monkeypatch):
    service, run, _fixture = acceptance_case(tmp_path, monkeypatch)
    with pytest.raises(StopAtCommit):
        accept(service, run)
    assert run.state == "VALIDATING"
    assert (
        service._commit_json_artifact.call_args.kwargs["artifact_type"]
        == "knowledge-analysis-accepted-result"
    )


def test_existing_acceptance_actor_semantics_are_not_narrowed_to_creator(tmp_path, monkeypatch):
    service, run, _fixture = acceptance_case(tmp_path, monkeypatch, "hash")
    reviewer = "operator_" + "6" * 32
    result = accept(service, run, actor=reviewer)
    assert result.state == "FAILED"
    assert service._transition.call_args.kwargs["actor_id"] == reviewer


@pytest.mark.parametrize("changed", ("version", "request", "proposal", "state"))
def test_preaccept_failure_rechecks_locked_version_and_pins(tmp_path, monkeypatch, changed):
    service, run, _fixture = acceptance_case(tmp_path, monkeypatch, "hash")
    current = NS(**vars(run))
    if changed == "version":
        current.lock_version += 1
    elif changed == "request":
        current.request_sha256 = "sha256:" + "f" * 64
    elif changed == "proposal":
        current.proposal_content_set_sha256 = "sha256:" + "f" * 64
    else:
        current.state = "ACCEPTED"
    service._locked_run.return_value = current
    with pytest.raises(owner.KnowledgeAnalysisServiceError) as raised:
        accept(service, run)
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT"
    service._transition.assert_not_called()
    service._commit_json_artifact.assert_not_called()


def test_artifact_hash_failure_is_not_converted_to_model_failure(tmp_path, monkeypatch):
    service, run, fixture = acceptance_case(tmp_path, monkeypatch)
    fixture.reader.read_member.side_effect = ValueError("synthetic Artifact hash mismatch")
    with pytest.raises(KnowledgeProposalResolutionError):
        accept(service, run)
    service._transition.assert_not_called()
    service._commit_json_artifact.assert_not_called()


def test_already_accepted_base_is_never_reclassified_or_mutated(tmp_path, monkeypatch):
    service, run, _fixture = acceptance_case(tmp_path, monkeypatch, "hash")
    run.state = "ACCEPTED"
    assert accept(service, run) is run
    service._stored_receipt.assert_not_called()
    service._transition.assert_not_called()
    service._commit_json_artifact.assert_not_called()
