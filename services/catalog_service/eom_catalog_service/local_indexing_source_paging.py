"""Source-first metadata pages for a future segmented indexing publication.

This module does not authorize a read or extend the released 1,024-source policy.
The Catalog application must fence the actual service, pin one Graph/policy and
validate the complete population before using pages to publish an index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from sqlalchemy import Select
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import KnowledgeSnapshotAnalysisRecord
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    ReadOnlyCandidatePoolScope,
)
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent


@dataclass(frozen=True, slots=True)
class CandidateSourcePage:
    """One validated page; source identities are unique, ordered and bounded."""

    members: tuple[tuple[str, str], ...]
    next_after_source_revision_id: str | None
    complete: bool


def candidate_source_page_statement(
    intent: LocalIndexingSourceReadIntent | ReadOnlyCandidatePoolScope,
    *,
    after_source_revision_id: str | None = None,
) -> Select[tuple[str, str]]:
    """Reuse the official pre-limit eligibility, then page by immutable source.

    The extra row is required: it detects a duplicate source at the page edge
    before a caller could advance the cursor and silently omit that duplicate.
    This pure SQL builder is not a service authorization or a population read.
    """
    if after_source_revision_id is not None and (
        type(after_source_revision_id) is not str
        or re.fullmatch(r"itemrev_[0-9a-f]{32}", after_source_revision_id) is None
    ):
        raise ValueError("source page cursor is invalid")
    association = KnowledgeSnapshotAnalysisRecord
    statement = (
        KnowledgeRetrievalApplicationService.candidate_pool_analysis_statement(
            intent, allow_answer_bearing=True
        )
        .order_by(None)
        .limit(None)
        .with_only_columns(
            association.source_revision_id,
            association.analysis_run_id,
            maintain_column_froms=True,
        )
    )
    if after_source_revision_id is not None:
        statement = statement.where(association.source_revision_id > after_source_revision_id)
    return statement.order_by(association.source_revision_id, association.analysis_run_id).limit(
        intent.maximum_candidates + 1
    )


def validate_candidate_source_page(
    rows: tuple[tuple[str, str], ...],
    *,
    maximum: int,
    after_source_revision_id: str | None = None,
) -> CandidateSourcePage:
    """Fail closed on missing order, duplicate sources or an overfull SQL result."""
    if (
        type(rows) is not tuple
        or type(maximum) is not int
        or not 1 <= maximum <= 1024
        or len(rows) > maximum + 1
    ):
        raise ValueError("source page bound is invalid")
    if after_source_revision_id is not None and (
        type(after_source_revision_id) is not str
        or re.fullmatch(r"itemrev_[0-9a-f]{32}", after_source_revision_id) is None
    ):
        raise ValueError("source page cursor is invalid")
    prior = after_source_revision_id
    for row in rows:
        if (
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or re.fullmatch(r"itemrev_[0-9a-f]{32}", row[0]) is None
            or type(row[1]) is not str
            or re.fullmatch(r"analysisrun_[0-9a-f]{32}", row[1]) is None
            or (prior is not None and row[0] <= prior)
        ):
            raise ValueError("source page is unordered or ambiguous")
        prior = row[0]
    selected = rows[:maximum]
    return CandidateSourcePage(
        members=selected,
        next_after_source_revision_id=(selected[-1][0] if len(rows) > maximum else None),
        complete=len(rows) <= maximum,
    )


def read_candidate_source_pages(
    session: Session,
    intent: LocalIndexingSourceReadIntent | ReadOnlyCandidatePoolScope,
    *,
    maximum_sources: int,
) -> tuple[CandidateSourcePage, ...]:
    """Read bounded IDs once, without re-evaluating the whole Graph per page.

    Only source/run identities are materialized. Existing per-page provenance
    budgets and official eligibility stay unchanged; callers must still perform
    a fresh final membership read and authorize the actual operator/service.
    """
    if type(maximum_sources) is not int or not 1 <= maximum_sources <= MAX_PUBLIC_SOLUTION_SOURCES:
        raise ValueError("PUBLIC_SOLUTION_POPULATION_BOUND_INVALID")
    rows = tuple(
        tuple(row)
        for row in session.execute(
            candidate_source_page_statement(intent).limit(maximum_sources + 1)
        )
    )
    if len(rows) > maximum_sources:
        raise ValueError("PUBLIC_SOLUTION_POPULATION_BOUND_EXCEEDED")
    pages: list[CandidateSourcePage] = []
    after = None
    for start in range(0, max(1, len(rows)), intent.maximum_candidates):
        page = validate_candidate_source_page(
            rows[start : start + intent.maximum_candidates + 1],
            maximum=intent.maximum_candidates,
            after_source_revision_id=after,
        )
        pages.append(page)
        after = page.next_after_source_revision_id
    return tuple(pages)
