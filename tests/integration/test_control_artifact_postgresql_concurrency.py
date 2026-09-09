from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine, delete, func, select


def test_postgresql_concurrent_control_publication_creates_one_identity(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    """Exercise the production advisory-lock path on an explicit disposable database."""

    suffix = uuid4().hex
    idempotency_key = f"control-artifact-postgresql:{suffix}"
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "nas",
    )
    settings.nas_artifact_root.mkdir()
    publisher = ControlArtifactPublisher(integration_engine, settings)
    sessions = build_session_factory(integration_engine)
    start = threading.Barrier(2)

    def publish() -> object:
        start.wait(timeout=5)
        return publisher.publish_bytes(
            payload=b'{"schema_version":"test/1.0","value":"postgresql"}',
            logical_name=f"control-{suffix}.json",
            schema_ref="eom://schemas/test/control-test/1.0",
            media_type="application/json",
            artifact_type="control_test",
            idempotency_key=idempotency_key,
            created_at=datetime(2026, 9, 9, 0, 0, tzinfo=UTC),
            source_commit="a" * 40,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(publish), executor.submit(publish))
            first, second = (future.result(timeout=20) for future in futures)

        assert first == second
        with sessions() as session:
            jobs = list(
                session.scalars(
                    select(JobRecord).where(JobRecord.idempotency_key == idempotency_key)
                )
            )
            assert len(jobs) == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactRecord)
                    .where(ArtifactRecord.job_id == jobs[0].job_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactRevisionRecord)
                    .where(ArtifactRevisionRecord.job_id == jobs[0].job_id)
                )
                == 1
            )
    finally:
        with transaction(sessions) as session:
            job_ids = list(
                session.scalars(
                    select(JobRecord.job_id).where(JobRecord.idempotency_key == idempotency_key)
                )
            )
            if job_ids:
                session.execute(
                    delete(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id.in_(job_ids))
                )
                session.execute(delete(ArtifactRecord).where(ArtifactRecord.job_id.in_(job_ids)))
                session.execute(delete(JobEventRecord).where(JobEventRecord.job_id.in_(job_ids)))
                session.execute(delete(JobRecord).where(JobRecord.job_id.in_(job_ids)))
