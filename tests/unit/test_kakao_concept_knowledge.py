"""Core read-only retrieval, exact source provenance and current private-question authorization."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import eom_catalog_service.kakao_concept_knowledge as module
import pytest
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_service.item_textbook_context import (
    TextbookContextSelection,
    resolve_item_textbook_context,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_concept_knowledge import KakaoConceptKnowledgeReader
from eom_catalog_service.knowledge_retrieval_service import (
    EvidenceSourceFamily,
    KnowledgeRetrievalApplicationService,
)
from eom_kakao_archive_contracts.concepts import ConceptPlan
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey

from tests.unit.general_chat_rag_fixtures import HASH, scope
from tests.unit.test_chat_rag_resolution import (
    ACTOR,
    PERMISSIONS,
    RowsSession,
    candidate,
    materialized,
    pointer_rows,
    policy,
)
from tests.unit.test_kakao_concept_contracts import plan
from tests.unit.test_material_knowledge_contracts import source as uploaded_source


def actor():
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=ACTOR,
        session_id="apisession_" + "1" * 32,
        request_id="kakao-concept-synthetic",
        authentication_time=datetime(2026, 11, 17, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )


def snapshot():
    return KnowledgeGraphSnapshotPointer(
        graph_id="graph_" + "1" * 32,
        graph_snapshot_revision_id=scope().snapshot.graph_snapshot_revision_id,
        manifest_artifact=dict(
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "2" * 32,
            member_path="evidence/graph.json",
            logical_name="graph.json",
            media_type="application/json",
            schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/10.0",
            sha256=HASH,
        ),
        manifest_sha256=HASH,
    )


def resolved(value):
    association, pointer = pointer_rows(value)
    read = Mock()
    read.resolve_accepted_analyses.return_value = {value.analysis.analysis_run_id: value}
    selection = TextbookContextSelection(
        value.analysis.analysis_run_id,
        value.analysis.source,
        candidate(value).node_ids,
        candidate(value).anchor_ids,
    )
    return resolve_item_textbook_context(
        RowsSession((association,), (pointer,)),
        analyses=read,
        graph_snapshot_revision_id=scope().snapshot.graph_snapshot_revision_id,
        selections=(selection,),
    )[value.analysis.analysis_run_id]


def reader(monkeypatch, *, empty=False, count=1):
    owner = object.__new__(KakaoConceptKnowledgeReader)
    owner.sessions = MagicMock()
    owner.retrieval = Mock(spec=KnowledgeRetrievalApplicationService)
    owner.analyses = Mock()
    owner._authority = Mock(return_value=("EDITOR", PERMISSIONS, policy(), snapshot()))
    values = tuple(materialized(i) for i in range(1, count + 1))
    contexts = {} if empty else {v.analysis.analysis_run_id: resolved(v) for v in values}
    owner.retrieval.topic_keys_for_terms.return_value = () if empty else ("science.spacetime",)
    owner.retrieval.retrieve_material_read_only.return_value = SimpleNamespace(
        request=SimpleNamespace(
            graph_snapshot=snapshot(), access_policy_sha256=scope().policy.sha256
        ),
        candidates=tuple(candidate(v) for v in values),
    )
    resolver = Mock(return_value=contexts)
    monkeypatch.setattr(module, "resolve_item_textbook_context", resolver)
    owner._titles = Mock(return_value={key: "교재 이름" for key in contexts})
    return owner, resolver, contexts


def test_model_plan_reads_actual_actor_same_scope_and_current_authoring_source_family(monkeypatch):
    owner, read, contexts = reader(monkeypatch)
    question = Mock()
    value = owner.retrieve(
        actor(),
        "binding",
        scope=scope(),
        plan=ConceptPlan.model_validate(plan()),
        reauthorize_question=question,
    )
    call = owner.retrieval.retrieve_material_read_only.call_args
    command = call.args[1]
    assert command.requested_by == ACTOR and command.requester_role == "EDITOR"
    assert tuple(str(c) for c in command.source_classes) == ("TEXTBOOK",)
    assert command.evidence_budget.max_item_revisions == 0
    assert owner.retrieval.topic_keys_for_terms.call_args.kwargs["terms"] == (
        "관계",
        "광도",
        "별의",
        "질량",
        "질량과",
    )
    assert question.call_count == 3 and read.call_count == 2
    assert value.snapshot == snapshot() and value.scope == scope()
    assert value.materials[0].analysis == next(iter(contexts.values()))
    worker = value.worker_context()
    assert worker.evidence[0].evidence_key == "E1"
    assert worker.evidence[0].analysis_text == value.materials[0].analysis.approved_analysis_text
    assert not worker.pages and not worker.evidence[0].original_passages
    assert any("원문 페이지" in t for t in worker.limitations)


def test_empty_retrieval_still_checks_exact_pins_and_does_not_invent_evidence(monkeypatch):
    owner, _, _ = reader(monkeypatch, empty=True)
    value = owner.retrieve(
        actor(),
        "binding",
        scope=scope(),
        plan=ConceptPlan.model_validate(plan()),
        reauthorize_question=lambda: None,
    )
    assert owner._authority.call_count == 2
    owner.retrieval.retrieve_material_read_only.assert_not_called()
    assert not value.materials and not value.worker_context().evidence
    assert any("찾지 못했습니다" in t for t in value.worker_context().limitations)


def test_uploaded_material_v5_and_accepted_v12_keep_all_source_and_rights_pointers():
    from eom_catalog_contracts.material_knowledge_analysis import (
        EducationalDocumentKnowledgeSourceV5,
    )

    previous = materialized()
    source = EducationalDocumentKnowledgeSourceV5.model_validate(uploaded_source())
    accepted = previous.analysis.accepted_result.model_copy(
        update={
            "schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/12.0",
        }
    )
    value = replace(
        previous, analysis=replace(previous.analysis, source=source, accepted_result=accepted)
    )
    loaded = resolved(value)
    assert loaded.source == source
    assert loaded.source.material_revision_id == source.material_revision_id
    assert loaded.source.rights_attestation == source.rights_attestation
    assert loaded.source.materialization_members == source.materialization_members
    assert loaded.accepted_result.schema_ref.endswith("/12.0")
    assert (
        json.loads(loaded.as_markdown().splitlines()[-1])["approved_analysis_text"]
        == loaded.approved_analysis_text
    )


def test_three_selected_analyses_stop_further_queries_and_are_materialized_together(monkeypatch):
    owner, read, _ = reader(monkeypatch, count=3)
    proposed = plan()
    proposed["queries"] = [dict(concept="개념", query=f"질의{i}", reason="연결") for i in range(4)]
    value = owner.retrieve(
        actor(),
        "binding",
        scope=scope(),
        plan=ConceptPlan.model_validate(proposed),
        reauthorize_question=lambda: None,
    )
    assert owner.retrieval.retrieve_material_read_only.call_count == 1
    assert len(read.call_args_list[0].kwargs["selections"]) == 3
    assert tuple(e.evidence_key for e in value.worker_context().evidence) == ("E1", "E2", "E3")


def test_question_denial_precedes_retrieval(monkeypatch):
    owner, _, _ = reader(monkeypatch)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        owner.retrieve(
            actor(),
            "binding",
            scope=scope(),
            plan=ConceptPlan.model_validate(plan()),
            reauthorize_question=Mock(
                side_effect=KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            ),
        )
    owner.retrieval.topic_keys_for_terms.assert_not_called()


def test_question_revoked_after_read_does_not_return_partial_data(monkeypatch):
    owner, _, _ = reader(monkeypatch)
    question = Mock(side_effect=[None, KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")])
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        owner.retrieve(
            actor(),
            "binding",
            scope=scope(),
            plan=ConceptPlan.model_validate(plan()),
            reauthorize_question=question,
        )
    assert owner.retrieval.retrieve_material_read_only.call_count == 1


def test_changed_readback_and_changed_graph_pointer_are_not_latest_recovery(monkeypatch):
    owner, read, contexts = reader(monkeypatch)
    altered = {
        key: replace(value, approved_analysis_text="changed") for key, value in contexts.items()
    }
    read.side_effect = [contexts, altered]
    with pytest.raises(KakaoArchiveError, match="POINTER_INVALID"):
        owner.retrieve(
            actor(),
            "binding",
            scope=scope(),
            plan=ConceptPlan.model_validate(plan()),
            reauthorize_question=lambda: None,
        )
    owner, _, _ = reader(monkeypatch)
    owner.retrieval.retrieve_material_read_only.return_value.request.access_policy_sha256 = (
        "sha256:" + "9" * 64
    )
    with pytest.raises(KakaoArchiveError, match="POINTER_INVALID"):
        owner.retrieve(
            actor(),
            "binding",
            scope=scope(),
            plan=ConceptPlan.model_validate(plan()),
            reauthorize_question=lambda: None,
        )


@pytest.mark.parametrize("change", ["permissions", "role", "policy", "snapshot"])
def test_current_identity_and_source_scope_not_actor_claims_are_authority(monkeypatch, change):
    owner = object.__new__(KakaoConceptKnowledgeReader)
    owner.retrieval = Mock(spec=KnowledgeRetrievalApplicationService)
    allowed = policy()
    if change == "policy":
        allowed.allowed_source_classes = ("PAST_EXAM",)
    owner.retrieval.resolve_access_policy.return_value = allowed
    owner.retrieval.resolve_snapshot_pointer.return_value = snapshot()
    monkeypatch.setattr(module, "authorize_kakao_binding_scope", Mock(return_value=(ACTOR, Mock())))
    permissions = PERMISSIONS | {PermissionKey.KAKAO_ARCHIVE_EDIT}
    if change == "permissions":
        permissions -= {PermissionKey.CONTENT_INTAKE_READ}
    monkeypatch.setattr(module, "effective_permissions", lambda _s, _a: permissions)
    monkeypatch.setattr(
        module,
        "active_role_assignments",
        lambda _s, _a: [
            (None, SimpleNamespace(role_key="VIEWER" if change == "role" else "EDITOR"))
        ],
    )
    session = Mock()
    session.get.return_value = SimpleNamespace(
        snapshot_sha256="sha256:" + "9" * 64 if change == "snapshot" else HASH
    )
    with pytest.raises(KakaoArchiveError):
        owner._authority(session, actor(), "binding", scope())


@pytest.mark.parametrize("material", [False, True])
def test_read_only_retrieval_chooses_exact_source_family_without_publication(material):
    from tests.unit.test_knowledge_retrieval_service import _request

    value = object.__new__(KnowledgeRetrievalApplicationService)
    request = _request()
    value._snapshot_pointer = Mock(return_value=request.graph_snapshot)
    value._policy = Mock(return_value=policy())
    value._authorize = Mock()
    value._request = Mock(return_value=request)
    value._candidates = Mock(return_value=(candidate(materialized()),))
    value._commit_context = Mock()
    value._commit_database = Mock()
    command = Mock(
        graph_snapshot_revision_id=scope().snapshot.graph_snapshot_revision_id,
        access_policy_revision_id=scope().policy.access_policy_revision_id,
        submission_sha256=HASH,
    )
    method = value.retrieve_material_read_only if material else value.retrieve_read_only
    assert len(method(Mock(), command).candidates) == 1
    expected = (
        EvidenceSourceFamily.UPLOADED_MATERIAL_V1
        if material
        else EvidenceSourceFamily.RELEASED_CONSUMER
    )
    assert value._candidates.call_args.kwargs["source_family"] == expected
    assert value._candidates.call_args.kwargs["include_solution_evidence"] is False
    value._commit_context.assert_not_called()
    value._commit_database.assert_not_called()
