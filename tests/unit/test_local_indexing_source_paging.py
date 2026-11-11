"""The future source-first page is bounded; it is not a service grant."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_service.local_indexing_source_paging import (
    candidate_source_page_statement,
    read_candidate_source_pages,
    validate_candidate_source_page,
)
from sqlalchemy.dialects import postgresql

from tests.unit.test_local_indexing_policy_contracts import policy_document
from tests.unit.test_local_indexing_source_authority import intent


def _source(number: int) -> str:
    return f"itemrev_{number:032x}"


def _run(number: int) -> str:
    return f"analysisrun_{number:032x}"


def test_page_reuses_eligibility_before_source_first_limit() -> None:
    scope = replace(
        intent(LocalIndexingAccessPolicy.model_validate(policy_document())),
        maximum_candidates=8,
    )
    sql = str(
        candidate_source_page_statement(scope, after_source_revision_id=_source(17)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "knowledge_analysis_runs.state = 'ACCEPTED'" in sql
    assert "items.lifecycle_state = 'ACTIVE'" in sql
    assert "eligible_pointer_analyses AS MATERIALIZED" in sql
    assert "SELECT DISTINCT knowledge_node_source_pointers.analysis_run_id" in sql
    assert "knowledge_snapshot_analyses.source_revision_id > '" + _source(17) + "'" in sql
    assert (
        "ORDER BY knowledge_snapshot_analyses.source_revision_id, "
        "knowledge_snapshot_analyses.analysis_run_id"
    ) in sql
    assert "LIMIT 9" in sql
    assert "ORDER BY knowledge_snapshot_analyses.analysis_run_id LIMIT" not in sql


def test_page_of_1024_keeps_one_extra_row_for_edge_validation() -> None:
    rows = tuple((_source(number), _run(number)) for number in range(1, 1026))
    first = validate_candidate_source_page(rows[:1025], maximum=1024)
    assert len(first.members) == 1024
    assert first.next_after_source_revision_id == _source(1024)
    assert not first.complete
    second = validate_candidate_source_page(
        rows[1024:], maximum=1024, after_source_revision_id=first.next_after_source_revision_id
    )
    assert second.members == ((_source(1025), _run(1025)),)
    assert second.complete and second.next_after_source_revision_id is None


@pytest.mark.parametrize("source_count", (1025, 2048, 10000))
def test_many_source_pages_preserve_exact_order_without_overlap(source_count: int) -> None:
    rows = tuple((_source(number), _run(number)) for number in range(1, source_count + 1))
    emitted: list[tuple[str, str]] = []
    cursor: str | None = None
    offset = 0
    while True:
        page = validate_candidate_source_page(
            rows[offset : offset + 1025],
            maximum=1024,
            after_source_revision_id=cursor,
        )
        emitted.extend(page.members)
        if page.complete:
            assert page.next_after_source_revision_id is None
            break
        assert page.next_after_source_revision_id == page.members[-1][0]
        cursor = page.next_after_source_revision_id
        offset += len(page.members)
    assert tuple(emitted) == rows


def test_duplicate_at_page_edge_is_rejected_before_cursor_advances() -> None:
    rows = tuple((_source(number), _run(number)) for number in range(1, 1025))
    with pytest.raises(ValueError, match="ambiguous"):
        validate_candidate_source_page((*rows, (_source(1024), _run(1025))), maximum=1024)


@pytest.mark.parametrize(
    "rows",
    [
        ((_source(2), _run(1)), (_source(1), _run(2))),
        ((_source(1), _run(1)), (_source(1), _run(2))),
        ((_source(1), _run(1)), (_source(2), "not-an-analysis")),
    ],
)
def test_invalid_order_duplicate_or_identity_is_rejected(
    rows: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError, match="unordered or ambiguous"):
        validate_candidate_source_page(rows, maximum=8)


def test_cursor_and_page_bounds_fail_closed() -> None:
    scope = intent(LocalIndexingAccessPolicy.model_validate(policy_document()))
    with pytest.raises(ValueError, match="cursor"):
        candidate_source_page_statement(scope, after_source_revision_id="latest")
    with pytest.raises(ValueError, match="cursor"):
        validate_candidate_source_page((), maximum=8, after_source_revision_id="latest")
    with pytest.raises(ValueError, match="bound"):
        validate_candidate_source_page(((_source(1), _run(1)),) * 10, maximum=8)


@pytest.mark.parametrize("count", (0, 1, 255, 256, 257, 512, 1556, 16384))
def test_population_reads_ids_once_but_keeps_identical_bounded_pages(count):
    scope = replace(
        intent(LocalIndexingAccessPolicy.model_validate(policy_document())), maximum_candidates=256
    )
    rows = tuple((_source(number), _run(number)) for number in range(1, count + 1))
    execute = Mock(return_value=rows)
    pages = read_candidate_source_pages(
        SimpleNamespace(execute=execute), scope, maximum_sources=16384
    )
    expected = []
    after = None
    while True:
        remaining = tuple(row for row in rows if after is None or row[0] > after)
        page = validate_candidate_source_page(
            remaining[:257], maximum=256, after_source_revision_id=after
        )
        expected.append(page)
        if page.complete:
            break
        after = page.next_after_source_revision_id
    assert pages == tuple(expected)
    assert tuple(row for page in pages for row in page.members) == rows
    execute.assert_called_once()
    sql = str(
        execute.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "LIMIT 16385" in sql
    assert "eligible_pointer_analyses AS MATERIALIZED" in sql


@pytest.mark.parametrize("maximum", (0, -1, True, 16385))
def test_population_invalid_bound_never_reads(maximum):
    scope = intent(LocalIndexingAccessPolicy.model_validate(policy_document()))
    execute = Mock()
    with pytest.raises(ValueError, match="BOUND_INVALID"):
        read_candidate_source_pages(
            SimpleNamespace(execute=execute), scope, maximum_sources=maximum
        )
    execute.assert_not_called()


@pytest.mark.parametrize("fault", ("overflow", "duplicate_edge", "unordered", "invalid_run"))
def test_population_rejects_bad_membership_without_partial_pages(fault):
    scope = replace(
        intent(LocalIndexingAccessPolicy.model_validate(policy_document())), maximum_candidates=256
    )
    rows = [(_source(number), _run(number)) for number in range(1, 513)]
    if fault == "overflow":
        rows.append((_source(513), _run(513)))
    elif fault == "duplicate_edge":
        rows[256] = rows[255]
    elif fault == "unordered":
        rows[1], rows[2] = rows[2], rows[1]
    else:
        rows[-1] = (rows[-1][0], "not-an-analysis")
    with pytest.raises(ValueError):
        read_candidate_source_pages(
            SimpleNamespace(execute=Mock(return_value=rows)), scope, maximum_sources=512
        )
