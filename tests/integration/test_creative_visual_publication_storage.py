"""Crop Artifact commit/replay against a guarded disposable PostgreSQL database.

Source admission and role execution use synthetic inputs; this proves only the
real file-set owner concurrency and interruption boundary, not Graph acceptance.
PNG/PDF files are synthetic and all artifact storage is beneath tmp_path.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_orchestrator import creative_source_visual_publication as visual_owner
from eom_orchestrator import file_set_control_artifacts as artifact_owner
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit.test_creative_source_visual_publication import _case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _publisher(engine, tmp_path):
    staging, artifacts = tmp_path / "owner-staging", tmp_path / "artifact-store"
    staging.mkdir(mode=0o700)
    artifacts.mkdir(mode=0o700)
    return ControlFileSetPublisher(
        engine, Settings(staging_root=staging, nas_artifact_root=artifacts)
    )


def test_concurrent_creative_visual_publication_commits_one_exact_artifact(
    creative_engine, tmp_path, monkeypatch
):
    _, arguments, _, _, _ = _case(monkeypatch, tmp_path)
    monkeypatch.setattr(
        visual_owner, "resolve_control_artifact_member", resolve_control_artifact_member
    )
    publisher = _publisher(creative_engine, tmp_path)
    gate = Barrier(2)

    def publish(ordinal):
        gate.wait(timeout=10)
        return visual_owner.publish_creative_source_visuals(
            publisher, **{**arguments, "workspace": tmp_path / f"crop-{ordinal}"}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(publish, range(2)))
    assert all(result is not None for result in results)
    assert results[0].publication == results[1].publication
    published = results[0].publication
    with Session(creative_engine) as session:
        rows = tuple(
            session.scalars(
                select(JobRecord).where(JobRecord.revision_id == published.artifact_revision_id)
            )
        )
        assert len(rows) == 1 and rows[0].status == "SUCCEEDED"
    replay = visual_owner.publish_creative_source_visuals(
        publisher, **{**arguments, "workspace": tmp_path / "unused"}
    )
    assert replay.publication == published
    assert not (tmp_path / "unused").exists()


def test_interrupted_creative_visual_commit_resumes_original_job_and_revision(
    creative_engine, tmp_path, monkeypatch
):
    _, arguments, _, _, _ = _case(monkeypatch, tmp_path)
    # Include test identity in the existing immutable publication key. A separate
    # source revision is not invented to escape the first operation's failure.
    arguments["source_commit"] = "b" * 40
    monkeypatch.setattr(
        visual_owner, "resolve_control_artifact_member", resolve_control_artifact_member
    )
    publisher = _publisher(creative_engine, tmp_path)
    original_commit = artifact_owner.commit_file_set_artifact
    interrupted = Mock(side_effect=RuntimeError("synthetic pre-NAS interruption"))
    monkeypatch.setattr(artifact_owner, "commit_file_set_artifact", interrupted)
    with pytest.raises(RuntimeError, match="pre-NAS interruption"):
        visual_owner.publish_creative_source_visuals(publisher, **arguments)
    staged = interrupted.call_args.args[0]
    with Session(creative_engine) as session:
        original = session.get(JobRecord, staged.manifest["job_id"])
        assert original is not None and original.status == "COMMITTING"
        original_identity = original.job_id, original.logical_artifact_id, original.revision_id
    monkeypatch.setattr(artifact_owner, "commit_file_set_artifact", original_commit)
    completed = visual_owner.publish_creative_source_visuals(
        publisher, **{**arguments, "workspace": tmp_path / "resumed"}
    )
    assert (
        completed.publication.job_id,
        completed.publication.artifact_id,
        completed.publication.artifact_revision_id,
    ) == original_identity
    with Session(creative_engine) as session:
        assert session.get(JobRecord, original_identity[0]).status == "SUCCEEDED"
