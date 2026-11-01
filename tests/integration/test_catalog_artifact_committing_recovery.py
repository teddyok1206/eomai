"""Real PostgreSQL interruption/replay and concurrent same-key publication."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.artifact_publication_lock import artifact_publication_lock
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select, text

from tests.unit import test_catalog_artifact_commit_recovery as cases

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog_service(integration_engine, tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    return CatalogArtifactService(
        integration_engine,
        CatalogSettings(
            nas_artifact_root=nas,
            staging_root=tmp_path / "staging",
        ),
    )


@pytest.mark.parametrize("after_nas", [False, True])
def test_postgres_original_identity_after_interruption(
    catalog_service, tmp_path, monkeypatch, after_nas
):
    cases.test_original_sealed_job_replays_after_interruption(
        catalog_service,
        tmp_path,
        monkeypatch,
        after_nas,
    )


def test_postgres_original_legacy_owner_reconstruction(catalog_service, tmp_path, monkeypatch):
    cases.test_legacy_absent_destination_requires_current_owner_proof(
        catalog_service, tmp_path, monkeypatch
    )


def test_postgres_current_authority_is_rechecked_after_nas(catalog_service, tmp_path, monkeypatch):
    cases.test_authority_withdrawal_after_nas_does_not_promote_revision(
        catalog_service, tmp_path, monkeypatch
    )


def test_postgres_three_same_key_writers_publish_one_revision(catalog_service, tmp_path):
    args = cases.arguments(tmp_path)
    start = Barrier(3)

    def write(_index):
        start.wait(timeout=15)
        service = CatalogArtifactService(catalog_service.engine, catalog_service.settings)
        return service.commit_file_set(**args)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(write, range(3)))
    assert results[0] == results[1] == results[2]
    with catalog_service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == args["idempotency_key"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == results[0].job_id)
            )
            == 1
        )


@pytest.mark.parametrize("fail", [False, True])
def test_postgres_publication_lock_is_released_after_owner_exit(integration_engine, tmp_path, fail):
    # A separate session must observe the same-key lock and acquire it only after owner exit.
    import hashlib

    namespace, key = "eom:catalog-artifact-publication", tmp_path.name
    number = int.from_bytes(
        hashlib.sha256(f"{namespace}:{key}".encode()).digest()[:8], "big", signed=True
    )

    def body():
        with artifact_publication_lock(
            integration_engine, namespace=namespace, idempotency_key=key, local_lock=Lock()
        ):
            with integration_engine.connect() as other:
                assert (
                    other.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": number})
                    is False
                )
            if fail:
                raise RuntimeError("synthetic owner exit")

    if fail:
        with pytest.raises(RuntimeError, match="synthetic owner exit"):
            body()
    else:
        body()
    with integration_engine.connect() as other:
        assert other.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": number}) is True
        assert other.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": number}) is True
