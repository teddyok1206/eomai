"""One strict public capture per exact DB frame, with fresh relational fences."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import get_ident

from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_population_dependencies import (
    observe_public_solution_index_dependencies,
    observe_public_solution_population_dependencies,
)
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class _PopulationReadSet:
    root: SessionTransaction
    transaction: SessionTransaction
    thread_id: int
    settings: CatalogSettings
    scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent
    recipe: PublicSolutionEmbeddingRecipe | None
    maximum_sources: int
    dependency_sha256: str
    value: CapturedPublicSolutionSources


def capture_public_solution_index_population(
    session: Session,
    intent: LocalIndexingSourceReadIntent,
    *,
    reader: PinnedArtifactReadContext,
    maximum_sources: int,
    capture: Callable[[], CapturedPublicSolutionSources],
    reauthorize: Callable[[], LocalIndexingSourceReadIntent],
) -> CapturedPublicSolutionSources:
    """INDEX keeps its existing exact clean root/savepoint admission."""
    return _capture_population(
        session,
        intent,
        reader=reader,
        maximum_sources=maximum_sources,
        recipe=None,
        capture=capture,
        reauthorize=reauthorize,
        observe=lambda transaction: observe_public_solution_index_dependencies(
            session, intent, maximum_sources, transaction=transaction
        ),
    )


def capture_public_solution_query_population(
    session: Session,
    scope: ReadOnlyCandidatePoolScope,
    recipe: PublicSolutionEmbeddingRecipe,
    *,
    reader: PinnedArtifactReadContext,
    maximum_sources: int,
    capture: Callable[[], CapturedPublicSolutionSources],
    reauthorize: Callable[[], ReadOnlyCandidatePoolScope],
) -> CapturedPublicSolutionSources:
    """Human QUERY reuse is root-only, exact-operator/scope/recipe, never a grant."""
    if not isinstance(scope, ReadOnlyCandidatePoolScope) or session.in_nested_transaction():
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    return _capture_population(
        session,
        scope,
        reader=reader,
        maximum_sources=maximum_sources,
        recipe=recipe,
        capture=capture,
        reauthorize=reauthorize,
        observe=lambda _transaction: observe_public_solution_population_dependencies(
            session, scope, maximum_sources
        ),
    )


def _capture_population(
    session: Session,
    scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
    *,
    recipe: PublicSolutionEmbeddingRecipe | None,
    reader: PinnedArtifactReadContext,
    maximum_sources: int,
    capture: Callable[[], CapturedPublicSolutionSources],
    reauthorize: Callable[[], ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent],
    observe: Callable[[SessionTransaction], str],
) -> CapturedPublicSolutionSources:
    """No cross-frame retention, authority cache, source mutation or numerical work.

    The caller has just authorized the actual operator or INDEX service. Each fence
    observes the complete current source closure and reauthorizes again. Only
    repeated immutable interpretation is avoided, not current provenance checks.
    """
    reader.require_session(session)
    root = session.get_transaction()
    if root is None or not root.is_active:
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    transaction = session.get_nested_transaction() or root
    if not transaction.is_active:
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    if session.new or session.dirty or session.deleted:
        # Unflushed writes must not be concealed by an immutable capture. A clean
        # registration savepoint is supported, but never inherits its parent's set.
        session.info.pop(_PopulationReadSet, None)
        value = capture()
        if value.scope != scope:
            raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
        reader.revalidate_provenance()
        if reauthorize() != scope:
            raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
        return value
    previous = session.info.get(_PopulationReadSet)
    if previous is not None and type(previous) is not _PopulationReadSet:
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    if previous is not None and previous.root is root and previous.thread_id != get_ident():
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    before = observe(transaction)
    reusable = (
        previous is not None
        and previous.root is root
        and previous.transaction is transaction
        and previous.settings == reader.settings
        and previous.scope == scope
        and previous.recipe == recipe
        and previous.maximum_sources == maximum_sources
    )
    if reusable:
        assert previous is not None
        if before != previous.dependency_sha256:
            raise ValueError("PUBLIC_SOLUTION_POPULATION_CHANGED")
        value = previous.value
    else:
        # First capture still checks all original files, schemas, admission and
        # report lineage. Failed/torn captures never populate this read set.
        value = capture()
        if observe(transaction) != before:
            raise ValueError("PUBLIC_SOLUTION_POPULATION_CHANGED")
        if value.scope != scope:
            raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    reader.revalidate_provenance()
    if reauthorize() != scope:
        raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
    if (
        session.get_transaction() is not root
        or not root.is_active
        or not transaction.is_active
        or (session.get_nested_transaction() or root) is not transaction
        or session.new
        or session.dirty
        or session.deleted
    ):
        session.info.pop(_PopulationReadSet, None)
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    if not reusable:
        session.info[_PopulationReadSet] = _PopulationReadSet(
            root,
            transaction,
            get_ident(),
            reader.settings,
            scope,
            recipe,
            maximum_sources,
            before,
            value,
        )
    return value
