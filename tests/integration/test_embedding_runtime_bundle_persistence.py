"""Opt-in synthetic bundle publication in a marker-guarded DB and local artifact root."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_runtime_bundle_bytes,
)
from eom_orchestrator import control_artifacts as owner_module
from eom_orchestrator.artifacts import StagedFileSet, commit_file_set_artifact
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    RUNTIME_BUNDLE_ARTIFACT_TYPE,
    EmbeddingRuntimeBundleArtifactPublisher,
    PublishedEmbeddingRuntimeBundle,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


@dataclass(frozen=True)
class BundlePublication:
    engine: Engine
    settings: Settings
    bundle: EmbeddingRuntimeBundle

    def publish(
        self, bundle: EmbeddingRuntimeBundle | None = None
    ) -> PublishedEmbeddingRuntimeBundle:
        return EmbeddingRuntimeBundleArtifactPublisher(
            ControlArtifactPublisher(self.engine, self.settings), source_commit="a" * 40
        ).publish(self.bundle if bundle is None else bundle, created_at=NOW)


@pytest.fixture
def publication(guarded_engine: Engine, tmp_path: Path) -> BundlePublication:
    assert tmp_path.is_absolute() and not tmp_path.is_relative_to(Path("/mnt/nas"))
    settings = Settings(staging_root=tmp_path / "staging", nas_artifact_root=tmp_path / "artifacts")
    settings.nas_artifact_root.mkdir(mode=0o700)
    body = native_config_metadata()[1].model_dump(mode="json") | {
        "bundle_id": "embeddingbundle_" + uuid4().hex,
        "bundle_revision_id": "embeddingbundlerev_" + uuid4().hex,
    }
    return BundlePublication(
        guarded_engine, settings, EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    )


def persisted(value: BundlePublication, receipt: PublishedEmbeddingRuntimeBundle) -> Path:
    member = receipt.bundle.manifest_member
    root = value.settings.nas_artifact_root / member.artifact_id / member.artifact_revision_id
    assert (root / "bundle.json").read_bytes() == embedding_runtime_bundle_bytes(value.bundle)
    with Session(value.engine) as session:
        job = session.get(JobRecord, receipt.owner_job_id)
        assert job is not None and job.status == "SUCCEEDED"
        assert job.task_type == RUNTIME_BUNDLE_ARTIFACT_TYPE
        assert (
            job.logical_artifact_id == member.artifact_id
            and job.revision_id == member.artifact_revision_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == job.idempotency_key)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.job_id == job.job_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job.job_id)
            )
            == 1
        )
        raw = json.dumps(job.request)
        assert (
            len(raw) < 2048 and "payload_model_spec" not in raw and "numerical_runtime" not in raw
        )
    return root


def test_disposable_bundle_replay_preserves_bytes_and_changed_revision_conflicts(
    publication: BundlePublication,
) -> None:
    receipt = publication.publish()
    root = persisted(publication, receipt)
    initial = (root / "bundle.json").stat()
    later = EmbeddingRuntimeBundleArtifactPublisher(
        ControlArtifactPublisher(publication.engine, publication.settings), source_commit="b" * 40
    ).publish(publication.bundle, created_at=NOW + timedelta(seconds=1))
    assert later == receipt
    assert ((root / "bundle.json").stat().st_ino, (root / "bundle.json").stat().st_mtime_ns) == (
        initial.st_ino,
        initial.st_mtime_ns,
    )
    body = publication.bundle.model_dump(mode="json")
    body["execution_model_spec"]["model_revision_id"] = "embeddingmodelrev_" + uuid4().hex
    body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
    changed = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    with pytest.raises(ControlPlaneError):
        publication.publish(changed)
    assert persisted(publication, receipt) == root


class PublicationStart(Protocol):
    def wait(self, timeout: int) -> object: ...


def publish_in_spawned_owner(
    bundle: EmbeddingRuntimeBundle,
    settings: Settings,
    start: PublicationStart,
) -> tuple[int, PublishedEmbeddingRuntimeBundle]:
    url = os.environ.get("EOM_DATABASE_URL")
    if os.environ.get("EOM_RUN_INTEGRATION") != "1" or not url:
        raise AssertionError("explicit disposable DB opt-in required")
    engine = build_engine(url)
    try:
        assert inspect.unwrap(guarded_engine)(engine) is engine
        assert all(
            path.is_absolute() and not path.is_relative_to(Path("/mnt/nas"))
            for path in (settings.staging_root, settings.nas_artifact_root)
        )
        start.wait(timeout=20)
        receipt = BundlePublication(engine, settings, bundle).publish()
        return os.getpid(), receipt
    finally:
        engine.dispose()


def test_disposable_bundle_two_processes_use_same_original_artifact(
    publication: BundlePublication,
) -> None:
    context = multiprocessing.get_context("spawn")
    with (
        context.Manager() as manager,
        ProcessPoolExecutor(max_workers=2, mp_context=context) as executor,
    ):
        barrier = manager.Barrier(2)
        futures = [
            executor.submit(
                publish_in_spawned_owner, publication.bundle, publication.settings, barrier
            )
            for _ in range(2)
        ]
        (first_pid, first), (second_pid, second) = [future.result(timeout=45) for future in futures]
    assert first_pid != second_pid and os.getpid() not in {first_pid, second_pid}
    assert first == second == publication.publish()
    root = persisted(publication, first)
    assert tuple(path.name for path in root.parent.iterdir()) == (
        first.bundle.manifest_member.artifact_revision_id,
    )


def test_disposable_bundle_post_file_commit_failure_reconciles_same_identity(
    publication: BundlePublication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_commit(staged: StagedFileSet, nas_root: Path) -> Path:
        commit_file_set_artifact(staged, nas_root)
        raise RuntimeError("synthetic post-commit failure")

    monkeypatch.setattr(owner_module, "commit_file_set_artifact", fail_after_commit)
    with pytest.raises(RuntimeError, match="synthetic post-commit failure"):
        publication.publish()
    (committed,) = publication.settings.nas_artifact_root.glob("artifact_*/rev_*/bundle.json")
    initial = committed.stat()
    with Session(publication.engine) as session:
        job = session.scalars(
            select(JobRecord).where(JobRecord.logical_artifact_id == committed.parent.parent.name)
        ).one()
        assert job.status == "COMMITTING"
        assert session.get(ArtifactRecord, job.logical_artifact_id) is None
        job_id = job.job_id
    monkeypatch.setattr(owner_module, "commit_file_set_artifact", commit_file_set_artifact)
    result = publication.publish()
    assert result.owner_job_id == job_id
    assert persisted(publication, result) == committed.parent
    assert (committed.stat().st_ino, committed.stat().st_mtime_ns) == (
        initial.st_ino,
        initial.st_mtime_ns,
    )
