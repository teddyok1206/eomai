"""Rendition interruption and concurrent replay use a guarded disposable database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_orchestrator import file_set_control_artifacts as artifact_owner
from eom_orchestrator.creative_visual_presentation_publication import (
    publish_creative_visual_presentation,
)
from eom_orchestrator.models import JobRecord
from sqlalchemy.orm import Session

from tests.integration.test_creative_visual_publication_storage import _publisher
from tests.unit.test_creative_visual_presentation_publication import publication_fixture

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_concurrent_original_image_renditions_commit_one_identified_revision(
    creative_engine, tmp_path
):
    arguments = publication_fixture(tmp_path)
    publisher = _publisher(creative_engine, tmp_path)
    barrier = Barrier(2)

    def publish(_ordinal):
        barrier.wait(timeout=10)
        return publish_creative_visual_presentation(publisher, **arguments)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(publish, range(2)))
    assert results[0] == results[1]
    assert results[0].artifact_revision_id == arguments["identity"].artifact_revision_id
    replay = publish_creative_visual_presentation(publisher, **arguments)
    assert replay == results[0]


def test_interrupted_original_image_rendition_resumes_the_same_identity(
    creative_engine, tmp_path, monkeypatch
):
    arguments = publication_fixture(tmp_path, variant="6")
    identity = arguments["identity"]
    publisher = _publisher(creative_engine, tmp_path)
    original = artifact_owner.commit_file_set_artifact
    monkeypatch.setattr(
        artifact_owner,
        "commit_file_set_artifact",
        Mock(side_effect=RuntimeError("synthetic interrupted original-image commit")),
    )
    with pytest.raises(RuntimeError, match="synthetic interrupted"):
        publish_creative_visual_presentation(publisher, **arguments)
    with Session(creative_engine) as session:
        assert session.get(JobRecord, identity.job_id).status == "COMMITTING"
    monkeypatch.setattr(artifact_owner, "commit_file_set_artifact", original)
    result = publish_creative_visual_presentation(publisher, **arguments)
    assert result.job_id == identity.job_id
    assert result.artifact_revision_id == identity.artifact_revision_id
    with Session(creative_engine) as session:
        assert session.get(JobRecord, identity.job_id).status == "SUCCEEDED"
