"""Prepared opt-in disposable DB index publication; synthetic metadata, never source authority.

Uses the existing guarded PostgreSQL lifecycle and a temporary local artifact root.
These tests are not executed as part of the source-only implementation task.
"""

from __future__ import annotations

import inspect
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingVectorShardManifest,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import file_set_control_artifacts as publication_module
from eom_orchestrator.artifacts import StagedFileSet, commit_file_set_artifact
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_INDEX_ARTIFACT_TYPE,
    EMBEDDING_INDEX_MANIFEST_VERSION,
    EMBEDDING_INDEX_MEMBER_NAMES,
    EmbeddingArtifactStore,
    EmbeddingIndexPublicationScope,
    PublishedEmbeddingIndexArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import DBAPIError

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    seal,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW

pytestmark = pytest.mark.integration
SOURCE_COMMIT = "a" * 40


@dataclass(frozen=True)
class SyntheticIndexPublication:
    engine: Engine
    settings: Settings
    index: EmbeddingIndexManifest
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    scope: EmbeddingIndexPublicationScope
    key: str

    def workspace(self, name: str) -> Path:
        path = self.settings.workspace_root / name
        path.mkdir(mode=0o700)
        return path

    def publish(
        self, workspace: Path, *, index: EmbeddingIndexManifest | None = None
    ) -> PublishedEmbeddingIndexArtifacts:
        return EmbeddingArtifactStore(
            ControlFileSetPublisher(self.engine, self.settings), source_commit=SOURCE_COMMIT
        ).publish_index(
            index=index or self.index,
            shards=self.shards,
            previous=None,
            scope=self.scope,
            workspace=workspace,
        )


@pytest.fixture
def publication(guarded_engine: Engine, tmp_path: Path) -> SyntheticIndexPublication:
    assert guarded_engine.dialect.name == "postgresql"
    assert tmp_path.is_absolute() and not tmp_path.is_relative_to(Path("/mnt/nas"))
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "temporary-artifacts",
        workspace_root=tmp_path / "workspaces",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    binding = source_binding()
    body = index_manifest(binding).model_dump(mode="json") | {
        "index_id": "embeddingindex_" + uuid4().hex,
        "index_revision_id": "embeddingindexrev_" + uuid4().hex,
    }
    index = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    shard = vector_shard((binding.encoding,), space=index.space)
    return SyntheticIndexPublication(
        guarded_engine,
        settings,
        index,
        ((binding.row_ref.shard_manifest, shard),),
        EmbeddingIndexPublicationScope(
            binding.graph_snapshot, binding.policy_revision_id, binding.policy_sha256
        ),
        "embedding-index-artifact:"
        + content_sha256(
            {"index_id": index.index_id, "index_revision_id": index.index_revision_id}
        )[7:],
    )


def _persisted_package(
    value: SyntheticIndexPublication, receipt: PublishedEmbeddingIndexArtifacts
) -> Path:
    sessions = build_session_factory(value.engine)
    with sessions() as session:
        jobs = tuple(
            session.scalars(select(JobRecord).where(JobRecord.idempotency_key == value.key))
        )
        assert len(jobs) == 1
        job = jobs[0]
        artifacts = tuple(
            session.scalars(select(ArtifactRecord).where(ArtifactRecord.job_id == job.job_id))
        )
        revisions = tuple(
            session.scalars(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job.job_id)
            )
        )
        assert len(artifacts) == len(revisions) == 1
        artifact, revision = artifacts[0], revisions[0]
        assert job.status == "SUCCEEDED" and job.worker_slot_id is None
        assert job.task_type == artifact.artifact_type == EMBEDDING_INDEX_ARTIFACT_TYPE
        assert job.protocol_version == EMBEDDING_INDEX_MANIFEST_VERSION
        assert artifact.approved and revision.approved  # Control bytes only, not Item eligibility.
        assert job.job_id == artifact.job_id == revision.job_id == receipt.owner_job_id
        assert receipt.index_id == value.index.index_id != receipt.owner_job_id
        assert receipt.index_revision_id == value.index.index_revision_id
        assert artifact.logical_artifact_id == receipt.index_manifest.artifact_id
        assert revision.revision_id == receipt.index_manifest.artifact_revision_id
        assert revision.content_hash == receipt.index_manifest.sha256
        assert revision.manifest_hash == receipt.manifest_sha256
        assert content_sha256(revision.manifest) == receipt.manifest_sha256
        assert revision.result == {"schema_version": "control-file-set-result/1.0", **job.request}
        assert set(job.request) == {
            "primary_file",
            "artifact_type",
            "manifest_version",
            "members",
            "source_commit",
            "created_at_utc",
        }
        assert job.request["source_commit"] == SOURCE_COMMIT
        assert job.request["created_at_utc"] == NOW.isoformat().replace("+00:00", "Z")
        assert (
            tuple(member["file_name"] for member in job.request["members"])
            == EMBEDDING_INDEX_MEMBER_NAMES
        )
        assert job.request["members"] == revision.manifest["files"]
        assert all(
            set(member) == {"file_name", "sha256", "bytes", "schema_ref", "media_type"}
            for member in job.request["members"]
        )
        assert not {"vectors", "source", "text", "report", "model", "bindings"}.intersection(
            job.request
        )
        root = Path(revision.nas_path)
        manifest = revision.manifest
    assert (
        root
        == value.settings.nas_artifact_root
        / receipt.index_manifest.artifact_id
        / receipt.index_manifest.artifact_revision_id
    )
    assert {path.name for path in root.iterdir()} == {"index.json", "manifest.json"}
    payload = (root / "index.json").read_bytes()
    assert payload == canonical_json_bytes(value.index.model_dump(mode="json"))
    assert sha256_bytes(payload) == receipt.index_manifest.sha256
    assert receipt.index_manifest.schema_ref == INDEX_SCHEMA_REF
    assert receipt.index_manifest.media_type == "application/json"
    assert receipt.index_sha256 == value.index.index_sha256 != receipt.index_manifest.sha256
    assert (root / "manifest.json").read_bytes() == canonical_json_bytes(manifest)
    return root


def test_disposable_index_replay_conflict_and_control_artifact_immutability(
    publication: SyntheticIndexPublication,
) -> None:
    workspace = publication.workspace("initial")
    receipt = publication.publish(workspace)
    root = _persisted_package(publication, receipt)
    before = {name: (root / name).stat() for name in ("index.json", "manifest.json")}
    assert publication.publish(workspace) == receipt
    for name, initial in before.items():
        after = (root / name).stat()
        assert (initial.st_ino, initial.st_mtime_ns, initial.st_size) == (
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        )
    body = publication.index.model_dump(mode="json") | {
        "created_at": (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    }
    changed = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    with pytest.raises(ControlPlaneError) as conflict:
        publication.publish(publication.workspace("changed-same-revision"), index=changed)
    assert conflict.value.code == "CONTROL_FILE_SET_CONFLICT"
    assert publication.publish(workspace) == receipt
    _persisted_package(publication, receipt)
    sessions = build_session_factory(publication.engine)
    with (
        pytest.raises(DBAPIError, match="approved EOM artifacts and revisions are immutable"),
        transaction(sessions) as session,
    ):
        session.execute(
            update(ArtifactRecord)
            .where(ArtifactRecord.logical_artifact_id == receipt.index_manifest.artifact_id)
            .values(approved=False)
        )


class _PublicationStart(Protocol):
    def wait(self, timeout: float) -> int: ...


def _publish_index_in_spawned_owner(
    index: EmbeddingIndexManifest,
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    scope: EmbeddingIndexPublicationScope,
    settings: Settings,
    workspace: Path,
    start: _PublicationStart,
) -> tuple[int, PublishedEmbeddingIndexArtifacts]:
    explicit_url = os.environ.get("EOM_DATABASE_URL")
    if os.environ.get("EOM_RUN_INTEGRATION") != "1" or not explicit_url:
        raise AssertionError("index publication requires explicit disposable DB opt-in")
    engine = build_engine(explicit_url)  # No runtime secret fallback.
    try:
        assert inspect.unwrap(guarded_engine)(engine) is engine
        assert engine.dialect.name == "postgresql"
        assert workspace.is_relative_to(settings.workspace_root)
        assert all(
            path.is_absolute() and not path.is_relative_to(Path("/mnt/nas"))
            for path in (workspace, settings.staging_root, settings.nas_artifact_root)
        )
        start.wait(timeout=20)
        receipt = EmbeddingArtifactStore(
            ControlFileSetPublisher(engine, settings), source_commit=SOURCE_COMMIT
        ).publish_index(index=index, shards=shards, previous=None, scope=scope, workspace=workspace)
        return os.getpid(), receipt
    finally:
        engine.dispose()


def test_disposable_independent_process_same_revision_has_one_owner_identity(
    publication: SyntheticIndexPublication,
) -> None:
    workspaces = (publication.workspace("first-owner"), publication.workspace("second-owner"))
    context = multiprocessing.get_context("spawn")
    with (
        context.Manager() as manager,
        ProcessPoolExecutor(max_workers=2, mp_context=context) as executor,
    ):
        start = manager.Barrier(2)
        futures = tuple(
            executor.submit(
                _publish_index_in_spawned_owner,
                publication.index,
                publication.shards,
                publication.scope,
                publication.settings,
                workspace,
                start,
            )
            for workspace in workspaces
        )
        (first_pid, first), (second_pid, second) = (future.result(timeout=45) for future in futures)
    assert first_pid != second_pid and os.getpid() not in {first_pid, second_pid}
    assert first == second
    root = _persisted_package(publication, first)
    assert publication.publish(workspaces[0]) == first
    assert tuple(path.name for path in root.parent.iterdir()) == (
        first.index_manifest.artifact_revision_id,
    )


def test_disposable_post_file_commit_failure_replays_exact_existing_index(
    publication: SyntheticIndexPublication, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = publication.workspace("partial-owner-commit")
    original_commit = commit_file_set_artifact

    def fail_after_commit(staged: StagedFileSet, nas_root: Path) -> Path:
        original_commit(staged, nas_root)
        raise RuntimeError("synthetic failure after immutable local artifact commit")

    monkeypatch.setattr(publication_module, "commit_file_set_artifact", fail_after_commit)
    with pytest.raises(RuntimeError):
        publication.publish(workspace)
    sessions = build_session_factory(publication.engine)
    with sessions() as session:
        job = session.scalars(
            select(JobRecord).where(JobRecord.idempotency_key == publication.key)
        ).one()
        assert job.status == "COMMITTING"
        assert session.get(ArtifactRecord, job.logical_artifact_id) is None
        committed = (
            publication.settings.nas_artifact_root / job.logical_artifact_id / job.revision_id
        )
    before = (committed / "index.json").stat()
    monkeypatch.setattr(publication_module, "commit_file_set_artifact", original_commit)
    receipt = publication.publish(workspace)
    assert _persisted_package(publication, receipt) == committed
    assert (committed / "index.json").stat().st_ino == before.st_ino
    assert publication.publish(workspace) == receipt
