"""Guarded PostgreSQL/local Artifact completion; no production source or runtime authority."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.local_embedding_workflow_receipt import parse_local_embedding_workflow_receipt
from sqlalchemy import Engine, func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def completion(guarded_engine: Engine, tmp_path: Path):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    root, workspace = tmp_path / "artifacts", tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    owner = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=root, workspace_root=workspace
        ),
    )
    identity = ControlFileSetIdentity(
        "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    body = receipt_fixture().receipt.model_dump(mode="json")
    body.update(workflow_id="workflow_" + uuid4().hex, receipt_owner_job_id=identity.job_id)
    receipt = parse_local_embedding_workflow_receipt(seal(body, "receipt_sha256"))
    return NativeEmbeddingCompletionPublisher(owner, source_commit="a" * 40), receipt, identity


def test_concurrent_publication_has_one_actual_producer_and_exact_replay(completion) -> None:
    publisher, receipt, identity = completion
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=20)
        return publisher.publish(receipt, identity=identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(lambda _ordinal: run(), range(2)))
    assert first == second == publisher.publish(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        producer = session.get(JobRecord, identity.job_id)
        assert producer.status == "SUCCEEDED" and producer.worker_slot_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == identity.job_id)
            )
            == 1
        )
        assert (
            resolve_native_embedding_completion(
                session,
                CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
                first,
            )
            == receipt
        )
        assert set(producer.request) == {
            "primary_file",
            "artifact_type",
            "manifest_version",
            "members",
            "source_commit",
            "created_at_utc",
        }
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


def test_conflicting_identity_cannot_reallocate_existing_postgres_job(completion) -> None:
    publisher, receipt, identity = completion
    first = publisher.publish(receipt, identity=identity)
    changed = ControlFileSetIdentity(
        identity.job_id, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    with pytest.raises(ControlPlaneError, match="existing allocation differs"):
        publisher.publish(receipt, identity=changed)
    assert publisher.publish(receipt, identity=identity) == first


def test_postgres_commit_interruption_reuses_exact_receipt_identity(
    completion, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, receipt, identity = completion
    original = publication.create_artifact_records
    interrupted = False

    def fail_once(*args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("isolated PostgreSQL commit interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(publication, "create_artifact_records", fail_once)
    with pytest.raises(RuntimeError, match="isolated PostgreSQL commit interruption"):
        publisher.publish(receipt, identity=identity)
    output = publisher.publish(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        assert (
            resolve_native_embedding_completion(
                session,
                CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
                output,
            )
            == receipt
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == identity.job_id)
            )
            == 1
        )
