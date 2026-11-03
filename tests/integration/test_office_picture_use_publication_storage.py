"""Native picture publication interrupted, concurrently resumed and replayed in a guarded DB."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_orchestrator import file_set_control_artifacts as artifact_owner
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.office_picture_use_publication import (
    publish_office_picture_catalog,
    resolve_office_source_images,
)
from eom_orchestrator.settings import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit.test_office_picture_use_publication import publication_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_native_input_interrupt_concurrent_resume_and_registration_reuse(
    creative_engine, tmp_path, monkeypatch
):
    work, result, _catalog, bindings, extracted = publication_case(tmp_path)
    staging, artifacts = tmp_path / "owner-staging", tmp_path / "artifact-store"
    staging.mkdir(mode=0o700)
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        creative_engine, Settings(staging_root=staging, nas_artifact_root=artifacts)
    )
    original_commit = artifact_owner.commit_file_set_artifact
    interrupted = Mock(side_effect=RuntimeError("synthetic pre-commit interruption"))
    monkeypatch.setattr(artifact_owner, "commit_file_set_artifact", interrupted)
    arguments = dict(source_commit="a" * 40, authorize_source=Mock())
    with pytest.raises(RuntimeError, match="pre-commit interruption"):
        publish_office_picture_catalog(publisher, extracted, **arguments)
    staged = interrupted.call_args.args[0]
    with Session(creative_engine) as session:
        original = session.get(JobRecord, staged.manifest["job_id"])
        assert original is not None and original.status == "COMMITTING"
        identity = original.job_id, original.logical_artifact_id, original.revision_id
    monkeypatch.setattr(artifact_owner, "commit_file_set_artifact", original_commit)
    gate = Barrier(2)

    def resume(_ordinal):
        gate.wait(timeout=10)
        return publish_office_picture_catalog(publisher, extracted, **arguments)

    with ThreadPoolExecutor(max_workers=2) as executor:
        resumed = tuple(executor.map(resume, range(2)))
    assert resumed[0] == resumed[1]
    artifact = resumed[0]
    assert (artifact.artifact_id, artifact.artifact_revision_id) == identity[1:]
    replay = publish_office_picture_catalog(
        publisher, extracted, **{**arguments, "source_commit": "b" * 40}
    )
    assert replay == artifact
    with Session(creative_engine) as session:
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.revision_id == identity[2])))
        assert len(jobs) == 1 and jobs[0].job_id == identity[0] and jobs[0].status == "SUCCEEDED"
    updated_work = work.model_dump(mode="json", exclude={"request_sha256"})
    updated_work["office_artifact"] = artifact.model_dump(mode="json")
    from eom_catalog_contracts.office_item_learning import OfficeItemLearningWorkInput
    from eom_identifiers import content_sha256

    exact_work = OfficeItemLearningWorkInput.model_validate(
        {**updated_work, "request_sha256": content_sha256(updated_work)}
    )
    images = resolve_office_source_images(
        publisher, work=exact_work, result=result, selection=bindings
    )
    image = next(iter(images.values()))
    assert image.artifact.artifact_id == artifact.artifact_id
    assert image.artifact.artifact_revision_id == artifact.artifact_revision_id
    assert (artifacts / artifact.artifact_id / artifact.artifact_revision_id).is_dir()
    # Intake and registered Item refer to the same original member. No new crop Artifact is made.
    assert len(tuple(artifacts.iterdir())) == 1
