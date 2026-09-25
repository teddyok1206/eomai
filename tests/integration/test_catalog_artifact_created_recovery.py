from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_file
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import IdempotencyConflict
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, func, select

pytestmark = pytest.mark.integration


def _settings(tmp_path: Path) -> CatalogSettings:
    staging = tmp_path / "catalog-staging"
    nas = tmp_path / "nas"
    intake = tmp_path / "intake"
    staging.mkdir()
    nas.mkdir()
    intake.mkdir()
    return CatalogSettings(
        staging_root=staging,
        nas_artifact_root=nas.resolve(),
        intake_root=intake,
        placeholder_pack_source=tmp_path / "unused-pack",
        knowledge_stimulus_source=tmp_path / "unused-stimulus.png",
    )


def _commit(
    service: CatalogArtifactService,
    *,
    source: Path,
    idempotency_key: str,
    request: dict[str, str],
    expected_sha256: str,
) -> CatalogArtifact:
    return service.commit_file_set(
        files={"payload.json": source},
        primary_file="payload.json",
        artifact_type="catalog-created-recovery-test",
        idempotency_key=idempotency_key,
        request=request,
        result={"status": "ok"},
        file_metadata={
            "payload.json": {
                "schema_ref": "eom://schemas/test/catalog-created-recovery/1.0",
                "media_type": "application/json",
            }
        },
        expected_file_sha256={"payload.json": expected_sha256},
    )


def test_created_job_replays_after_precommit_hash_failure(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    service = CatalogArtifactService(integration_engine, settings)
    source = tmp_path / "payload.json"
    source.write_text('{"status":"ok"}', encoding="utf-8")
    idempotency_key = f"catalog-created-recovery:{uuid4().hex}"
    request = {"fixture": uuid4().hex}

    with pytest.raises(
        ValueError,
        match="catalog artifact staged members do not match expected hashes",
    ):
        _commit(
            service,
            source=source,
            idempotency_key=idempotency_key,
            request=request,
            expected_sha256="sha256:" + "0" * 64,
        )

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        job = session.scalar(select(JobRecord).where(JobRecord.idempotency_key == idempotency_key))
        assert job is not None
        assert job.status == JobState.CREATED.value
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job.job_id)
            )
            == 0
        )
        job_id = job.job_id
        artifact_id = job.logical_artifact_id
        revision_id = job.revision_id
    assert not any((settings.staging_root / job_id).iterdir())

    with pytest.raises(IdempotencyConflict):
        _commit(
            service,
            source=source,
            idempotency_key=idempotency_key,
            request={"fixture": "different"},
            expected_sha256=sha256_file(source),
        )

    committed = _commit(
        service,
        source=source,
        idempotency_key=idempotency_key,
        request=request,
        expected_sha256=sha256_file(source),
    )
    replayed = _commit(
        service,
        source=source,
        idempotency_key=idempotency_key,
        request=request,
        expected_sha256=sha256_file(source),
    )

    assert committed == replayed
    assert committed.job_id == job_id
    assert committed.artifact_id == artifact_id
    assert committed.revision_id == revision_id
    assert Path(committed.nas_path).is_dir()
    assert not any((settings.staging_root / job_id).iterdir())
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == idempotency_key)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job_id)
            )
            == 1
        )


def test_incomplete_job_after_created_state_remains_fail_closed(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    service = CatalogArtifactService(integration_engine, settings)
    source = tmp_path / "payload.json"
    source.write_text('{"status":"ok"}', encoding="utf-8")
    idempotency_key = f"catalog-non-created-recovery:{uuid4().hex}"
    request = {"fixture": uuid4().hex}

    with pytest.raises(ValueError):
        _commit(
            service,
            source=source,
            idempotency_key=idempotency_key,
            request=request,
            expected_sha256="sha256:" + "0" * 64,
        )

    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        job = session.scalar(select(JobRecord).where(JobRecord.idempotency_key == idempotency_key))
        assert job is not None
        transition_job(session, job.job_id, JobState.VALIDATED, "TEST_VALIDATED_WITHOUT_ARTIFACT")

    with pytest.raises(RuntimeError, match="catalog artifact job is incomplete"):
        _commit(
            service,
            source=source,
            idempotency_key=idempotency_key,
            request=request,
            expected_sha256=sha256_file(source),
        )
