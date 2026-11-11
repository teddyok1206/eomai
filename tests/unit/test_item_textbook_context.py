"""Accepted textbook materialization uses existing owner reads and exact Graph pins."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.item_textbook_context import (
    TEXTBOOK_TEXT_MAX_BYTES,
    ItemTextbookContextError,
    TextbookContextSelection,
    materialize_item_textbook_context,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
    MaterializedAcceptedAnalysis,
)
from sqlalchemy.orm import Session

from tests.unit.test_chat_rag_resolution import RowsSession, materialized, pointer_rows

SNAPSHOT = "graphrev_" + "d" * 32


def _selection(value: MaterializedAcceptedAnalysis) -> TextbookContextSelection:
    return TextbookContextSelection(
        analysis_run_id=value.analysis.analysis_run_id,
        source=value.analysis.source,
        node_ids=("knode_spacetime",),
        anchor_ids=("anchor_page_1",),
    )


def _reader(value: MaterializedAcceptedAnalysis) -> Mock:
    reader = Mock(spec=KnowledgeGraphPublicationService)
    reader.resolve_accepted_analyses.return_value = {value.analysis.analysis_run_id: value}
    return reader


def _render(
    value: MaterializedAcceptedAnalysis, *, selection: TextbookContextSelection | None = None
) -> str:
    association, pointer = pointer_rows(value)
    return materialize_item_textbook_context(
        cast(Session, RowsSession((association,), (pointer,))),
        analyses=_reader(value),
        graph_snapshot_revision_id=SNAPSHOT,
        selections=(selection or _selection(value),),
    )[value.analysis.analysis_run_id]


def test_approved_text_reuses_exact_publisher_read_and_pinned_graph_queries() -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    session = RowsSession((association,), (pointer,))
    reader = _reader(value)
    result = materialize_item_textbook_context(
        cast(Session, session),
        analyses=reader,
        graph_snapshot_revision_id=SNAPSHOT,
        selections=(_selection(value),),
    )
    run_id = value.analysis.analysis_run_id
    reader.resolve_accepted_analyses.assert_called_once_with(session, (run_id,))
    assert len(session.statements) == 2
    for statement in session.statements:
        assert SNAPSHOT in str(statement.compile(compile_kwargs={"literal_binds": True}))
    text = result[run_id]
    assert "교과서 원문 인용이 아닙니다" in text
    body = json.loads(text.splitlines()[-1])
    assert body["approved_analysis_text"] == value.analysis.proposal.normalized_markdown
    assert body["accepted_result"] == value.analysis.accepted_result.model_dump(mode="json")
    assert body["normalized_markdown"] == value.markdown_member.model_dump(mode="json")
    assert body["source"]["document_revision_id"] == value.analysis.source.document_revision_id
    assert body["truncated"] is False


def test_shared_analysis_is_materialized_once_and_rendered_once() -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    session = RowsSession((association,), (pointer,))
    reader = _reader(value)
    result = materialize_item_textbook_context(
        cast(Session, session),
        analyses=reader,
        graph_snapshot_revision_id=SNAPSHOT,
        selections=(_selection(value), _selection(value)),
    )
    assert len(result) == 1
    reader.resolve_accepted_analyses.assert_called_once_with(
        session, (value.analysis.analysis_run_id,)
    )


@pytest.mark.parametrize(
    "field",
    (
        "source_kind",
        "source_revision_id",
        "source_artifact_id",
        "source_artifact_revision_id",
        "source_sha256",
        "accepted_result_artifact_id",
        "accepted_result_artifact_revision_id",
        "accepted_result_sha256",
    ),
)
def test_snapshot_missing_or_changed_identity_fails_closed(field: str) -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    setattr(association, field, "different")
    with pytest.raises(ItemTextbookContextError, match="identity or hash"):
        materialize_item_textbook_context(
            cast(Session, RowsSession((association,), (pointer,))),
            analyses=_reader(value),
            graph_snapshot_revision_id=SNAPSHOT,
            selections=(_selection(value),),
        )


@pytest.mark.parametrize("missing", ("analysis", "association", "node", "anchor"))
def test_missing_analysis_snapshot_node_or_anchor_has_no_substitution(missing: str) -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    reader = _reader(value)
    selection = _selection(value)
    if missing == "analysis":
        reader.resolve_accepted_analyses.return_value = {}
    if missing == "anchor":
        selection = replace(selection, anchor_ids=("anchor_absent",))
    session = RowsSession(
        () if missing == "association" else (association,),
        () if missing == "node" else (pointer,),
    )
    with pytest.raises(ItemTextbookContextError):
        materialize_item_textbook_context(
            cast(Session, session),
            analyses=reader,
            graph_snapshot_revision_id=SNAPSHOT,
            selections=(selection,),
        )


@pytest.mark.parametrize(
    "field",
    (
        "source_class",
        "source_revision_id",
        "source_artifact_id",
        "source_sha256",
        "artifact_revision_id",
        "member_path",
        "excerpt_sha256",
    ),
)
def test_graph_anchor_pointer_hashes_and_source_are_checked(field: str) -> None:
    value = materialized()
    association, pointer = pointer_rows(value)
    setattr(pointer, field, "different")
    with pytest.raises(ItemTextbookContextError, match="anchor identity or hash"):
        materialize_item_textbook_context(
            cast(Session, RowsSession((association,), (pointer,))),
            analyses=_reader(value),
            graph_snapshot_revision_id=SNAPSHOT,
            selections=(_selection(value),),
        )


def test_publisher_pointer_failure_is_not_downgraded_to_node_labels() -> None:
    value = materialized()
    reader = _reader(value)
    reader.resolve_accepted_analyses.side_effect = KnowledgeGraphPublicationError(
        "KNOWLEDGE_GRAPH_ANALYSIS_INELIGIBLE", "missing accepted source"
    )
    with pytest.raises(KnowledgeGraphPublicationError):
        materialize_item_textbook_context(
            cast(Session, RowsSession()),
            analyses=reader,
            graph_snapshot_revision_id=SNAPSHOT,
            selections=(_selection(value),),
        )


def test_utf8_excerpt_bound_truncation_and_data_encoding_are_explicit() -> None:
    value = materialized()
    source_text = "교과서\\n본문🙂\n" * 1000
    value = replace(
        value,
        analysis=replace(
            value.analysis,
            proposal=value.analysis.proposal.model_copy(
                update={"normalized_markdown": source_text}
            ),
        ),
    )
    body = json.loads(_render(value).splitlines()[-1])
    excerpt = body["approved_analysis_text"]
    assert source_text.startswith(excerpt)
    assert "�" not in excerpt
    assert body["truncated"] is True
    assert body["original_utf8_bytes"] == len(source_text.encode("utf-8"))
    assert body["excerpt_utf8_bytes"] == len(excerpt.encode("utf-8")) <= TEXTBOOK_TEXT_MAX_BYTES


@pytest.mark.parametrize("text", ("", " \n\t", "\ud800"))
def test_empty_or_invalid_analysis_text_fails(text: str) -> None:
    value = materialized()
    value = replace(
        value,
        analysis=replace(
            value.analysis,
            proposal=value.analysis.proposal.model_copy(update={"normalized_markdown": text}),
        ),
    )
    with pytest.raises(ItemTextbookContextError):
        _render(value)


def test_selection_limit_and_non_textbook_fail_before_owner_read() -> None:
    value = materialized()
    reader = _reader(value)
    selection = _selection(value)
    for selections in (
        (selection,) * 4,
        (
            replace(
                selection, source=selection.source.model_copy(update={"source_class": "CURRICULUM"})
            ),
        ),
    ):
        with pytest.raises(ItemTextbookContextError):
            materialize_item_textbook_context(
                cast(Session, RowsSession()),
                analyses=reader,
                graph_snapshot_revision_id=SNAPSHOT,
                selections=selections,
            )
    reader.resolve_accepted_analyses.assert_not_called()
