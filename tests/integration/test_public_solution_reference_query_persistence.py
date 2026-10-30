"""Guarded disposable PostgreSQL QUERY2 publication, no real source authority/model/GPU.

Control Job/Artifact transactions and local file bytes are real. Workflow/source
admission and numerical output are explicitly synthetic, never live acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from eom_catalog_service.reference_query_artifact_read import CatalogReferenceQueryArtifacts
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_public_solution_query_artifacts import (
    public_artifact_case,
    publication_arguments,
    publish_public_query,
    published_read_arguments,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def publication(guarded_engine, tmp_path):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=artifacts),
    )
    return public_artifact_case(tmp_path, publisher)


def test_same_query2_concurrent_publication_commits_one_job_and_one_revision(publication):
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=30)
        return publish_public_query(publication)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _: submit(), range(2)))
    assert first == second
    with publication.publisher.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.job_id == first.owner_job_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.revision_id == first.result.artifact_revision_id)
            )
            == 1
        )
        value = CatalogReferenceQueryArtifacts(
            session,
            CatalogSettings(nas_artifact_root=publication.publisher.settings.nas_artifact_root),
        ).resolve_public_solution_publication(**published_read_arguments(publication, first))
        assert value.result == publication.case.result
        assert value.binary == publication.binary


def test_query2_owner_restart_after_commit_reuses_canonical_output_without_new_encoding(
    publication,
):
    first = publish_public_query(publication)
    # Simulate loss of the caller's post-commit response, not native re-execution.
    restarted = EmbeddingArtifactStore(publication.publisher, source_commit="a" * 40)
    second = restarted.publish_public_solution_reference_query(**publication_arguments(publication))
    assert first == second
    with publication.publisher.sessions.begin() as session:
        value = CatalogReferenceQueryArtifacts(
            session,
            CatalogSettings(nas_artifact_root=publication.publisher.settings.nas_artifact_root),
        ).resolve_public_solution_publication(**published_read_arguments(publication, second))
        assert value.request == publication.case.native_input
        assert value.publication_job_id == first.owner_job_id


def test_query2_declared_completion_mismatch_does_not_create_a_successful_publication(publication):
    from eom_identifiers import content_sha256
    from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStoreError

    args = publication_arguments(publication)
    args["expected_result_sha256"] = content_sha256({"foreign_completion": True})
    with publication.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    with pytest.raises(EmbeddingArtifactStoreError, match="RESULT_INVALID"):
        publication.store.publish_public_solution_reference_query(**args)
    with publication.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
