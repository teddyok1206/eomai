"""Guarded PG locks/official Artifact commit; synthetic IAM/ranking, no live inference."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from time import perf_counter, sleep
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from eom_catalog_contracts.completed_public_ranking import CompletedPublicSimilarityRanking
from eom_catalog_service import completed_public_ranking_read as module
from eom_catalog_service import public_solution_population_dependencies as dependencies
from eom_catalog_service.completed_public_ranking_dependencies import (
    observe_completed_public_ranking_dependencies,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.local_indexing_source_paging import (
    candidate_source_page_statement,
    read_candidate_source_pages,
    validate_candidate_source_page,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eom_orchestrator.completed_public_ranking_artifact import CompletedPublicRankingArtifactStore
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_inference_transfer_candidate_admission import (
    item_source_relation_database as item_source_relation_database,
)
from tests.integration.test_inference_transfer_candidate_admission import (
    occurrence_scope,
)
from tests.integration.test_inference_transfer_candidate_admission import (
    pool_database as pool_database,
)
from tests.integration.test_inference_transfer_candidate_admission import (
    population_observation_database as population_observation_database,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_completed_public_ranking import values

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def saved(guarded_engine, tmp_path, monkeypatch):
    original, context, old_selection = values()
    selection = old_selection.model_copy(update={"workflow_id": "workflow_" + uuid4().hex})
    settings = Settings(
        staging_root=tmp_path / "stage",
        workspace_root=tmp_path / "work",
        nas_artifact_root=tmp_path / "nas",
    )
    for path in (settings.staging_root, settings.workspace_root, settings.nas_artifact_root):
        path.mkdir()
    publisher = ControlFileSetPublisher(guarded_engine, settings)
    store = CompletedPublicRankingArtifactStore(publisher, source_commit="a" * 40)
    owner = NS(
        settings=CatalogSettings(
            staging_root=tmp_path / "catalog", nas_artifact_root=settings.nas_artifact_root
        )
    )
    caller = EmbeddingRegistryCaller(original.operator_audit.operator_id)
    calls = []
    monkeypatch.setattr(module, "select_completed_reference_query_request", lambda *_a: original)
    monkeypatch.setattr(
        module, "select_completed_reference_query_read_owner", lambda value, _r: value
    )
    monkeypatch.setattr(module, "_scope", lambda *_a: "synthetic-authority-leaf")
    monkeypatch.setattr(
        module, "observe_completed_public_ranking_dependencies", lambda *_a: "sha256:" + "a" * 64
    )

    def compose(*_a):
        calls.append("ranking")
        sleep(0.1)  # Only a synthetic competing-read window, never a live delay.
        return context

    monkeypatch.setattr(module, "read_completed_public_solution_similarity_in_session", compose)

    def read():
        with Session(guarded_engine) as session, session.begin():
            return module.read_saved_public_ranking_in_session(
                session, owner, caller, selection, store=store
            )

    return NS(
        engine=guarded_engine,
        original=original,
        context=context,
        selection=selection,
        publisher=publisher,
        store=store,
        read=read,
        calls=calls,
        root=settings.nas_artifact_root,
    )


def test_two_concurrent_completed_reads_create_one_ranking_and_one_official_artifact(saved):
    start = Barrier(2)

    def read():
        start.wait(timeout=10)
        return saved.read()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [future.result(timeout=30) for future in (pool.submit(read), pool.submit(read))]
    assert a == b == saved.context and saved.calls == ["ranking"]
    assert saved.read() == a and saved.calls == ["ranking"]
    with Session(saved.engine) as session:
        key = "completed-public-ranking:" + content_sha256(
            dict(
                operator_id=saved.original.operator_audit.operator_id,
                selection=saved.selection.model_dump(mode="json"),
            )
        ).removeprefix("sha256:")
        count = session.scalar(
            select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
        )
        assert count == 1
    # No placeholder ORM cache row/migration or hidden vector/model process exists.
    assert list(saved.root.rglob("ranking.json"))


def test_interrupted_publication_replays_one_identity_without_repairing_terminal_corruption(
    saved, monkeypatch
):
    body = dict(
        schema_version="completed-public-similarity-ranking/1.0",
        operator_id=saved.original.operator_audit.operator_id,
        selection=saved.selection.model_dump(mode="json"),
        context=saved.context.model_dump(mode="json"),
        dependency_sha256="sha256:" + "a" * 64,
    )
    snapshot = CompletedPublicSimilarityRanking.model_validate(seal(body, "snapshot_sha256"))
    key = "saved-ranking-interruption:" + uuid4().hex
    advance = saved.publisher._advance
    monkeypatch.setattr(
        saved.publisher,
        "_advance",
        lambda _identity: (_ for _ in ()).throw(RuntimeError("synthetic publication interruption")),
    )
    with pytest.raises(RuntimeError):
        saved.store.commit(snapshot, key)
    assert saved.store.find(key) is None
    assert (
        saved.publisher.publication_state(
            idempotency_key=key, artifact_type="control_completed_public_ranking"
        )
        == JobState.CREATED
    )
    with Session(saved.engine) as session:
        first = session.scalar(select(JobRecord.job_id).where(JobRecord.idempotency_key == key))
    monkeypatch.setattr(saved.publisher, "_advance", advance)
    pointer = saved.store.commit(snapshot, key)
    assert saved.store.find(key) == pointer
    with Session(saved.engine) as session:
        job = session.scalar(select(JobRecord).where(JobRecord.idempotency_key == key))
        assert job.job_id == first and job.status == "SUCCEEDED"
    # Fault only this synthetic disposable file, never an immutable approved DB row.
    path = next(saved.root.rglob("ranking.json"))
    path.chmod(0o600)
    path.write_bytes(b"synthetic corruption")
    with pytest.raises(ControlPlaneError):
        saved.store.find(key)
    assert (
        saved.publisher.publication_state(
            idempotency_key=key, artifact_type="control_completed_public_ranking"
        )
        == JobState.SUCCEEDED
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
        "WHERE item_id='item_'||lpad('545',32,'0')",
        "UPDATE pg_temp.item_components SET required=false "
        "WHERE item_revision_id='itemrev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.artifacts SET approved=false "
        "WHERE logical_artifact_id='artifact_'||lpad('545',32,'0')",
    ),
)
def test_fresh_sql_dependency_fingerprint_detects_an_unreturned_source_change(
    population_observation_database, mutation, record_property
):
    session = population_observation_database
    original, _context, selection = values()
    context = original.context_request
    scope = replace(
        occurrence_scope(maximum=1024),
        graph_snapshot=context.graph_snapshot,
        access_policy_revision_id=context.policy_revision_id,
        access_policy_sha256=context.policy_sha256,
        requested_by=original.operator_audit.operator_id,
        source_classes=context.source_classes,
    )
    for table in (
        "knowledge_graph_snapshots",
        "knowledge_snapshot_analyses",
        "knowledge_nodes",
        "knowledge_node_source_pointers",
        "assessment_item_occurrence_references",
    ):
        session.execute(
            text(f"UPDATE pg_temp.{table} SET graph_snapshot_revision_id=:graph"),
            {"graph": context.graph_snapshot.graph_snapshot_revision_id},
        )
    started = perf_counter()
    first = observe_completed_public_ranking_dependencies(
        session, scope, original, selection.workflow_id
    )
    assert first == observe_completed_public_ranking_dependencies(
        session, scope, original, selection.workflow_id
    )
    session.execute(text(mutation))
    assert first != observe_completed_public_ranking_dependencies(
        session, scope, original, selection.workflow_id
    )
    elapsed = perf_counter() - started
    record_property("saved_ranking_545_source_three_metadata_observations_seconds", elapsed)
    assert elapsed < 20  # Synthetic SQL ceiling, not a live latency claim.


def test_bounded_membership_scan_preserves_legacy_dependency_fingerprint(
    population_observation_database, monkeypatch, record_property
):
    session = population_observation_database
    scope = occurrence_scope(maximum=1024)
    count = {"legacy": 0, "bounded": 0}

    def legacy_pages(session, scope, *, maximum_sources):
        pages = []
        after = None
        while True:
            count["legacy"] += 1
            page = validate_candidate_source_page(
                tuple(
                    tuple(row)
                    for row in session.execute(
                        candidate_source_page_statement(scope, after_source_revision_id=after)
                    )
                ),
                maximum=scope.maximum_candidates,
                after_source_revision_id=after,
            )
            pages.append(page)
            if page.complete:
                break
            after = page.next_after_source_revision_id
        assert sum(len(page.members) for page in pages) <= maximum_sources
        return tuple(pages)

    def bounded_pages(*args, **kwargs):
        count["bounded"] += 1
        return read_candidate_source_pages(*args, **kwargs)

    monkeypatch.setattr(dependencies, "read_candidate_source_pages", legacy_pages)
    started = perf_counter()
    before = dependencies.observe_public_solution_population_dependencies(session, scope, 16384)
    record_property("legacy_membership_seconds", perf_counter() - started)
    monkeypatch.setattr(dependencies, "read_candidate_source_pages", bounded_pages)
    started = perf_counter()
    after = dependencies.observe_public_solution_population_dependencies(session, scope, 16384)
    record_property("bounded_membership_seconds", perf_counter() - started)
    assert before == after
    assert count == {"legacy": 6, "bounded": 2}  # 545 sources, 3 pages, before/after.


def test_membership_changed_during_observation_is_not_accepted(
    population_observation_database, monkeypatch
):
    session = population_observation_database
    scope = occurrence_scope(maximum=1024)
    calls = 0

    def change_before_second_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            session.execute(
                text(
                    "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
                    "WHERE item_id='item_'||lpad('545',32,'0')"
                )
            )
        return read_candidate_source_pages(*args, **kwargs)

    monkeypatch.setattr(dependencies, "read_candidate_source_pages", change_before_second_read)
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        dependencies.observe_public_solution_population_dependencies(session, scope, 16384)
