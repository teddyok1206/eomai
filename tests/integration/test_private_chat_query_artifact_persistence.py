"""Guarded disposable PostgreSQL only; source, launch and numerical seams are synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE,
    EmbeddingArtifactStore,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_artifact_store import SOURCE_COMMIT
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import prepare, write_member

pytestmark = pytest.mark.integration


@pytest.fixture
def publication(guarded_engine: Engine, tmp_path: Path):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    value = prepare(tmp_path)
    identity = ControlFileSetIdentity(
        "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    launch = value.arguments["launch"].model_dump(mode="json") | {
        "workflow_id": "workflow_" + uuid4().hex,
        "step_run_id": "steprun_" + uuid4().hex,
        "original_command_id": "wfcmd_" + uuid4().hex,
    }
    value.arguments["launch"] = PrivateChatQueryLaunchAssociation.model_validate(
        seal(launch, "association_sha256")
    )
    value.arguments["identity"] = identity
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "local-artifacts",
        workspace_root=tmp_path / "workspaces",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(guarded_engine, settings)
    value.store = EmbeddingArtifactStore(publisher, source_commit=SOURCE_COMMIT)
    return value, publisher


def assert_one_text_free_committed_result(value, publisher):
    identity = value.arguments["identity"]
    with Session(publisher.engine) as session:
        job = session.get(JobRecord, identity.job_id)
        artifact = session.get(ArtifactRecord, identity.artifact_id)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        assert job is not None and job.status == "SUCCEEDED"
        assert (
            artifact is not None
            and artifact.artifact_type == EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE
        )
        assert revision is not None and revision.job_id == identity.job_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == identity.job_id)
            )
            == 1
        )
        assert TEXT not in canonical_json_bytes(job.request).decode()
        assert TEXT not in canonical_json_bytes(revision.manifest).decode()
        assert TEXT not in canonical_json_bytes(revision.result).decode()
        root = Path(revision.nas_path)
        assert root.is_relative_to(publisher.settings.nas_artifact_root)
        assert not (root / "input.json").exists()
        assert tuple(v["file_name"] for v in revision.manifest["files"]) == (
            "intent.json",
            "result.json",
            "shard.json",
            "vectors.f32",
        )
        for member in revision.manifest["files"]:
            assert TEXT.encode() not in (root / member["file_name"]).read_bytes()
        return revision.manifest_hash


def test_private_result_persists_one_canonical_file_set_and_replays(publication):
    value, publisher = publication
    result = value.store.publish_private_chat_query(**value.arguments)
    before = assert_one_text_free_committed_result(value, publisher)
    assert value.store.publish_private_chat_query(**value.arguments) == result
    assert assert_one_text_free_committed_result(value, publisher) == before


def test_two_current_publishers_same_identity_commit_only_once(publication, tmp_path):
    value, publisher = publication
    second = tmp_path / "second-materialization"
    second.mkdir(mode=0o700)
    for name in ("input.json", "result.json", "vectors.f32"):
        write_member(second / name, (value.workspace / name).read_bytes())
    barrier = Barrier(2)

    def publish(workspace):
        barrier.wait(timeout=15)
        return value.store.publish_private_chat_query(
            **(value.arguments | {"workspace": workspace})
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(publish, workspace) for workspace in (value.workspace, second)]
        results = [job.result(timeout=30) for job in jobs]
    assert results[0] == results[1]
    assert_one_text_free_committed_result(value, publisher)


def test_late_unknown_outcome_preserves_original_commit_for_exact_replay(publication, monkeypatch):
    value, publisher = publication
    original = publisher.publish_identified

    def unknown(**kwargs):
        original(**kwargs)
        raise RuntimeError("synthetic observation lost after commit")

    monkeypatch.setattr(publisher, "publish_identified", unknown)
    with pytest.raises(RuntimeError, match="after commit"):
        value.store.publish_private_chat_query(**value.arguments)
    committed = assert_one_text_free_committed_result(value, publisher)
    monkeypatch.setattr(publisher, "publish_identified", original)
    value.store.publish_private_chat_query(**value.arguments)
    assert assert_one_text_free_committed_result(value, publisher) == committed


def test_same_original_key_cannot_change_publication_time(publication):
    value, publisher = publication
    value.store.publish_private_chat_query(**value.arguments)
    committed = assert_one_text_free_committed_result(value, publisher)
    changed = value.arguments | {"created_at": value.arguments["created_at"] + timedelta(seconds=1)}
    with pytest.raises(ControlPlaneError):
        value.store.publish_private_chat_query(**changed)
    assert assert_one_text_free_committed_result(value, publisher) == committed
