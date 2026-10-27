"""Catalog-owned bounded metadata page for a future segmented index.

This is not full-population acceptance or an Artifact read. The caller must
retain the same active root transaction while checking every source/profile
and publishing an index; a page or cursor alone is never a source grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.segmented_embedding_index import MAX_SEGMENTS
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SegmentedLocalIndexingAccessPolicy,
)
from eom_identifiers import content_sha256
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_paging import (
    CandidateSourcePage,
    candidate_source_page_statement,
    validate_candidate_source_page,
)
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)


class SegmentedPopulationReadError(ValueError):
    def __init__(
        self,
        code: Literal[
            "SEGMENTED_POPULATION_READ_CONTEXT_INVALID",
            "SEGMENTED_POPULATION_READ_PAGE_INVALID",
            "SEGMENTED_POPULATION_READ_INCOMPLETE",
            "SEGMENTED_POPULATION_READ_UNAVAILABLE",
        ],
    ) -> None:
        self.code = code
        super().__init__(code)


def read_segmented_candidate_source_page(
    session: Session,
    intent: LocalIndexingSourceReadIntent,
    *,
    authority: CatalogLocalIndexingSourceAuthority,
    after_source_revision_id: str | None = None,
) -> tuple[SegmentedLocalIndexingAccessPolicy, CandidateSourcePage]:
    """O(page) metadata only, with authority before and after one pinned read."""
    root = session.get_transaction()
    if (
        type(authority) is not CatalogLocalIndexingSourceAuthority
        or type(intent) is not LocalIndexingSourceReadIntent
        or root is None
        or not root.is_active
        or session.get_nested_transaction() is not None
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
    try:
        statement = candidate_source_page_statement(
            intent, after_source_revision_id=after_source_revision_id
        )
        policy = authority.authorize_segmented_scope(session, intent)
        rows = tuple((source, run) for source, run in session.execute(statement).all())
        page = validate_candidate_source_page(
            rows,
            maximum=intent.maximum_candidates,
            after_source_revision_id=after_source_revision_id,
        )
        if session.get_transaction() is not root or not root.is_active:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
        if authority.authorize_segmented_scope(session, intent) != policy:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_UNAVAILABLE")
        return policy, page
    except SegmentedPopulationReadError:
        raise
    except LocalIndexingSourceError:
        raise
    except ValueError:
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_PAGE_INVALID") from None
    except SQLAlchemyError:
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_UNAVAILABLE") from None


@dataclass(frozen=True, slots=True)
class SegmentedSourceSelection:
    """Small derived summary, not a grant, Artifact pointer or binding set."""

    graph_snapshot_revision_id: str
    policy_revision_id: str
    source_count: int
    segments: tuple[CandidateSourcePageDescriptor, ...]
    selection_sha256: str


@dataclass(frozen=True, slots=True)
class CandidateSourcePageDescriptor:
    first_source_revision_id: str
    last_source_revision_id: str
    source_count: int
    source_analysis_sha256: str


def scan_segmented_candidate_sources(
    session: Session,
    intent: LocalIndexingSourceReadIntent,
    *,
    authority: CatalogLocalIndexingSourceAuthority,
) -> SegmentedSourceSelection:
    """O(N) scan in one root; retain O(segments) hashes, never all source rows.

    The output only establishes exact admitted source/analysis membership. It
    cannot publish an index until every source, profile and input text is
    independently resolved through the normal Catalog/Artifact owners.
    """
    root = session.get_transaction()
    if root is None or not root.is_active or intent.analysis_run_ids or intent.source_revision_ids:
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
    try:
        isolation = session.connection().get_isolation_level()
    except SQLAlchemyError:
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_UNAVAILABLE") from None
    if isolation not in {"REPEATABLE READ", "SERIALIZABLE"}:
        # READ COMMITTED takes a new snapshot for every page; a concurrent
        # insertion could otherwise be skipped by the source-first cursor.
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
    descriptors: list[CandidateSourcePageDescriptor] = []
    selected_policy: SegmentedLocalIndexingAccessPolicy | None = None
    cursor: str | None = None
    source_count = 0
    while True:
        policy, page = read_segmented_candidate_source_page(
            session,
            intent,
            authority=authority,
            after_source_revision_id=cursor,
        )
        if selected_policy is None:
            selected_policy = policy
        if policy != selected_policy:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_UNAVAILABLE")
        if not page.members or len(descriptors) >= MAX_SEGMENTS:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_INCOMPLETE")
        source_count += len(page.members)
        if source_count > policy.maximum_population_sources:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_INCOMPLETE")
        descriptors.append(
            CandidateSourcePageDescriptor(
                first_source_revision_id=page.members[0][0],
                last_source_revision_id=page.members[-1][0],
                source_count=len(page.members),
                source_analysis_sha256=content_sha256(
                    [
                        {"source_revision_id": source, "analysis_run_id": run}
                        for source, run in page.members
                    ]
                ),
            )
        )
        if page.complete:
            break
        cursor = page.next_after_source_revision_id
        if cursor is None:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_INCOMPLETE")
    if (
        source_count < 1025
        or selected_policy is None
        or session.get_transaction() is not root
        or not root.is_active
    ):
        raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_INCOMPLETE")
    segments = tuple(descriptors)
    selection_sha256 = content_sha256(
        {
            "graph_snapshot_revision_id": intent.graph_snapshot.graph_snapshot_revision_id,
            "policy_revision_id": selected_policy.access_policy_revision_id,
            "segments": [
                {
                    "first_source_revision_id": segment.first_source_revision_id,
                    "last_source_revision_id": segment.last_source_revision_id,
                    "source_count": segment.source_count,
                    "source_analysis_sha256": segment.source_analysis_sha256,
                }
                for segment in segments
            ],
        }
    )
    return SegmentedSourceSelection(
        graph_snapshot_revision_id=intent.graph_snapshot.graph_snapshot_revision_id,
        policy_revision_id=selected_policy.access_policy_revision_id,
        source_count=source_count,
        segments=segments,
        selection_sha256=selection_sha256,
    )
