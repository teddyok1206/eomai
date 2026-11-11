"""New item preparation selects real textbook grounding, without rewriting old evidence."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ContentIntakeKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    CurriculumRetrievalScope,
)
from eom_catalog_service.knowledge_retrieval_service import (
    TEXTBOOK_CONTEXT_HEADER,
    EvidenceSourceFamily,
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    _Candidate,
    _source_matches_item_preparation_target,
)
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session

from tests.unit.test_knowledge_retrieval_service import (
    _item_production_command,
    _member,
    _request,
    _SequenceSession,
)


def _textbook(*, answer: bool = False) -> _Candidate:
    return _Candidate(
        analysis_run_id="analysisrun_" + "1" * 32,
        source=ContentIntakeKnowledgeSourceV2(
            source_class="TEXTBOOK",
            intake_batch_id="intake_" + "7" * 32,
            source_file_id="sourcefile_" + "8" * 32,
            artifact_member=_member("8", media_type="text/markdown", schema_ref=None),
        ),
        node_ids=("knode_book",),
        anchor_ids=("anchor_book",),
        node_labels=("교과서 개념",),
        node_types=("CONCEPT",),
        relevance_milli=850,
        answer_bearing=answer,
        textbook_context="승인된 교과서 분석: 단위 시간에 일어난 속도 변화가 가속도이다.",
    )


def _item() -> _Candidate:
    return _Candidate(
        analysis_run_id="analysisrun_" + "2" * 32,
        source=ApprovedItemKnowledgeSourceV2(
            source_class="PAST_EXAM",
            item_id="item_" + "9" * 32,
            item_revision_id="itemrev_" + "a" * 32,
            artifact_member=_member(
                "a", media_type="application/json", schema_ref="eom.assessment.item-content/1.0"
            ),
        ),
        node_ids=("knode_exam",),
        anchor_ids=("anchor_exam",),
        node_labels=("기출 문항",),
        node_types=("ASSESSMENT_PATTERN",),
        relevance_milli=950,
        answer_bearing=False,
    )


def _command() -> CreateEvidenceBundleCommand:
    outer = _item_production_command()
    value = {
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "graph_snapshot_revision_id": _request().graph_snapshot.graph_snapshot_revision_id,
        "query_kind": "ITEM_PREPARATION",
        "curriculum_scope": None,
        "topic_keys": list(outer.requirement.topic_keys),
        "target_item_revision_id": None,
        "required_item_elements": list(outer.requirement.required_item_elements),
        "source_classes": list(outer.requirement.source_classes),
        "evidence_budget": outer.evidence_budget.model_dump(mode="json"),
        "access_policy_revision_id": outer.access_policy_revision_id,
        "requester_role": outer.requester_role,
        "requester_permission_keys": list(outer.requester_permission_keys),
        "requested_by": outer.requested_by,
    }
    return CreateEvidenceBundleCommand.model_validate(
        value
        | {"idempotency_key": outer.idempotency_key, "submission_sha256": content_sha256(value)}
    )


@pytest.mark.parametrize(
    "candidates",
    [(), (_item(),), (_textbook(answer=True),), (replace(_textbook(), textbook_context=None),)],
)
def test_requested_source_class_is_not_proof_of_selected_textbook(
    candidates: tuple[_Candidate, ...],
) -> None:
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        KnowledgeRetrievalApplicationService._rank_and_render(
            request=_request(), candidates=candidates, required_grounding_class="TEXTBOOK"
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_REQUIRED"


def test_textbook_reserves_budget_but_final_manifest_keeps_score_order() -> None:
    request = _request()
    entries, _ = KnowledgeRetrievalApplicationService._rank_and_render(
        request=request, candidates=(_item(), _textbook()), required_grounding_class="TEXTBOOK"
    )
    assert [entry.relevance_milli for entry in entries] == [950, 850]
    assert entries[1].use == "GROUNDING"

    tight = request.model_copy(
        update={
            "evidence_budget": request.evidence_budget.model_copy(update={"max_graph_nodes": 1})
        }
    )
    selected, context = KnowledgeRetrievalApplicationService._rank_and_render(
        request=tight, candidates=(_item(), _textbook()), required_grounding_class="TEXTBOOK"
    )
    assert len(selected) == 1 and selected[0].source.source_class == "TEXTBOOK"
    assert "class=TEXTBOOK" in context
    assert "단위 시간에 일어난 속도 변화" in context
    assert context.startswith(f"# EOM Evidence Bundle\n\n{TEXTBOOK_CONTEXT_HEADER}\n")


def test_zero_document_budget_does_not_fall_back_to_past_exam_only() -> None:
    request = _request()
    request = request.model_copy(
        update={"evidence_budget": request.evidence_budget.model_copy(update={"max_documents": 0})}
    )
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        KnowledgeRetrievalApplicationService._rank_and_render(
            request=request, candidates=(_item(), _textbook()), required_grounding_class="TEXTBOOK"
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_REQUIRED"


def test_oversized_first_textbook_does_not_hide_smaller_grounding() -> None:
    request = _request()
    request = request.model_copy(
        update={
            "evidence_budget": request.evidence_budget.model_copy(update={"max_graph_nodes": 1})
        }
    )
    large = replace(_textbook(), node_ids=("knode_large_a", "knode_large_b"), relevance_milli=900)
    entries, _ = KnowledgeRetrievalApplicationService._rank_and_render(
        request=request,
        candidates=(_item(), large, _textbook()),
        required_grounding_class="TEXTBOOK",
    )
    assert len(entries) == 1 and entries[0].graph_node_ids == ("knode_book",)


def test_one_reserved_textbook_does_not_starve_higher_ranked_item() -> None:
    request = _request()
    request = request.model_copy(
        update={
            "evidence_budget": request.evidence_budget.model_copy(update={"max_graph_nodes": 2})
        }
    )
    textbook = _textbook()
    other_source = textbook.source.model_copy(update={"source_file_id": "sourcefile_" + "b" * 32})
    other = replace(textbook, source=other_source, node_ids=("knode_other",), relevance_milli=800)
    entries, _ = KnowledgeRetrievalApplicationService._rank_and_render(
        request=request,
        candidates=(_item(), textbook, other),
        required_grounding_class="TEXTBOOK",
    )
    assert [entry.source.source_class for entry in entries] == ["PAST_EXAM", "TEXTBOOK"]


def test_generic_historical_retrieval_does_not_acquire_new_item_policy() -> None:
    entries, _ = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request(), candidates=(_item(),)
    )
    assert len(entries) == 1 and entries[0].source.source_class == "PAST_EXAM"


def test_exact_variation_admits_only_selected_item_and_scoped_textbooks() -> None:
    source = _item().source
    assert isinstance(source, ApprovedItemKnowledgeSourceV2)
    command = _command().model_copy(
        update={
            "target_item_revision_id": source.item_revision_id,
            "source_classes": ("PAST_EXAM", "TEXTBOOK"),
            "curriculum_scope": CurriculumRetrievalScope(
                framework_revision_id="curriculumrev_" + "1" * 32,
                root_unit_id="currunit_" + "2" * 32,
                include_descendants=True,
            ),
        }
    )
    assert _source_matches_item_preparation_target(command, source)
    assert _source_matches_item_preparation_target(command, _textbook().source)
    other = source.model_copy(update={"item_revision_id": "itemrev_" + "b" * 32})
    assert not _source_matches_item_preparation_target(command, other)
    external = source.model_copy(update={"source_class": "APPROVED_ITEM"})
    assert not _source_matches_item_preparation_target(command, external)
    assert not _source_matches_item_preparation_target(
        command.model_copy(update={"curriculum_scope": None}), _textbook().source
    )
    assert not _source_matches_item_preparation_target(
        command.model_copy(update={"source_classes": ("PAST_EXAM",)}), _textbook().source
    )


def test_current_preparation_materializes_bounded_books_before_budgeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    reader = Mock()
    cast(Any, service).textbook_analyses = reader
    books = tuple(
        replace(_textbook(), analysis_run_id="analysisrun_" + digit * 32)
        for digit in ("1", "2", "3", "4")
    )
    session = Mock(spec=Session)
    materialize = Mock(
        return_value={book.analysis_run_id: "approved analysis text" for book in books[:3]}
    )
    monkeypatch.setattr(
        "eom_catalog_service.knowledge_retrieval_service.materialize_item_textbook_context",
        materialize,
    )
    candidates = (_item(), *books)
    request = _request()
    request = request.model_copy(
        update={"evidence_budget": request.evidence_budget.model_copy(update={"max_documents": 3})}
    )
    enriched = service._with_textbook_context(session, request, candidates)
    assert enriched[0] is candidates[0]
    assert len(enriched) == 4
    assert all(book.textbook_context == "approved analysis text" for book in enriched[1:])
    materialize.assert_called_once()
    call = materialize.call_args
    assert call.args == (session,)
    assert call.kwargs["analyses"] is reader
    assert call.kwargs["graph_snapshot_revision_id"] == (
        _request().graph_snapshot.graph_snapshot_revision_id
    )
    assert [selected.analysis_run_id for selected in call.kwargs["selections"]] == [
        book.analysis_run_id for book in books[:3]
    ]


@pytest.mark.parametrize("exists", [True, False])
def test_published_membership_uses_exact_revision_grounding_and_index(exists: bool) -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = "evidenceitem_" + "1" * 32 if exists else None
    revision = "evidencerev_" + "2" * 32
    if exists:
        KnowledgeRetrievalApplicationService._require_published_textbook(session, revision)
    else:
        with pytest.raises(KnowledgeRetrievalServiceError) as caught:
            KnowledgeRetrievalApplicationService._require_published_textbook(session, revision)
        assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_REQUIRED"
    statement = session.scalar.call_args.args[0]
    sql = str(statement)
    parameters = statement.compile().params
    assert revision in parameters.values()
    assert "evidence_bundle_revision_id =" in sql
    assert "source_class =" in sql and "evidence_use =" in sql
    assert "answer_bearing IS false" in sql and "LIMIT" in sql
    session.scalar.assert_called_once()


def test_missing_textbook_fails_before_any_artifact_commit() -> None:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    cast(Any, service)._existing = Mock(return_value=None)
    cast(Any, service).sessions = lambda: _SequenceSession([])
    cast(Any, service)._snapshot_pointer = Mock(return_value=_request().graph_snapshot)
    cast(Any, service)._policy = Mock(return_value=SimpleNamespace())
    cast(Any, service)._authorize = Mock()
    cast(Any, service)._request = Mock(return_value=_request())
    cast(Any, service)._candidates = Mock(return_value=(_item(),))
    commit = Mock(side_effect=AssertionError("must not commit incomplete grounding"))
    cast(Any, service)._commit_context = commit
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        service._create(
            _command(),
            include_solution_evidence=False,
            require_solution_evidence=False,
            source_family=EvidenceSourceFamily.RELEASED_CONSUMER,
            required_grounding_class="TEXTBOOK",
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_REQUIRED"
    commit.assert_not_called()


def test_existing_preparation_cannot_bypass_current_textbook_selection() -> None:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    publication = SimpleNamespace(evidence_bundle_revision_id="evidencerev_" + "3" * 32)
    cast(Any, service)._existing = Mock(return_value=publication)
    cast(Any, service).sessions = lambda: _SequenceSession([None])
    cast(Any, service)._commit_context = Mock(side_effect=AssertionError("replay never writes"))
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        service._create(
            _command(),
            include_solution_evidence=False,
            require_solution_evidence=False,
            source_family=EvidenceSourceFamily.RELEASED_CONSUMER,
            required_grounding_class="TEXTBOOK",
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_REQUIRED"


@pytest.mark.parametrize("current", [False, True])
def test_prepared_context_requires_pinned_analysis_materialization(current: bool) -> None:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    artifact_reader = Mock()
    cast(Any, service).artifacts = artifact_reader
    pointer = _member("8", media_type="text/markdown", schema_ref=None)
    publication = cast(Any, SimpleNamespace(context_artifact=pointer))
    artifact_reader.read_member.return_value = (
        f"# EOM Evidence Bundle\n\n{TEXTBOOK_CONTEXT_HEADER}\napproved text".encode()
        if current
        else b"# EOM Evidence Bundle\n\n- nodes=title only"
    )
    if current:
        service._require_textbook_context(publication)
    else:
        with pytest.raises(KnowledgeRetrievalServiceError) as caught:
            service._require_textbook_context(publication)
        assert caught.value.code == "KNOWLEDGE_RETRIEVAL_TEXTBOOK_TEXT_INVALID"
    assert artifact_reader.read_member.call_args.kwargs["sha256"] == pointer.sha256
    assert (
        artifact_reader.read_member.call_args.kwargs["revision_id"] == pointer.artifact_revision_id
    )
