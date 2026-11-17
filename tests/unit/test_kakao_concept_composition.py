"""Actual bounded input publication logic; synthetic Graph/Workflow ports, no Codex/NAS."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import EvidenceBudget
from eom_catalog_contracts.kakao_concept_knowledge import (
    KakaoConceptKnowledge,
    KakaoConceptResultPin,
)
from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptIntent
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import kakao_concept_composition as module
from eom_catalog_service import kakao_concept_knowledge as knowledge_module
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_concept_phase_results import CompletedKakaoConceptPhase
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.kakao_concept_request import KakaoConceptWork
from eom_workflow.kakao_concept_result import KakaoConceptRoleResult

from tests.unit.general_chat_rag_fixtures import scope
from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_kakao_concept_contracts import ROOT, plan, plan_request, result
from tests.unit.test_kakao_concept_knowledge import actor, policy, snapshot
from tests.unit.test_kakao_concept_knowledge import reader as knowledge_reader
from tests.unit.test_kakao_concept_pages import prepared
from tests.unit.test_kakao_concept_tasks import intent_value
from tests.unit.test_kakao_concept_workflow_contracts import message, work_value


def fixture(monkeypatch, tmp_path, *, family="V5"):
    artifacts, pages, _, _ = prepared(tmp_path, family=family)
    request = plan_request()
    work = KakaoConceptWork.model_validate(work_value(request))
    input_value = message(request)
    body = {
        key: input_value[key]
        for key in (
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "role",
            "artifact",
        )
    }
    body.update(status="ok", completed_at="2026-11-17T11:00:00Z", output=result(request, plan()))
    output = KakaoConceptRoleResult.model_validate(body)
    pin = KakaoConceptResultPin(
        workflow_id=output.workflow_id,
        step_run_id=output.step_run_id,
        job_id=output.job_id,
        artifact_id=output.artifact.logical_artifact_id,
        artifact_revision_id=output.artifact.revision_id,
        sha256=content_sha256(output),
    )
    planned = CompletedKakaoConceptPhase(work, pin, request, output)
    monkeypatch.setattr(module, "read_kakao_concept_phase_result", Mock(return_value=planned))
    intent = intent_value()
    intent.update(
        task_id=request.task_id,
        scope=pages.knowledge.scope.model_dump(mode="json"),
        question_manifest=work.question_manifest.model_dump(mode="json"),
    )
    service = Mock()
    service.artifacts = artifacts
    service.sessions.return_value.__enter__ = Mock(return_value=Mock())
    service.sessions.return_value.__exit__ = Mock(return_value=None)
    session = service.sessions.return_value.__enter__.return_value
    session.get.return_value = None
    authority = Mock()
    authority.service, authority.owner_operator_id = service, "operator_" + "a" * 32
    authority.intent = KakaoConceptIntent.model_validate(intent)
    authority.reauthorize.side_effect = lambda _session, **kwargs: kwargs["work"]
    service.source_authority.return_value = authority
    service.adopt_accepted_phase.side_effect = lambda *_args: _args[-1]
    reader = Mock(spec=knowledge_module.KakaoConceptKnowledgeReader)
    reader.retrieve.return_value = pages.knowledge
    reader.restore.return_value = pages.knowledge
    reader.prepare_pages.return_value = pages
    captured = {}

    def publish(**kwargs):
        captured.update({name: path.read_bytes() for name, path in kwargs["files"].items()})
        return SimpleNamespace(
            artifact_id="artifact_" + "e" * 32,
            revision_id="rev_" + "e" * 32,
            content_hash=sha256_bytes(captured["request.json"]),
            content_bytes=len(captured["request.json"]),
        )

    artifacts.commit_file_set.side_effect = publish
    value = SimpleNamespace(
        service=service,
        reader=reader,
        authority=authority,
        planned=planned,
        pages=pages,
        artifacts=artifacts,
        captured=captured,
        session=session,
    )
    return value


def prepare(value):
    return module.prepare_kakao_concept_composition(
        value.service,
        value.reader,
        actor=actor(),
        binding_id=value.planned.work.source_binding_id,
        task_id=value.planned.work.task_id,
    )


def bind_input_reads(value, work):
    receipt_bytes = value.captured["knowledge.json"]
    pointer = ArtifactMemberPointer(
        artifact_id=work.request_member.artifact_id,
        artifact_revision_id=work.request_member.artifact_revision_id,
        member_path="knowledge.json",
        schema_ref=module.CONCEPT_KNOWLEDGE_REF,
        media_type="application/json",
        sha256=sha256_bytes(receipt_bytes),
    )
    value.artifacts.published_member_pointer.return_value = pointer
    value.artifacts.read_member.side_effect = lambda **kwargs: value.captured[kwargs["member_path"]]


@pytest.mark.parametrize("family", ["V3", "V4", "V5"])
def test_plan_to_official_reader_and_composition_retains_original_page_pointers(
    monkeypatch, tmp_path, family
):
    value = fixture(monkeypatch, tmp_path, family=family)
    work = prepare(value)
    receipt = KakaoConceptKnowledge.model_validate_json(value.captured["knowledge.json"])
    assert receipt.plan_result == value.planned.pin
    assert receipt.materials == tuple(
        material.pin() for material in value.pages.knowledge.materials
    )
    assert receipt.request_sha256 == work.request_member.sha256
    assert work.phase == "COMPOSE"
    assert set(value.artifacts.commit_file_set.call_args.kwargs["files"]) == {
        "request.json",
        "knowledge.json",
    }
    assert all(
        file.source
        in {
            *(file.source for file in value.planned.work.files),
            *(page.original for page in value.pages.sources),
        }
        for file in work.files
    )
    value.reader.retrieve.assert_called_once()
    assert value.reader.retrieve.call_args.kwargs["scope"] == value.authority.intent.scope
    value.service.adopt_accepted_phase.assert_called_once()
    bind_input_reads(value, work)
    restored = module.authorize_kakao_concept_composition(value.reader, value.authority, work)
    assert restored == value.pages.knowledge
    value.reader.restore.assert_called_once()
    if family == "V3":
        assert not receipt.pages and not value.pages.context.pages
    else:
        assert receipt.pages and work.files[-1].source == receipt.pages[0].original


def test_existing_phase_reuses_accepted_work_without_retrieval_publication_or_adoption(
    monkeypatch, tmp_path
):
    value = fixture(monkeypatch, tmp_path)
    work = prepare(value)
    value.session.get.return_value = SimpleNamespace(work_input=work.model_dump(mode="json"))
    for mock in (
        value.reader.retrieve,
        value.reader.prepare_pages,
        value.artifacts.commit_file_set,
        value.service.adopt_accepted_phase,
    ):
        mock.reset_mock()
    assert prepare(value) == work
    value.reader.retrieve.assert_not_called()
    value.reader.prepare_pages.assert_not_called()
    value.artifacts.commit_file_set.assert_not_called()
    value.service.adopt_accepted_phase.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "input-hash",
        "scope",
        "plan-result",
        "analysis",
        "file-pointer",
        "page-pointer",
        "instructions",
    ],
)
def test_saved_context_never_accepts_changed_plan_scope_text_or_original(
    monkeypatch, tmp_path, change
):
    value = fixture(monkeypatch, tmp_path)
    work = prepare(value)
    import json

    request = json.loads(value.captured["request.json"])
    receipt = json.loads(value.captured["knowledge.json"])
    if change == "scope":
        receipt["scope"]["snapshot"]["sha256"] = "sha256:" + "0" * 64
    elif change == "plan-result":
        receipt["plan_result"]["job_id"] = "job_" + "0" * 32
    elif change == "analysis":
        request["context"]["evidence"][0]["analysis_text"] = "invented source text"
        request["context"]["context_sha256"] = content_sha256(
            {key: val for key, val in request["context"].items() if key != "context_sha256"}
        )
    elif change == "instructions":
        request["additional_instructions"] = "different accepted request"
    elif change == "page-pointer":
        receipt["pages"][0]["original"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif change == "file-pointer":
        body = work.model_dump(mode="json")
        body["files"][-1]["source"]["artifact_revision_id"] = "rev_" + "f" * 32
        work = KakaoConceptWork.model_validate(body)
    value.captured["request.json"] = canonical_json_bytes(request)
    if change != "input-hash":
        digest = sha256_bytes(value.captured["request.json"])
        receipt["request_sha256"] = digest
        body = work.model_dump(mode="json")
        body["request_member"]["sha256"] = digest
        body["request_bytes"] = len(value.captured["request.json"])
        work = KakaoConceptWork.model_validate(body)
    else:
        receipt["request_sha256"] = "sha256:" + "0" * 64
    value.captured["knowledge.json"] = canonical_json_bytes(receipt)
    bind_input_reads(value, work)
    with pytest.raises((ValueError, KakaoArchiveError)):
        module.authorize_kakao_concept_composition(value.reader, value.authority, work)


def test_knowledge_schema_and_mirror_are_pinned_and_reject_item_as_textbook(monkeypatch, tmp_path):
    value = fixture(monkeypatch, tmp_path)
    prepare(value)
    entry = CATALOG_SCHEMA_RESOURCES["kakao-concept-knowledge-v1"]
    raw = (ROOT / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    receipt = KakaoConceptKnowledge.model_validate_json(value.captured["knowledge.json"])
    body = receipt.model_dump(mode="json")
    body["materials"][0]["source"]["source_class"] = "INTERNAL_GUIDE"
    with pytest.raises(ValueError):
        KakaoConceptKnowledge.model_validate(body)


def authoring_scope_fixture(monkeypatch):
    owner, _, _ = knowledge_reader(monkeypatch)
    logical, revision = _published_preset()
    preset = deepcopy(revision.canonical_document)
    policy_value = policy()
    preset.update(
        schema_version="execution-preset-revision/2.0",
        retrieval_policy=dict(
            access_policy_revision_id=scope().policy.access_policy_revision_id,
            access_policy_sha256=scope().policy.sha256,
            allowed_corpus_keys=["integrated-science-textbooks"],
            allowed_query_kinds=["ITEM_PREPARATION"],
            allowed_source_classes=["TEXTBOOK"],
            maximum_budget=EvidenceBudget.model_validate(
                vars(policy_value.maximum_budget)
            ).model_dump(mode="json"),
        ),
    )
    preset["role_policies"][0]["evidence_access"] = "EVIDENCE_CONTEXT"
    preset["content_sha256"] = content_sha256(
        {k: v for k, v in preset.items() if k != "content_sha256"}
    )
    model = ExecutionPresetRevisionV2.model_validate(preset)
    revision.canonical_document = model.model_dump(mode="json")
    revision.content_sha256 = model.content_sha256
    revision.preset_revision_id, revision.revision_number = (
        model.preset_revision_id,
        model.revision_number,
    )
    corpus = SimpleNamespace(
        current_graph_snapshot_revision_id=snapshot().graph_snapshot_revision_id,
        graph_id=snapshot().graph_id,
    )
    session = Mock()
    session.scalar.side_effect = [logical, corpus]
    session.get.side_effect = [revision, SimpleNamespace(snapshot_sha256="sha256:" + "1" * 64)]
    owner.retrieval.resolve_snapshot_pointer.return_value = snapshot()
    return owner, session, logical, revision, corpus


def test_initial_scope_uses_current_published_authoring_policy_without_selecting_latest_history(
    monkeypatch,
):
    owner, session, _, revision, _ = authoring_scope_fixture(monkeypatch)
    captured = owner.capture_authoring_scope(session, actor(), "binding")
    assert (
        captured.policy.access_policy_revision_id
        == revision.canonical_document["retrieval_policy"]["access_policy_revision_id"]
    )
    assert captured.snapshot.graph_snapshot_revision_id == snapshot().graph_snapshot_revision_id
    owner._authority.assert_called_once_with(session, actor(), "binding", captured)


@pytest.mark.parametrize(
    "change", ["inactive", "unpublished", "wrong-owner", "wrong-hash", "wrong-graph"]
)
def test_initial_scope_rejects_missing_or_mixed_published_inputs(monkeypatch, change):
    owner, session, logical, revision, corpus = authoring_scope_fixture(monkeypatch)
    if change == "inactive":
        logical.state = "RETIRED"
    elif change == "unpublished":
        logical.current_revision_id = None
    elif change == "wrong-owner":
        revision.preset_id = "execpreset_" + "0" * 32
    elif change == "wrong-hash":
        revision.content_sha256 = "sha256:" + "0" * 64
    else:
        corpus.graph_id = "graph_" + "0" * 32
    with pytest.raises((ValueError, RuntimeError)):
        owner.capture_authoring_scope(session, actor(), "binding")


@pytest.mark.parametrize("change", [None, "accepted-result", "normalized", "analysis", "source"])
def test_restoring_saved_selection_reads_exact_sources_and_never_reranks(
    monkeypatch, tmp_path, change
):
    value = fixture(monkeypatch, tmp_path, family="V3")
    prepare(value)
    receipt = KakaoConceptKnowledge.model_validate_json(value.captured["knowledge.json"])
    owner, _, contexts = knowledge_reader(monkeypatch)
    selected = next(iter(contexts.values()))
    original = receipt.materials[0]
    # Use the exact current-source model produced by the real immutable materializer helper.
    pin = knowledge_module.ConceptTextbookMaterial(
        original.title, original.node_ids, selected
    ).pin()
    receipt = receipt.model_copy(update={"materials": (pin,)})
    if change is not None:
        body = receipt.model_dump(mode="json")
        if change in {"accepted-result", "normalized"}:
            body["materials"][0][
                "accepted_result" if change == "accepted-result" else "normalized_markdown"
            ]["artifact_revision_id"] = "rev_" + "f" * 32
        elif change == "analysis":
            body["materials"][0]["analysis_text_sha256"] = "sha256:" + "f" * 64
        else:
            body["materials"][0]["source"]["document_revision_id"] = "edudocrev_" + "f" * 32
        receipt = KakaoConceptKnowledge.model_validate(body)
        with pytest.raises(KakaoArchiveError):
            owner.restore(actor(), "binding", receipt, reauthorize_question=Mock())
    else:
        restored = owner.restore(actor(), "binding", receipt, reauthorize_question=Mock())
        assert restored.materials[0].pin() == receipt.materials[0]
    owner.retrieval.topic_keys_for_terms.assert_not_called()
    owner.retrieval.retrieve_material_read_only.assert_not_called()
