"""One strict public INDEX capture per DB root, with fresh relational fences."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import get_ident

from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_population_dependencies import (
    observe_public_solution_population_dependencies,
)
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class _IndexPopulationReadSet:
    root: SessionTransaction
    thread_id: int
    settings: CatalogSettings
    intent: LocalIndexingSourceReadIntent
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
    """No cross-root retention, authority cache, source mutation or numerical work.

    The caller has just authorized the real INDEX service. Each original fence
    observes the complete current source closure and reauthorizes again. Only
    repeated immutable interpretation is avoided, not current provenance checks.
    """
    reader.require_session(session)
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    previous = session.info.get(_IndexPopulationReadSet)
    if previous is not None and type(previous) is not _IndexPopulationReadSet:
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    if previous is not None and previous.root is root and previous.thread_id != get_ident():
        raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    before = observe_public_solution_population_dependencies(session, intent, maximum_sources)
    reusable = (
        previous is not None
        and previous.root is root
        and previous.settings == reader.settings
        and previous.intent == intent
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
        if (
            observe_public_solution_population_dependencies(session, intent, maximum_sources)
            != before
        ):
            raise ValueError("PUBLIC_SOLUTION_POPULATION_CHANGED")
        if value.scope != intent:
            raise ValueError("PUBLIC_SOLUTION_READ_SET_INVALID")
    reader.revalidate_provenance()
    if reauthorize() != intent:
        raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
    if not reusable:
        session.info[_IndexPopulationReadSet] = _IndexPopulationReadSet(
            root, get_ident(), reader.settings, intent, maximum_sources, before, value
        )
    return value
