"""Offline Catalog RAG read/authority/pointer tests; no DB or model invocation."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock

import eom_catalog_service.chat_rag_resolution as rag_module
import pytest
from eom_catalog_contracts import (
    EducationalDocumentKnowledgeSourceV3,
    EducationRetrievalAccessPolicy,
    EvidenceBudget,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeArtifactMemberPointer,
)
from eom_catalog_service.chat_rag_resolution import (
    ANALYSIS_LIMITATION,
    TEXT_LIMITATION,
    ChatRagResolutionError,
    ChatRagResolutionService,
    analysis_excerpt,
    source_reference,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
    MaterializedAcceptedAnalysis,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalCandidate,
    KnowledgeRetrievalServiceError,
)
from eom_operator_identity import PermissionKey
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagCatalogRequest,
    ChatRagSource,
    chat_rag_context,
)
from sqlalchemy.orm import Session

from tests.unit.general_chat_rag_fixtures import HASH, scope
from tests.unit.test_knowledge_analysis_document_contracts import (
    document_source,
    proposal_v3,
    request_v3,
)

ACTOR = "operator_" + "f" * 32
BUDGET = EvidenceBudget(
    max_documents=3,
    max_item_revisions=3,
    max_graph_nodes=32,
    max_claims=32,
    max_context_tokens=4000,
)
PERMISSIONS = frozenset(
    {
        PermissionKey.GENERAL_CHAT_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
        PermissionKey.ITEM_READ,
    }
)


def materialized(number: int = 1) -> MaterializedAcceptedAnalysis:
    original = document_source()
    original.update(
        document_id=f"edudoc_{number:032x}", document_revision_id=f"edudocrev_{number:032x}"
    )
    source = EducationalDocumentKnowledgeSourceV3.model_validate(original)
    request = KnowledgeAnalysisRequestV3.model_validate(request_v3())
    proposal_value = proposal_v3(request)
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(proposal_value)
    accepted = KnowledgeArtifactMemberPointer(
        artifact_id=f"artifact_{number + 100:032x}",
        artifact_revision_id=f"rev_{number + 100:032x}",
        member_path="evidence/accepted-result.json",
        schema_ref="eom://schemas/knowledge/knowledge-analysis-result/3.0",
        media_type="application/json",
        sha256=HASH,
        logical_name="accepted-result.json",
    )
    member = ArtifactMemberPointer(
        artifact_id=f"artifact_{number + 200:032x}",
        artifact_revision_id=f"rev_{number + 200:032x}",
        member_path="normalized/document.md",
        schema_ref="eom://schemas/knowledge/normalized-markdown/1.0",
        media_type="text/markdown",
        sha256=HASH,
    )
    return MaterializedAcceptedAnalysis(
        AcceptedAnalysisProposal(
            analysis_run_id=f"analysisrun_{number:032x}",
            source=source,
            accepted_result=accepted,
            proposal=proposal,
        ),
        member,
    )


def candidate(value: MaterializedAcceptedAnalysis) -> KnowledgeRetrievalCandidate:
    analysis = value.analysis
    return KnowledgeRetrievalCandidate(
        analysis_run_id=analysis.analysis_run_id,
        source=analysis.source,
        node_ids=("knode_spacetime",),
        anchor_ids=("anchor_page_1",),
        node_labels=("시간과 공간",),
        node_types=("CONCEPT",),
        relevance_milli=1000,
        answer_bearing=False,
    )


def pointer_rows(value: MaterializedAcceptedAnalysis) -> tuple[SimpleNamespace, SimpleNamespace]:
    analysis = value.analysis
    original = analysis.source.artifact_member
    association = SimpleNamespace(
        analysis_run_id=analysis.analysis_run_id,
        source_kind=analysis.source.source_kind,
        source_revision_id=analysis.source.document_revision_id,
        source_artifact_id=original.artifact_id,
        source_artifact_revision_id=original.artifact_revision_id,
        source_sha256=original.sha256,
        accepted_result_artifact_id=analysis.accepted_result.artifact_id,
        accepted_result_artifact_revision_id=analysis.accepted_result.artifact_revision_id,
        accepted_result_sha256=analysis.accepted_result.sha256,
    )
    anchor = analysis.proposal.anchors[0]
    pointer = SimpleNamespace(
        analysis_run_id=analysis.analysis_run_id,
        node_id="knode_spacetime",
        anchor_id=anchor.anchor_id,
        artifact_revision_id=anchor.artifact_revision_id,
        member_path=anchor.member_path,
        excerpt_sha256=anchor.excerpt_sha256,
        source_class="TEXTBOOK",
        source_revision_id=analysis.source.document_revision_id,
        source_artifact_id=original.artifact_id,
        source_sha256=original.sha256,
    )
    return association, pointer


class RowsSession:
    def __init__(self, *rows: tuple[Any, ...]) -> None:
        self.rows = deque(rows)
        self.statements: list[Any] = []

    def scalars(self, statement: Any) -> tuple[Any, ...]:
        self.statements.append(statement)
        return self.rows.popleft()


def service() -> ChatRagResolutionService:
    value = object.__new__(ChatRagResolutionService)
    value.retrieval = Mock(spec=KnowledgeRetrievalApplicationService)
    value.retrieval.artifacts = Mock()
    value.analyses = Mock(spec=KnowledgeGraphPublicationService)
    return value


def policy() -> EducationRetrievalAccessPolicy:
    return cast(
        EducationRetrievalAccessPolicy,
        SimpleNamespace(
            allowed_requester_roles=("ADMIN", "EDITOR", "REVIEWER"),
            allowed_query_kinds=("ITEM_PREPARATION",),
            allowed_source_classes=("TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM"),
            answer_bearing_roles=("ADMIN",),
            maximum_budget=BUDGET,
        ),
    )


def test_source_projection_retains_identity_without_staging_or_batch_keys() -> None:
    ref = source_reference(materialized().analysis.source)
    assert ref.document_revision_id == "edudocrev_" + f"{1:032x}"
    assert ref.first_physical_page == 1 and ref.last_physical_page == 2
    document = ref.model_dump(mode="json")
    assert "materialized_path" not in str(document)
    assert "intake_batch_id" not in str(document)


def test_utf8_excerpt_is_deterministic_and_bounded() -> None:
    text = "문맥과 검증 " * 1000
    assert analysis_excerpt(text).encode().decode() == analysis_excerpt(text)
    assert len(analysis_excerpt(text).encode()) <= 2500
    assert analysis_excerpt("  가  ") == "가"
    small = policy()
    small.maximum_budget = BUDGET.model_copy(update={"max_context_tokens": 1000})
    limit = ChatRagResolutionService._source_text_budget(small)
    assert len(analysis_excerpt(text, max_bytes=limit).encode()) * 3 <= 2000


def test_candidate_selection_is_ordered_unique_and_bounded() -> None:
    values = tuple(materialized(i) for i in range(1, 6))
    candidates = tuple(candidate(v) for v in values)
    assert (
        ChatRagResolutionService._bounded_candidates((candidates[0], *candidates), None, BUDGET)
        == candidates[:3]
    )
    assert (
        ChatRagResolutionService._bounded_candidates(
            candidates, None, BUDGET.model_copy(update={"max_documents": 1})
        )
        == candidates[:1]
    )
    changed = replace(candidates[0], node_ids=tuple(f"n{i}" for i in range(33)))
    assert ChatRagResolutionService._bounded_candidates((changed,), None, BUDGET) == ()
    duplicate_source = replace(candidates[1], source=candidates[0].source)
    assert (
        ChatRagResolutionService._bounded_candidates(
            (candidates[0], duplicate_source), None, BUDGET
        )
        == candidates[:1]
    )


def test_term_adaptation_uses_index_keys_source_scope_and_stable_top_k() -> None:
    session = RowsSession(("science.z", "science.a", "한글-key", "a" * 129))
    assert KnowledgeRetrievalApplicationService.topic_keys_for_terms(
        cast(Session, session),
        snapshot_id=scope().snapshot.graph_snapshot_revision_id,
        terms=("운동량",),
        source_classes=("TEXTBOOK",),
        allow_answer_bearing=False,
    ) == ("science.a", "science.z")
    statement = str(session.statements[0])
    assert "knowledge_node_terms" in statement and "source_class IN" in statement
    assert "knowledge_nodes.answer_bearing IS false" in statement
    assert "LIKE" not in statement and "ILIKE" not in statement
    assert session.statements[0].compile().params["param_1"] == 20


def test_three_reference_resolutions_use_two_queries_not_n_plus_one() -> None:
    values = tuple(materialized(i) for i in range(1, 4))
    rows = tuple(pointer_rows(v) for v in values)
    session = RowsSession(tuple(a for a, _p in rows), tuple(p for _a, p in rows))
    result = ChatRagResolutionService._references(
        cast(Session, session),
        scope(),
        tuple((v, candidate(v).node_ids, candidate(v).anchor_ids) for v in values),
    )
    assert tuple(result) == tuple(v.analysis.analysis_run_id for v in values)
    assert len(session.statements) == 2
    assert all(r.source.source_class == "TEXTBOOK" for r in result.values())


@pytest.mark.parametrize(
    "target,field",
    (
        ("association", "accepted_result_sha256"),
        ("association", "source_sha256"),
        ("association", "source_artifact_id"),
        ("association", "source_revision_id"),
        ("pointer", "excerpt_sha256"),
        ("pointer", "source_sha256"),
        ("pointer", "source_artifact_id"),
        ("pointer", "source_class"),
        ("pointer", "source_revision_id"),
        ("pointer", "member_path"),
        ("pointer", "node_id"),
        ("pointer", "anchor_id"),
    ),
)
def test_reference_rejects_stale_source_graph_hash_and_anchor(target: str, field: str) -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    setattr(association if target == "association" else pointer, field, "wrong")
    session = RowsSession((association,), (pointer,))
    with pytest.raises(ChatRagResolutionError):
        ChatRagResolutionService._references(
            cast(Session, session),
            scope(),
            ((value, candidate(value).node_ids, candidate(value).anchor_ids),),
        )


def test_missing_and_duplicate_association_fail_before_pointer_read() -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    for rows in ((), (association, association)):
        session = RowsSession(rows, (pointer,))
        with pytest.raises(ChatRagResolutionError):
            ChatRagResolutionService._references(
                cast(Session, session),
                scope(),
                ((value, candidate(value).node_ids, candidate(value).anchor_ids),),
            )
        assert len(session.statements) == 1


@pytest.mark.parametrize(
    "change", ("missing", "disabled", "deleted", "password", "permission", "role")
)
def test_actual_actor_is_authorized_before_source_metadata(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service()
    actor = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    if change == "disabled":
        actor.status = "DISABLED"
    if change == "deleted":
        actor.deleted_at = "removed"
    if change == "password":
        actor.must_change_password = True
    session = Mock(spec=Session)
    session.get.return_value = None if change == "missing" else actor
    permissions = (
        PERMISSIONS - {PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE}
        if change == "permission"
        else PERMISSIONS
    )
    monkeypatch.setattr(rag_module, "effective_permissions", lambda _s, _actor: permissions)
    monkeypatch.setattr(
        rag_module,
        "active_role_assignments",
        lambda _s, _actor: [
            (None, SimpleNamespace(role_key="VIEWER" if change == "role" else "ADMIN"))
        ],
    )
    value.retrieval.resolve_access_policy.return_value = policy()
    with pytest.raises(ChatRagResolutionError) as caught:
        value._authority(session, ACTOR, scope().policy)
    assert caught.value.code == "CHAT_KNOWLEDGE_FORBIDDEN"
    value.analyses.resolve_accepted_analyses.assert_not_called()
    value.retrieval.topic_keys_for_terms.assert_not_called()


def test_permission_and_role_are_actual_not_model_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    value = service()
    session = Mock(spec=Session)
    session.get.return_value = SimpleNamespace(
        status="ACTIVE", deleted_at=None, must_change_password=False
    )
    monkeypatch.setattr(
        rag_module,
        "effective_permissions",
        lambda _s, actor: PERMISSIONS if actor == ACTOR else frozenset(),
    )
    monkeypatch.setattr(
        rag_module,
        "active_role_assignments",
        lambda _s, _actor: [(None, SimpleNamespace(role_key="EDITOR"))],
    )
    value.retrieval.resolve_access_policy.return_value = policy()
    _policy, role, permissions = value._authority(session, ACTOR, scope().policy)
    assert role == "EDITOR" and permissions == PERMISSIONS


@pytest.mark.parametrize(
    "source_class,permission",
    (
        ("TEXTBOOK", PermissionKey.CONTENT_INTAKE_READ),
        ("PAST_EXAM", PermissionKey.ITEM_READ),
        ("PAST_EXAM", PermissionKey.CONTENT_INTAKE_READ),
        ("APPROVED_ITEM", PermissionKey.ITEM_READ),
    ),
)
def test_source_specific_permissions_are_required(
    source_class: str, permission: PermissionKey
) -> None:
    with pytest.raises(ChatRagResolutionError):
        ChatRagResolutionService._source_authority(
            (source_class,), PERMISSIONS - {permission}, policy()
        )


def test_followup_rejects_tampered_text_and_removed_limitations() -> None:
    value = service()
    item = materialized()
    association, pointer = pointer_rows(item)
    session = RowsSession((association,), (pointer,))
    reference = value._references(
        cast(Session, session),
        scope(),
        ((item, candidate(item).node_ids, candidate(item).anchor_ids),),
    )[item.analysis.analysis_run_id]
    source = ChatRagSource(
        key="R1",
        reference=reference,
        display_name="합성 교과서",
        location=value._location(reference),
        text="위조 텍스트",
    )
    context = chat_rag_context(
        scope=scope(), sources=(source,), limitations=(ANALYSIS_LIMITATION, TEXT_LIMITATION)
    )
    value.analyses.resolve_accepted_analyses.return_value = {item.analysis.analysis_run_id: item}
    value._titles = Mock(return_value={item.analysis.analysis_run_id: source.display_name})
    with pytest.raises(ChatRagResolutionError):
        value._authorize_context(
            cast(Session, RowsSession((association,), (pointer,))),
            context,
            PERMISSIONS,
            policy(),
            "ADMIN",
        )
    context = chat_rag_context(scope=scope(), sources=(source,), limitations=())
    value.analyses.resolve_accepted_analyses.reset_mock()
    with pytest.raises(ChatRagResolutionError):
        value._authorize_context(cast(Session, Mock()), context, PERMISSIONS, policy(), "ADMIN")
    value.analyses.resolve_accepted_analyses.assert_not_called()


def test_read_only_selection_never_calls_publication_boundary() -> None:
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
    result = value.retrieve_read_only(Mock(spec=Session), command)
    assert len(result.candidates) == 1
    assert value._candidates.call_args.kwargs["include_solution_evidence"] is False
    value._commit_context.assert_not_called()
    value._commit_database.assert_not_called()


@pytest.mark.parametrize("change", (None, "row_hash", "document_hash", "graph_id", "revision"))
def test_snapshot_identity_hash_is_not_the_manifest_file_hash(
    change: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    value = service()
    session = Mock(spec=Session)
    session.get.return_value = SimpleNamespace(snapshot_sha256=scope().snapshot.sha256)
    manifest_hash = "sha256:" + "b" * 64
    member = Mock(
        sha256=manifest_hash,
        schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/9.0",
    )
    graph = Mock(
        manifest_sha256=manifest_hash, manifest_artifact=member, graph_id="graph_" + "1" * 32
    )
    value.retrieval.resolve_snapshot_pointer.return_value = graph
    document = {
        "graph_snapshot_revision_id": scope().snapshot.graph_snapshot_revision_id,
        "graph_id": graph.graph_id,
        "snapshot_sha256": scope().snapshot.sha256,
    }
    if change == "row_hash":
        session.get.return_value.snapshot_sha256 = manifest_hash
    if change == "document_hash":
        document["snapshot_sha256"] = manifest_hash
    if change == "graph_id":
        document["graph_id"] = "graph_" + "2" * 32
    if change == "revision":
        document["graph_snapshot_revision_id"] = "graphrev_" + "2" * 32
    value.retrieval.artifacts.read_member.return_value = json.dumps(document).encode()
    validate = Mock()
    monkeypatch.setattr(rag_module, "validate_contract", validate)
    if change:
        with pytest.raises(ChatRagResolutionError):
            value._scope(session, scope())
    else:
        assert value._scope(session, scope()) is graph
        validate.assert_called_once_with("knowledge-graph-snapshot-manifest-v9", document)
        assert value.retrieval.artifacts.read_member.call_args.kwargs["sha256"] == manifest_hash


def test_actual_read_only_use_case_materializes_text_and_extends_exact_prefix() -> None:
    from eom_protocol.general_chat_rag_knowledge import read_rag_catalog_reply

    value = service()
    first, second = materialized(), materialized(2)
    first_rows, second_rows = pointer_rows(first), pointer_rows(second)
    references = value._references(
        cast(
            Session, RowsSession((first_rows[0], second_rows[0]), (first_rows[1], second_rows[1]))
        ),
        scope(),
        tuple((v, candidate(v).node_ids, candidate(v).anchor_ids) for v in (first, second)),
    )
    value._authority = Mock(return_value=(policy(), "ADMIN", PERMISSIONS))
    value._scope = Mock()
    value._references = Mock(return_value=references)
    value._titles = Mock(
        return_value={v.analysis.analysis_run_id: "합성 교과서" for v in (first, second)}
    )
    value.retrieval.topic_keys_for_terms.return_value = ("science.spacetime",)
    value.retrieval.retrieve_read_only.return_value = SimpleNamespace(
        candidates=(candidate(first),)
    )
    value.analyses.resolve_accepted_analyses.return_value = {first.analysis.analysis_run_id: first}
    request = ChatRagCatalogRequest.model_validate(
        {
            "actor_id": ACTOR,
            "command": {
                "action": "RETRIEVE_CHAT_RAG",
                "scope": scope().model_dump(mode="json"),
                "arguments": {"terms": ["시간"], "source_classes": ["TEXTBOOK"]},
                "prior_context": None,
            },
        }
    )
    reply = value._resolve(Mock(spec=Session), request)
    read_rag_catalog_reply(reply.model_dump(mode="json"), request=request)
    assert reply.context is not None
    assert reply.context.sources[0].text == analysis_excerpt(
        first.analysis.proposal.normalized_markdown
    )
    assert reply.context.sources[0].text_kind == "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
    command = value.retrieval.retrieve_read_only.call_args.args[1]
    assert command.requested_by == ACTOR and command.requester_role == "ADMIN"
    assert command.topic_keys == ("science.spacetime",)
    value._authorize_context = Mock()
    value.retrieval.retrieve_read_only.return_value = SimpleNamespace(
        candidates=(candidate(first), candidate(second))
    )
    value.analyses.resolve_accepted_analyses.return_value = {
        second.analysis.analysis_run_id: second
    }
    request = ChatRagCatalogRequest.model_validate(
        {
            "actor_id": ACTOR,
            "command": {
                **request.command.model_dump(mode="json"),
                "prior_context": reply.context.model_dump(mode="json"),
            },
        }
    )
    extended = value._resolve(Mock(spec=Session), request)
    read_rag_catalog_reply(extended.model_dump(mode="json"), request=request)
    assert extended.context is not None
    assert extended.context.sources[:1] == reply.context.sources
    assert extended.context.sources[1].key == "R2"
    value._authorize_context.assert_called_once()


def test_accepted_materialization_bounds_missing_and_duplicate_runs() -> None:
    value = object.__new__(KnowledgeGraphPublicationService)
    session = Mock(spec=Session)
    assert value.resolve_accepted_analyses(session, ()) == {}
    session.scalars.assert_not_called()
    for ids in (("same", "same"), tuple(f"analysisrun_{i:032x}" for i in range(4))):
        with pytest.raises(KnowledgeGraphPublicationError):
            value.resolve_accepted_analyses(session, ids)
    session.scalars.return_value = ()
    with pytest.raises(KnowledgeGraphPublicationError):
        value.resolve_accepted_analyses(session, ("analysisrun_" + "1" * 32,))


@pytest.mark.parametrize("invalid_member", (False, True))
def test_accepted_materialization_reuses_validator_and_four_batched_queries(
    invalid_member: bool,
) -> None:
    value = object.__new__(KnowledgeGraphPublicationService)
    analyses = tuple(materialized(i) for i in range(1, 4))
    by_run = {a.analysis.analysis_run_id: a for a in analyses}
    runs = tuple(
        SimpleNamespace(
            analysis_run_id=a.analysis.analysis_run_id,
            proposal_artifact_id=a.markdown_member.artifact_id,
            proposal_artifact_revision_id=a.markdown_member.artifact_revision_id,
            accepted_result_artifact_revision_id=a.analysis.accepted_result.artifact_revision_id,
        )
        for a in analyses
    )
    revisions = tuple(
        SimpleNamespace(
            revision_id=a.markdown_member.artifact_revision_id,
            logical_artifact_id=a.markdown_member.artifact_id,
            job_id=f"job_{i:032x}",
            result={"members": {"normalized_markdown": a.markdown_member.model_dump(mode="json")}},
        )
        for i, a in enumerate(analyses)
    )
    if invalid_member:
        revisions[0].result["members"]["normalized_markdown"]["artifact_revision_id"] = (
            "rev_" + "f" * 32
        )
    session = RowsSession(runs, revisions, (), ())
    value._load_accepted_analysis = Mock(
        side_effect=lambda _s, run_id, **_kw: by_run[run_id].analysis
    )
    if invalid_member:
        with pytest.raises(KnowledgeGraphPublicationError):
            value.resolve_accepted_analyses(cast(Session, session), tuple(by_run))
    else:
        assert value.resolve_accepted_analyses(cast(Session, session), tuple(by_run)) == by_run
        assert value._load_accepted_analysis.call_count == 3
    assert len(session.statements) == 4


@pytest.mark.parametrize(
    "error",
    (
        ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN"),
        KnowledgeRetrievalServiceError("KNOWLEDGE_RETRIEVAL_SOURCE_HASH_MISMATCH", "hidden"),
        ValueError("hidden source content"),
    ),
)
def test_failed_resolution_returns_no_partial_evidence(error: Exception) -> None:
    value = service()
    session = MagicMock()
    value.sessions = Mock(return_value=session)
    value._resolve = Mock(side_effect=error)
    request = ChatRagCatalogRequest.model_validate(
        {
            "actor_id": ACTOR,
            "command": {
                "action": "PREPARE_CHAT_RAG",
                "snapshot": None,
                "policy": scope().policy.model_dump(mode="json"),
            },
        }
    )
    reply = value.resolve(request)
    assert reply.status == "FAILED" and reply.scope is None and reply.context is None
    assert "hidden" not in str(reply.model_dump())
    actual = session.__enter__.return_value
    actual.connection.assert_called_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    assert str(actual.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"


@pytest.mark.parametrize("configured", (True, False))
def test_catalog_socket_rag_operation_is_closed_and_read_only(
    configured: bool, tmp_path: Any
) -> None:
    import json
    import socket
    import threading

    from eom_protocol.general_chat_rag_knowledge import ChatRagCatalogReply, read_rag_catalog_reply

    from tests.unit.test_catalog_application_boundary import _server

    server = _server(tmp_path)
    expected = ChatRagCatalogReply(status="SUCCEEDED", scope=scope(), context=None, error_code=None)
    resolver = Mock(spec=ChatRagResolutionService)
    resolver.resolve.return_value = expected
    server.chat_rag = resolver if configured else None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = ChatRagCatalogRequest.model_validate(
        {
            "actor_id": ACTOR,
            "command": {
                "action": "PREPARE_CHAT_RAG",
                "snapshot": scope().snapshot.model_dump(mode="json"),
                "policy": scope().policy.model_dump(mode="json"),
            },
        }
    )
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps(request.model_dump(mode="json")).encode() + b"\n")
            raw = connection.makefile("rb").readline()
        result = read_rag_catalog_reply(json.loads(raw), request=request)
        if configured:
            assert result == expected
            resolver.resolve.assert_called_once_with(request)
        else:
            assert result.status == "FAILED"
            assert result.error_code == "CHAT_KNOWLEDGE_UNAVAILABLE"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
