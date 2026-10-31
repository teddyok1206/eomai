"""Application-family and source-anchor invariants; no live DB, model or NAS."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceiptV10,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV11,
    KnowledgeAnalysisWorkerProposal,
)
from eom_catalog_service import knowledge_analysis_service as application
from eom_catalog_service.knowledge_analysis_risk import evaluate_knowledge_analysis_risk
from eom_catalog_service.registered_item_solution_base import (
    registered_item_solution_reference_index,
    resolve_registered_item_solution_base,
)
from eom_identifiers import content_sha256

from tests.unit.test_knowledge_analysis_risk import _policy
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_analysis_models import receipt_value


def base_request():
    value = request_value()
    base = value.pop("base_analysis")
    value.update(
        schema_version="knowledge-analysis-request/2.0",
        analysis_request_id=base["analysis_request_id"],
        predecessor_analysis_run_id=None,
        worker_proposal_schema_ref="eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0",
        accepted_result_schema_ref="eom://schemas/knowledge/knowledge-analysis-result/2.0",
        requested_outputs=list(application.REQUESTED_OUTPUTS),
    )
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return KnowledgeAnalysisRequestV2.model_validate(value)


def source_fixture(version="3.0"):
    request = base_request()
    value = (
        dict(schema_version=version, body=[dict(text="조건")], solution=dict(explanation="해설"))
        if version == "1.0"
        else dict(schema_version=version, stem="조건", explanations=dict(main="해설"))
    )
    paths = (
        ("/body/0/text", "/solution/explanation")
        if version == "1.0"
        else ("/stem", "/explanations/main")
    )
    pointer = request.source.artifact_member
    proposal = dict(
        schema_version="knowledge-analysis-worker-proposal/1.0",
        analysis_request_id=request.analysis_request_id,
        normalized_markdown="# Source",
        anchors=[
            dict(
                anchor_id=key,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                anchor_kind="ITEM_ELEMENT",
                locator=path,
                excerpt_sha256=content_sha256(text),
            )
            for key, path, text in zip(
                ("anchor_problem", "anchor_answer"), paths, ("조건", "해설"), strict=True
            )
        ],
        nodes=[
            dict(
                node_id="knode_concept_motion",
                node_type="CONCEPT",
                stable_key="physics.motion",
                label="운동",
                anchor_ids=["anchor_problem"],
            )
        ],
        edges=[],
        claims=[],
        component_observations=[],
        unresolved_ambiguities=[],
        general_knowledge_used=False,
        completed_at=request.created_at,
    )
    return request, proposal, value


@pytest.mark.parametrize("version", ["1.0", "2.0", "3.0"])
def test_registered_reference_index_uses_exact_source_fields_not_anchor_names(version):
    request, document, source = source_fixture(version)
    # Names deliberately contradict their true JSON locations.
    document["anchors"][0]["anchor_id"] = "anchor_answer_named_but_problem"
    document["anchors"][1]["anchor_id"] = "anchor_problem_named_but_answer"
    document["nodes"][0]["anchor_ids"] = ["anchor_answer_named_but_problem"]
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(document)
    index = registered_item_solution_reference_index(request, proposal, source)
    assert index.problem_anchor_ids == ("anchor_answer_named_but_problem",)
    assert index.answer_explanation_anchor_ids == ("anchor_problem_named_but_answer",)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_version",
        "non_pointer",
        "bad_escape",
        "missing_field",
        "array_negative",
        "array_leading_zero",
        "array_out_of_range",
        "wrong_member",
        "wrong_revision",
        "wrong_excerpt_hash",
        "metadata_anchor",
        "untyped_node",
    ],
)
def test_registered_reference_index_rejects_unverifiable_or_forged_source_roles(change):
    request, document, source = source_fixture("1.0")
    anchor = document["anchors"][0]
    if change == "unknown_version":
        source["schema_version"] = "999.0"
    elif change == "wrong_member":
        anchor["member_path"] = "other.json"
    elif change == "wrong_revision":
        anchor["artifact_revision_id"] = "rev_" + "0" * 32
    elif change == "wrong_excerpt_hash":
        anchor["excerpt_sha256"] = "sha256:" + "0" * 64
    elif change == "metadata_anchor":
        source["title"] = "조건"
        anchor["locator"] = "/title"
    elif change == "untyped_node":
        document["nodes"][0]["node_id"] = "knode_untyped"
    else:
        anchor["locator"] = {
            "non_pointer": "paragraph 1",
            "bad_escape": "/body/~2",
            "missing_field": "/missing",
            "array_negative": "/body/-1",
            "array_leading_zero": "/body/00",
            "array_out_of_range": "/body/1",
        }[change]
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(document)
    with pytest.raises(ValueError):
        registered_item_solution_reference_index(request, proposal, source)


def test_registered_reference_index_resolves_escaped_keys_and_array_values():
    request, document, source = source_fixture()
    source["explanations"] = {"a/b~c": ["해설"]}
    document["anchors"][1]["locator"] = "/explanations/a~1b~0c/0"
    index = registered_item_solution_reference_index(
        request, KnowledgeAnalysisWorkerProposal.model_validate(document), source
    )
    assert index.answer_explanation_anchor_ids == ("anchor_answer",)


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_registered_reference_index_does_not_treat_empty_source_fields_as_evidence(empty):
    request, document, source = source_fixture()
    source["stem"] = empty
    document["anchors"][0]["excerpt_sha256"] = content_sha256(empty)
    with pytest.raises(ValueError, match="no source content"):
        registered_item_solution_reference_index(
            request, KnowledgeAnalysisWorkerProposal.model_validate(document), source
        )


def test_new_application_family_selects_the_new_closed_receipt_and_distinct_protocol():
    request = KnowledgeAnalysisRequestV11.model_validate(request_value())
    assert application._analysis_request(request.model_dump(mode="json")) == request
    receipt = application._receipt_contract(receipt_value(), request)
    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV10)
    assert application._solution_contract(request)
    assert application._proposal_result_schema(request) == "knowledge-analysis-proposal-result@11.0"
    assert (
        application._proposal_receipt_schema(request)[0]
        == "knowledge-analysis-proposal-receipt-v10"
    )
    assert application._catalog_protocol(request)[0] == "catalog/1.27"
    assert application._catalog_protocol(request) != (
        application.KNOWLEDGE_ANALYSIS_SOLUTION_CATALOG_PROTOCOL,
        application.KNOWLEDGE_ANALYSIS_SOLUTION_CATALOG_SCHEMA_HASH,
    )
    with pytest.raises(application.KnowledgeAnalysisServiceError) as exc:
        application._receipt_contract(
            receipt_value() | {"schema_version": "knowledge-analysis-proposal-receipt/9.0"}, request
        )
    assert exc.value.code == "KNOWLEDGE_ANALYSIS_POINTER_INVALID"


def test_registered_solution_risk_and_counts_use_full_report_not_empty_base_fields():
    receipt = KnowledgeAnalysisProposalReceiptV10.model_validate(receipt_value())
    assert not evaluate_knowledge_analysis_risk(receipt, _policy()).requires_review
    value = deepcopy(receipt_value())
    value["solution_counts"]["unresolved_issues"] = 1
    receipt = KnowledgeAnalysisProposalReceiptV10.model_validate(value)
    assert evaluate_knowledge_analysis_risk(receipt, _policy()).reason_codes == (
        "BLOCKING_AMBIGUITY_PRESENT",
    )
    run = NS()
    application.KnowledgeAnalysisApplicationService._apply_proposal(
        run, receipt, NS(job_id="job", logical_artifact_id="artifact", revision_id="revision")
    )
    assert run.node_count == receipt.base_analysis.base_counts.nodes
    assert run.proposal_content_set_sha256 == receipt.content_set_sha256


def test_solution_member_reader_is_shared_and_pins_new_receipt_report_bytes():
    from eom_catalog_service.knowledge_proposal_resolution import (
        resolve_knowledge_solution_proposal,
    )
    from eom_identifiers import canonical_json_bytes

    from tests.unit.test_past_exam_solution_analysis_contracts import _role_result_value

    report = _role_result_value()["output"]["proposal"]["solution_report"]
    raw = canonical_json_bytes(report)
    value = receipt_value()
    value["solution_report"].update(bytes=len(raw), sha256=content_sha256(report))
    from eom_catalog_contracts import (
        KnowledgeProposalArtifactMember,
        RegisteredItemSolutionBasePointer,
    )
    from eom_catalog_contracts.knowledge import knowledge_solution_content_set_sha256

    value["content_set_sha256"] = knowledge_solution_content_set_sha256(
        RegisteredItemSolutionBasePointer.model_validate(value["base_analysis"]).base_members,
        KnowledgeProposalArtifactMember.model_validate(value["solution_report"]),
    )
    receipt = KnowledgeAnalysisProposalReceiptV10.model_validate(value)
    reader = Mock(spec=["read_member"])
    reader.read_member.return_value = raw
    result = resolve_knowledge_solution_proposal(reader, receipt)
    assert result.solution_report.model_dump(mode="json") == report
    assert reader.read_member.call_count == 1
    assert reader.read_member.call_args.kwargs["sha256"] == receipt.solution_report.sha256


def accepted_chain(tmp_path):
    from eom_identifiers import sha256_bytes

    from tests.unit.test_registered_item_solution_execution_plan import base_files

    fixture = base_files(tmp_path)
    base = fixture.plan.base_analysis
    request = fixture.base_request

    def read_member(**kwargs):
        raw = (
            fixture.root / kwargs["artifact_id"] / kwargs["revision_id"] / kwargs["member_path"]
        ).read_bytes()
        assert len(raw) <= kwargs["max_bytes"]
        assert sha256_bytes(raw) == kwargs["sha256"]
        return raw

    reader = Mock(spec=["read_member"])
    reader.read_member.side_effect = read_member
    run = NS(
        state="ACCEPTED",
        analysis_run_id=base.analysis_run_id,
        analysis_request_id=request.analysis_request_id,
        request_sha256=request.request_sha256,
        accepted_result_artifact_id=base.accepted_result_artifact.artifact_id,
        accepted_result_artifact_revision_id=base.accepted_result_artifact.artifact_revision_id,
        accepted_result_sha256=fixture.accepted_revision.content_hash,
    )
    return NS(
        fixture=fixture,
        request=request,
        receipt=fixture.base_receipt,
        receipt_pointer=base.proposal_receipt,
        reader=reader,
        run=run,
        revision=fixture.accepted_revision,
    )


def test_registered_base_resolver_keeps_distinct_result_self_hash_and_file_hash(tmp_path):
    fixture = accepted_chain(tmp_path)
    # Real base JSONL content is resolved, not substituted by a report summary.
    result = resolve_registered_item_solution_base(
        fixture.fixture.session,
        fixture.reader,
        run=fixture.run,
        request=fixture.request,
        receipt=fixture.receipt,
        receipt_pointer=fixture.receipt_pointer,
    )
    assert result.accepted_result_sha256 != result.accepted_result_artifact.sha256
    assert result.reference_index.problem_anchor_ids == ("anchor_problem",)
    assert result.reference_index.answer_explanation_anchor_ids == ("anchor_answer",)
    assert not hasattr(result.base_members, "page_image_observations")


@pytest.mark.parametrize("change", ["retired", "missing", "different_cache", "stale_hash"])
def test_registered_base_resolver_rejects_invalid_accepted_artifact(tmp_path, change):
    fixture = accepted_chain(tmp_path)
    if change == "retired":
        fixture.revision.approved = False
    elif change == "missing":
        fixture.run.accepted_result_artifact_revision_id = None
    elif change == "different_cache":
        fixture.revision.result = fixture.revision.result | {
            "analysis_request_sha256": "sha256:" + "0" * 64
        }
    else:
        fixture.run.accepted_result_sha256 = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        resolve_registered_item_solution_base(
            fixture.fixture.session,
            fixture.reader,
            run=fixture.run,
            request=fixture.request,
            receipt=fixture.receipt,
            receipt_pointer=fixture.receipt_pointer,
        )


def test_create_registered_solution_reuses_atomic_analysis_submission_and_exact_family(
    tmp_path, monkeypatch
):
    from contextlib import nullcontext

    from eom_catalog_contracts import CreateKnowledgeSolutionAnalysisCommand
    from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord

    fixture = accepted_chain(tmp_path)
    base = fixture.run
    base.canonical_request = fixture.request.model_dump(mode="json")
    base.risk_policy_revision_id = fixture.request.risk_policy_revision_id
    session = fixture.fixture.session
    session.scalar.side_effect = [None, base]
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr(application, "transaction", lambda _sessions: nullcontext(session))
    service = object.__new__(application.KnowledgeAnalysisApplicationService)
    service.sessions = Mock()
    service.artifacts = fixture.reader
    original = fixture.fixture.plan
    service.published_preset = Mock(
        return_value=(
            NS(preset_id=original.preset_id),
            NS(
                preset_revision_id=original.preset_revision_id,
                content_sha256=original.preset_sha256,
                compatible_workflow_protocols=["workflow-role/1.35.0"],
            ),
        )
    )
    service.risk_policy = Mock(
        return_value=NS(
            risk_policy_revision_id=fixture.request.risk_policy_revision_id,
            content_sha256="sha256:" + "7" * 64,
        )
    )
    service._stored_receipt = Mock(return_value=fixture.receipt)
    service._proposal_receipt_pointer = Mock(return_value=fixture.receipt_pointer)
    service._projection = Mock(side_effect=lambda run: run)
    service._transition = Mock(
        side_effect=lambda _session, run, state, *_args, **_kw: setattr(run, "state", state)
    )
    source_resolver = Mock(return_value=fixture.request.source)
    monkeypatch.setattr(application, "resolve_approved_item_source", source_resolver)
    definition = Mock(
        return_value=NS(definition_version="11.0.0", definition_hash="sha256:" + "8" * 64)
    )
    monkeypatch.setattr(application, "admitted_workflow_definition", definition)
    workflow = NS(
        workflow_id=original.workflow_id,
        role_schema_version="workflow-role/1.35.0",
        runtime_context={},
    )
    create = Mock(return_value=(workflow, True))
    monkeypatch.setattr(application, "create_workflow_instance", create)
    resolve = Mock(return_value=original)
    monkeypatch.setattr(application, "resolve_knowledge_analysis_plan", resolve)
    enqueue = Mock()
    monkeypatch.setattr(application, "enqueue_command", enqueue)
    command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id=base.analysis_run_id,
        requested_by="operator_" + "5" * 32,
        idempotency_key="registered-solution-unit-test-1",
    )
    result = service.create_solution(command)
    assert isinstance(result, KnowledgeAnalysisRunRecord)
    assert result.state == "QUEUED"
    assert result.predecessor_analysis_run_id == base.analysis_run_id
    assert result.created_by_operator_id == command.requested_by
    request = create.call_args.kwargs["request"]
    assert isinstance(request.analysis_request, KnowledgeAnalysisRequestV11)
    assert request.image_mode == "skip"
    assert request.analysis_request.base_analysis.accepted_result_sha256 != (
        request.analysis_request.base_analysis.accepted_result_artifact.sha256
    )
    assert (
        source_resolver.call_args.kwargs["item_revision_id"]
        == fixture.request.source.item_revision_id
    )
    assert definition.call_args.kwargs["definition_version"] == "11.0.0"
    assert resolve.call_args.kwargs["request"] == request.analysis_request
    assert enqueue.call_count == 1
    assert create.call_args.kwargs["actor_id"] == command.requested_by


@pytest.mark.parametrize("different_input", [False, True])
def test_registered_solution_replay_does_not_resolve_latest_or_enqueue_a_duplicate(
    monkeypatch, different_input
):
    from contextlib import nullcontext

    from eom_catalog_contracts import CreateKnowledgeSolutionAnalysisCommand

    command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id=request_value()["predecessor_analysis_run_id"],
        requested_by="operator_" + "5" * 32,
        idempotency_key="registered-solution-replay-1",
    )
    submission = content_sha256(
        command.model_dump(mode="json", exclude={"operation", "idempotency_key"})
    )
    replay = NS(submission_sha256="sha256:" + "0" * 64 if different_input else submission)
    session = Mock()
    session.scalar.return_value = replay
    monkeypatch.setattr(application, "transaction", lambda _sessions: nullcontext(session))
    service = object.__new__(application.KnowledgeAnalysisApplicationService)
    service.sessions = Mock()
    service._projection = Mock(side_effect=lambda run: run)
    enqueue = Mock()
    monkeypatch.setattr(application, "enqueue_command", enqueue)
    if different_input:
        with pytest.raises(application.KnowledgeAnalysisServiceError) as exc:
            service.create_solution(command)
        assert exc.value.code == "KNOWLEDGE_ANALYSIS_IDEMPOTENCY_CONFLICT"
    else:
        assert service.create_solution(command) is replay
    assert session.scalar.call_count == 1
    session.add.assert_not_called()
    enqueue.assert_not_called()


def test_registered_solution_acceptance_keeps_v11_schema_protocol_and_full_report_counts(
    monkeypatch,
):
    from contextlib import nullcontext
    from unittest.mock import MagicMock

    from eom_catalog_contracts import KnowledgeAnalysisResultV11, KnowledgeProposalArtifactMember

    from tests.unit.test_registered_item_solution_analysis_models import result_value

    request = KnowledgeAnalysisRequestV11.model_validate(request_value())
    receipt = KnowledgeAnalysisProposalReceiptV10.model_validate(receipt_value())
    receipt_pointer = KnowledgeProposalArtifactMember.model_validate(
        result_value()["proposal_receipt"]
    )
    run = NS(
        analysis_run_id="analysisrun_" + "6" * 32,
        state="VALIDATING",
        canonical_request=request.model_dump(mode="json"),
        risk_policy_revision_id=request.risk_policy_revision_id,
    )
    session = Mock()
    session.get.return_value = run
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = session
    monkeypatch.setattr(application, "transaction", lambda _sessions: nullcontext(session))
    service = object.__new__(application.KnowledgeAnalysisApplicationService)
    service.sessions = sessions
    service._stored_receipt = Mock(return_value=receipt)
    service._proposal_receipt_pointer = Mock(return_value=receipt_pointer)
    service.risk_policy = Mock(
        return_value=NS(
            risk_policy_revision_id=request.risk_policy_revision_id,
            content_sha256="sha256:" + "8" * 64,
        )
    )
    committed = {}

    def commit(**kwargs):
        committed.update(kwargs)
        return NS(
            artifact_id="artifact_" + "8" * 32,
            revision_id="rev_" + "8" * 32,
            content_hash=content_sha256(kwargs["result"]),
        )

    service._commit_json_artifact = Mock(side_effect=commit)
    service._artifact_result = Mock(
        side_effect=lambda _artifact, model, _schema: model.model_validate(committed["result"])
    )
    service._locked_run = Mock(return_value=run)
    service._transition = Mock(
        side_effect=lambda _session, row, state, *_args, **_kwargs: setattr(row, "state", state)
    )
    service._projection = Mock(side_effect=lambda row: row)
    result = service._accept(
        run.analysis_run_id,
        acceptance_mode="AUTO_POLICY",
        review_pointer=None,
        actor_id="operator_" + "5" * 32,
    )
    assert result.state == "ACCEPTED"
    assert committed["protocol"] == application._catalog_protocol(request)
    assert committed["schema_ref"] == "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    accepted = KnowledgeAnalysisResultV11.model_validate(committed["result"])
    assert accepted.base_analysis == request.base_analysis
    assert accepted.solution_counts == receipt.solution_counts
    assert accepted.counts == receipt.base_analysis.base_counts
    assert accepted.minimum_confidence_milli is None
