"""Guarded disposable PostgreSQL and temporary local artifacts; no model execution.

Run through the existing disposable database lifecycle with EOM_RUN_INTEGRATION=1,
an explicit EOM_DATABASE_URL and its matching EOM_API_TEST_STATE. Nominal model,
Graph and policy pins below are synthetic contract values, not source authority.
Approved rows remain append-only until the guarded disposable database is destroyed.
"""

from __future__ import annotations

import inspect
import math
import multiprocessing
import os
import stat
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any, Protocol
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    pack_unit_vectors,
    read_unit_vectors,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    PublishedEmbeddingArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.settings import Settings
from eom_workflow.local_embedding_workflow import LocalEmbeddingWorkflowRequest
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.exc import DBAPIError

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_input,
    embedding_result,
    seal,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW, sha, source_basis

pytestmark = pytest.mark.integration
SOURCE_COMMIT = "a" * 40
MEMBER_NAMES = ("result.json", "shard.json", "vectors.f32")


@dataclass(frozen=True)
class SyntheticPublication:
    engine: Engine
    settings: Settings
    store: EmbeddingArtifactStore
    request: IncrementalEmbeddingInput
    workflow_request: LocalEmbeddingWorkflowRequest
    local_root: Path
    idempotency_key: str

    def workspace(self, name: str, *, basis_index: int = 0) -> Path:
        """Only the orchestrator test UID materializes synthetic local output."""
        dimension = self.request.space.model_spec.dimension
        row = tuple(1.0 if index == basis_index else 0.0 for index in range(dimension))
        binary = pack_unit_vectors(tuple(row for _ in self.request.rows), dimension=dimension)
        body = vector_shard(
            tuple(value.encoding for value in self.request.rows), space=self.request.space
        ).model_dump(mode="json")
        body["binary"]["sha256"] = sha256_bytes(binary)
        shard = EmbeddingVectorShardManifest.model_validate(seal(body, "shard_sha256"))
        result = embedding_result(self.request, shard=shard)
        workspace = self.local_root / name
        workspace.mkdir(mode=0o700)
        for member, payload in (
            ("result.json", canonical_json_bytes(result.model_dump(mode="json"))),
            ("vectors.f32", binary),
        ):
            target = workspace / member
            target.write_bytes(payload)
            target.chmod(0o600)
            assert target.stat().st_uid == os.geteuid()
            assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert workspace.stat().st_uid == os.geteuid()
        assert stat.S_IMODE(workspace.stat().st_mode) == 0o700
        return workspace

    def publish(self, workspace: Path) -> PublishedEmbeddingArtifacts:
        return self.store.publish(
            workflow_request=self.workflow_request,
            request=self.request,
            workspace=workspace,
            created_at=NOW,
        )


@pytest.fixture
def publication(guarded_engine: Engine, tmp_path: Path) -> SyntheticPublication:
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "local-artifacts",
        workspace_root=tmp_path / "workspaces",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    request = embedding_input(
        "합성 저장 테스트 첫째 입력: 실제 교과서나 문항이 아니다.",
        "합성 저장 테스트 둘째 입력: 모델 추론을 실행하지 않는다.",
        job_id="job_" + uuid4().hex,
    )
    body: dict[str, Any] = {
        "schema_version": "local-embedding-workflow-request/1.0",
        "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
        "workflow_definition_key": "local-embedding-index",
        "workflow_definition_version": "1.0.0",
        "requested_by_operator_id": "operator_" + "1" * 32,
        "requester_permissions_sha256": sha("2"),
        "graph_snapshot": source_basis().graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": "accessrev_" + "3" * 32,
        "access_policy_sha256": sha("3"),
        "space": request.space.model_dump(mode="json"),
        "input_artifact": {
            "artifact_id": "artifact_" + "4" * 32,
            "artifact_revision_id": "rev_" + "5" * 32,
            "member_path": "input.json",
            "schema_ref": INPUT_SCHEMA_REF,
            "media_type": "application/json",
            "sha256": content_sha256(request.model_dump(mode="json")),
        },
        "input_set_sha256": request.input_set_sha256,
    }
    workflow_request = LocalEmbeddingWorkflowRequest.model_validate(seal(body, "request_sha256"))
    key = "embedding-artifact:" + content_sha256(
        {
            "logical_encoder_job_id": request.job_id,
            "native_request_sha256": request.request_sha256,
            "workflow_request_sha256": workflow_request.request_sha256,
        }
    ).removeprefix("sha256:")
    return SyntheticPublication(
        guarded_engine,
        settings,
        EmbeddingArtifactStore(
            ControlFileSetPublisher(guarded_engine, settings), source_commit=SOURCE_COMMIT
        ),
        request,
        workflow_request,
        settings.workspace_root,
        key,
    )


def _observed_control_arguments(value: SyntheticPublication) -> dict[str, Any]:
    raw = b'{"test_only":"unattended-publication-time-not-source-authority"}'
    path = value.local_root / "observed-control.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return dict(
        members=(
            ControlFileSetMember(
                "observed-control.json",
                path,
                sha256_bytes(raw),
                len(raw),
                "eom://schemas/workflow/local-embedding-source-plan/1.0",
                "application/json",
            ),
        ),
        primary_file="observed-control.json",
        artifact_type="control_observed_time_test",
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key="observed-time-test:" + uuid4().hex,
        source_commit=SOURCE_COMMIT,
    )


def test_actual_first_observation_concurrency_allocates_one_time_and_artifact(publication):
    arguments = _observed_control_arguments(publication)
    barrier = Barrier(2)
    before = datetime.now(UTC)

    def publish(_ordinal):
        publisher = ControlFileSetPublisher(publication.engine, publication.settings)
        barrier.wait(timeout=30)
        return publisher.publish_first_observation(**arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, replayed = tuple(pool.map(publish, range(2)))
    assert first == replayed
    with build_session_factory(publication.engine)() as session:
        rows = tuple(
            session.scalars(
                select(JobRecord).where(JobRecord.idempotency_key == arguments["idempotency_key"])
            )
        )
        assert len(rows) == 1 and rows[0].status == "SUCCEEDED"
        selected_time = datetime.fromisoformat(
            rows[0].request["created_at_utc"].replace("Z", "+00:00")
        )
        assert before <= selected_time <= datetime.now(UTC)


def test_actual_observed_time_survives_interruption_before_commit(publication, monkeypatch):
    arguments = _observed_control_arguments(publication)
    publisher = ControlFileSetPublisher(publication.engine, publication.settings)
    original = publisher._advance

    def interrupted(_job_id):
        raise RuntimeError("synthetic after owned publication allocation")

    monkeypatch.setattr(publisher, "_advance", interrupted)
    with pytest.raises(RuntimeError, match="allocation"):
        publisher.publish_first_observation(**arguments)
    with publisher.sessions() as session:
        original_job = session.scalar(
            select(JobRecord).where(JobRecord.idempotency_key == arguments["idempotency_key"])
        )
        original_id, original_time = original_job.job_id, original_job.request["created_at_utc"]
        assert original_job.status == "CREATED"
    monkeypatch.setattr(publisher, "_advance", original)
    replayed = publisher.publish_first_observation(**arguments)
    assert replayed.job_id == original_id
    with publisher.sessions() as session:
        saved = session.get(JobRecord, original_id)
        assert saved.status == "SUCCEEDED"
        assert saved.request["created_at_utc"] == original_time


def _metadata_only(value: object, texts: tuple[str, ...]) -> None:
    assert not isinstance(value, (bytes, bytearray, memoryview, float))
    if isinstance(value, dict):
        assert not {"vectors", "vector", "rows", "text", "input"}.intersection(value)
        for name, nested in value.items():
            _metadata_only(name, texts)
            _metadata_only(nested, texts)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _metadata_only(nested, texts)
    elif isinstance(value, str):
        assert all(text not in value for text in texts)


def _persisted_package(
    value: SyntheticPublication, receipt: PublishedEmbeddingArtifacts
) -> tuple[Path, dict[str, object]]:
    sessions = build_session_factory(value.engine)
    with sessions() as session:
        jobs = list(
            session.scalars(
                select(JobRecord).where(JobRecord.idempotency_key == value.idempotency_key)
            )
        )
        assert len(jobs) == 1
        job = jobs[0]
        artifacts = list(
            session.scalars(select(ArtifactRecord).where(ArtifactRecord.job_id == job.job_id))
        )
        revisions = list(
            session.scalars(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id == job.job_id)
            )
        )
        assert len(artifacts) == len(revisions) == 1
        artifact, revision = artifacts[0], revisions[0]
        assert job.status == "SUCCEEDED"
        assert job.task_type == artifact.artifact_type == "control_incremental_embedding"
        assert job.protocol_version == "control-file-set/1.0"
        assert job.worker_slot_id is None
        assert session.get(JobRecord, value.request.job_id) is None
        assert artifact.approved and revision.approved
        assert job.job_id == artifact.job_id == revision.job_id == receipt.owner_job_id
        assert receipt.logical_encoder_job_id == value.request.job_id != job.job_id
        assert (
            job.logical_artifact_id == artifact.logical_artifact_id == revision.logical_artifact_id
        )
        assert job.logical_artifact_id == receipt.result.artifact_id
        assert job.revision_id == revision.revision_id == receipt.result.artifact_revision_id
        assert revision.content_hash == receipt.result.sha256
        assert revision.manifest_hash == receipt.manifest_sha256
        assert content_sha256(revision.manifest) == receipt.manifest_sha256
        assert job.request["source_commit"] == SOURCE_COMMIT
        assert job.request["created_at_utc"] == NOW.isoformat().replace("+00:00", "Z")
        assert set(job.request) == {
            "primary_file",
            "artifact_type",
            "manifest_version",
            "members",
            "source_commit",
            "created_at_utc",
        }
        assert revision.result == {"schema_version": "control-file-set-result/1.0", **job.request}
        assert tuple(member["file_name"] for member in revision.manifest["files"]) == MEMBER_NAMES
        assert job.request["members"] == revision.manifest["files"]
        assert all(
            set(member) == {"file_name", "sha256", "bytes", "schema_ref", "media_type"}
            for member in job.request["members"]
        )
        texts = tuple(row.text for row in value.request.rows)
        rows = (
            dict(
                session.execute(select(JobRecord.__table__).where(JobRecord.job_id == job.job_id))
                .mappings()
                .one()
            ),
            dict(
                session.execute(
                    select(ArtifactRecord.__table__).where(ArtifactRecord.job_id == job.job_id)
                )
                .mappings()
                .one()
            ),
            dict(
                session.execute(
                    select(ArtifactRevisionRecord.__table__).where(
                        ArtifactRevisionRecord.job_id == job.job_id
                    )
                )
                .mappings()
                .one()
            ),
            *(
                dict(row)
                for row in session.execute(
                    select(JobEventRecord.__table__).where(JobEventRecord.job_id == job.job_id)
                ).mappings()
            ),
        )
        for row in rows:
            _metadata_only(row, texts)
        events = rows[3:]
        assert len(events) == 8
        assert {event["sequence"] for event in events} == set(range(1, 9))
        assert revision.content_bytes == revision.manifest["files"][0]["bytes"]
        root = Path(revision.nas_path)
        manifest = dict(revision.manifest)
    assert (
        root
        == value.settings.nas_artifact_root
        / receipt.result.artifact_id
        / receipt.result.artifact_revision_id
    )
    assert root.is_relative_to(value.settings.nas_artifact_root)
    assert {path.name for path in root.iterdir()} == {*MEMBER_NAMES, "manifest.json"}
    assert (root / "manifest.json").read_bytes() == canonical_json_bytes(manifest)
    pointers = (receipt.result, receipt.shard, receipt.binary)
    assert {pointer.artifact_id for pointer in pointers} == {receipt.result.artifact_id}
    assert {pointer.artifact_revision_id for pointer in pointers} == {
        receipt.result.artifact_revision_id
    }
    assert tuple(pointer.member_path for pointer in pointers) == MEMBER_NAMES
    assert (receipt.result.schema_ref, receipt.shard.schema_ref) == (
        RESULT_SCHEMA_REF,
        SHARD_SCHEMA_REF,
    )
    assert receipt.binary.media_type == "application/octet-stream"
    members = {member["file_name"]: member for member in manifest["files"]}
    for pointer in pointers:
        payload = (root / pointer.member_path).read_bytes()
        assert sha256_bytes(payload) == pointer.sha256 == members[pointer.member_path]["sha256"]
        assert len(payload) == members[pointer.member_path]["bytes"]
        assert members[pointer.member_path]["schema_ref"] == pointer.schema_ref
        assert members[pointer.member_path]["media_type"] == pointer.media_type
    return root, manifest


def _assert_database_immutability(
    value: SyntheticPublication, receipt: PublishedEmbeddingArtifacts
) -> None:
    sessions = build_session_factory(value.engine)
    # Exercise installed triggers, not a mock or a successful destructive mutation.
    for statement in (
        update(ArtifactRecord)
        .where(ArtifactRecord.logical_artifact_id == receipt.result.artifact_id)
        .values(approved=False),
        delete(ArtifactRecord).where(
            ArtifactRecord.logical_artifact_id == receipt.result.artifact_id
        ),
        update(ArtifactRevisionRecord)
        .where(ArtifactRevisionRecord.revision_id == receipt.result.artifact_revision_id)
        .values(approved=False),
        delete(ArtifactRevisionRecord).where(
            ArtifactRevisionRecord.revision_id == receipt.result.artifact_revision_id
        ),
    ):
        with (
            pytest.raises(DBAPIError, match="approved EOM artifacts and revisions are immutable"),
            transaction(sessions) as session,
        ):
            session.execute(statement)


def test_postgresql_embedding_package_replay_and_binary_read(
    publication: SyntheticPublication,
) -> None:
    workspace = publication.workspace("single")
    receipt = publication.publish(workspace)
    root, manifest = _persisted_package(publication, receipt)
    before = {name: (root / name).stat() for name in (*MEMBER_NAMES, "manifest.json")}
    assert publication.publish(workspace) == receipt
    assert _persisted_package(publication, receipt) == (root, manifest)
    for name, initial in before.items():
        after = (root / name).stat()
        assert (after.st_ino, after.st_mtime_ns, after.st_size) == (
            initial.st_ino,
            initial.st_mtime_ns,
            initial.st_size,
        )
    shard = EmbeddingVectorShardManifest.model_validate_json((root / "shard.json").read_bytes())
    result = IncrementalEmbeddingResult.model_validate_json((root / "result.json").read_bytes())
    assert result.shard == shard
    assert result.job_id == publication.request.job_id
    binary = (root / "vectors.f32").read_bytes()
    assert binary == (workspace / "vectors.f32").read_bytes()
    vectors = read_unit_vectors(
        binary,
        dimension=shard.dimension,
        row_count=shard.row_count,
        expected_sha256=receipt.binary.sha256,
    )
    expected = (1.0, *(0.0 for _ in range(shard.dimension - 1)))
    assert vectors == tuple(expected for _ in publication.request.rows)
    assert all(math.isclose(math.hypot(*row), 1.0, abs_tol=1e-5) for row in vectors)
    with pytest.raises(EmbeddingVectorBinaryError) as error:
        read_unit_vectors(
            bytes(len(binary)),
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=receipt.binary.sha256,
        )
    assert error.value.code == "EMBEDDING_VECTOR_HASH_MISMATCH"
    _assert_database_immutability(publication, receipt)
    changed = publication.workspace("same-key-different-binary", basis_index=1)
    with pytest.raises(ControlPlaneError) as conflict:
        publication.publish(changed)
    assert conflict.value.code == "CONTROL_FILE_SET_CONFLICT"
    assert publication.publish(workspace) == receipt
    assert _persisted_package(publication, receipt) == (root, manifest)
    assert (root / "vectors.f32").read_bytes() == binary


def test_postgresql_concurrent_embedding_publication_has_one_immutable_identity(
    publication: SyntheticPublication,
) -> None:
    workspaces = (publication.workspace("first"), publication.workspace("second"))
    context = multiprocessing.get_context("spawn")
    # Only small immutable contracts, temporary paths and a barrier cross processes.
    # Neither the parent Engine nor a publisher nor its connections are pickled.
    with (
        context.Manager() as manager,
        ProcessPoolExecutor(max_workers=2, mp_context=context) as executor,
    ):
        start = manager.Barrier(2)
        futures = tuple(
            executor.submit(
                _publish_in_spawned_owner,
                publication.request,
                publication.workflow_request,
                publication.settings,
                workspace,
                start,
            )
            for workspace in workspaces
        )
        (first_pid, first), (second_pid, second) = (future.result(timeout=45) for future in futures)
    assert first_pid != second_pid
    assert os.getpid() not in {first_pid, second_pid}
    assert first == second
    root, manifest = _persisted_package(publication, first)
    assert publication.publish(workspaces[0]) == first
    assert _persisted_package(publication, second) == (root, manifest)
    assert tuple(path.name for path in root.parent.iterdir()) == (
        first.result.artifact_revision_id,
    )
    assert tuple(path.name for path in publication.settings.nas_artifact_root.iterdir()) == (
        first.result.artifact_id,
    )


class _PublicationStart(Protocol):
    def wait(self, timeout: float) -> int: ...


def _publish_in_spawned_owner(
    request: IncrementalEmbeddingInput,
    workflow_request: LocalEmbeddingWorkflowRequest,
    settings: Settings,
    workspace: Path,
    start: _PublicationStart,
) -> tuple[int, PublishedEmbeddingArtifacts]:
    explicit_url = os.environ.get("EOM_DATABASE_URL")
    if os.environ.get("EOM_RUN_INTEGRATION") != "1" or not explicit_url:
        raise AssertionError("spawned publication requires opt-in and an explicit disposable URL")
    # Inherit the already-authorized test URL; never resolve runtime secret fallback.
    engine = build_engine(explicit_url)
    try:
        # Reuse the exact existing manifest/owner/schema/head fixture guard in each
        # independent owner, rather than copying or weakening its authorization.
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
        ).publish(
            workflow_request=workflow_request,
            request=request,
            workspace=workspace,
            created_at=NOW,
        )
        return os.getpid(), receipt
    finally:
        engine.dispose()
