"""Creative page derivatives use the existing Orchestrator file-set commit owner."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_identifiers import content_sha256
from eom_orchestrator.external_item_learning_page_publication import (
    external_item_learning_page_artifact,
    publish_external_item_learning_pages,
)
from eom_orchestrator.external_item_learning_page_render import (
    render_external_item_learning_pages,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    PublishedControlFileSet,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select

from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_external_item_learning_page_render import (
    _direct_fixture_runner,
    _pdf,
    _source_for_pdf,
)

pytestmark = pytest.mark.skipif(
    shutil.which("pdfinfo") is None or shutil.which("pdftoppm") is None,
    reason="Poppler tools are not installed",
)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish_first_observation(self, **kwargs: object) -> PublishedControlFileSet:
        self.calls.append(kwargs)
        return PublishedControlFileSet(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "3" * 32,
            primary_file="page-set-manifest.json",
            primary_sha256="sha256:" + "4" * 64,
            manifest_sha256="sha256:" + "5" * 64,
            nas_path="/mnt/nas/eom/artifacts/artifact_test/rev_test",
        )


def _rendered(tmp_path: Path):
    payload = _pdf()
    return render_external_item_learning_pages(
        _source_for_pdf(payload),
        payload,
        workspace=tmp_path / "creative-pages",
        run=_direct_fixture_runner,
    )


def test_publisher_commits_only_manifest_and_ordered_pngs(tmp_path: Path) -> None:
    rendered = _rendered(tmp_path)
    publisher = _RecordingPublisher()
    receipt = publish_external_item_learning_pages(publisher, rendered, source_commit="a" * 40)
    assert receipt.artifact_id == "artifact_" + "2" * 32
    call = publisher.calls[0]
    members = call["members"]
    assert isinstance(members, tuple)
    assert all(isinstance(member, ControlFileSetMember) for member in members)
    assert tuple(member.file_name for member in members) == (
        "page-set-manifest.json",
        "pages/page-0001.png",
    )
    assert all(member.file_name != "preview.pdf" for member in members)
    assert call["artifact_type"] == "control_external_item_learning_pages"
    assert call["source_commit"] == "a" * 40
    publish_external_item_learning_pages(publisher, rendered, source_commit="a" * 40)
    assert publisher.calls[1]["idempotency_key"] == call["idempotency_key"]


def test_publisher_rejects_tampered_manifest_before_commit(tmp_path: Path) -> None:
    rendered = _rendered(tmp_path)
    rendered.manifest_path.write_bytes(b"{}")
    publisher = _RecordingPublisher()
    with pytest.raises(ValueError, match="CREATIVE_PAGE_PUBLICATION_INPUT_INVALID"):
        publish_external_item_learning_pages(publisher, rendered, source_commit="a" * 40)
    assert publisher.calls == []


def test_real_publisher_commits_once_without_copying_source_pdf_to_artifact(
    tmp_path: Path,
) -> None:
    rendered = _rendered(tmp_path)
    publisher, _engine = _publisher(tmp_path)
    first = publish_external_item_learning_pages(publisher, rendered, source_commit="a" * 40)
    replayed = publish_external_item_learning_pages(publisher, rendered, source_commit="a" * 40)
    assert replayed == first
    pointer = external_item_learning_page_artifact(first)
    assert pointer.artifact_id == first.artifact_id
    assert pointer.sha256 == first.primary_sha256
    assert pointer.file_set_manifest_sha256 == first.manifest_sha256
    work: dict[str, object] = {
        "schema_version": "external-item-learning-work-input/1.0",
        "request_id": "extlearnreq_" + "f" * 32,
        "source": _source_for_pdf(_pdf()).model_dump(mode="json"),
        "page_set": rendered.manifest.model_dump(mode="json"),
        "page_artifact": pointer.model_dump(mode="json"),
    }
    work["request_sha256"] = content_sha256(work)
    assert ExternalItemLearningWorkInput.model_validate(work).source.external_number == "12345"
    artifact_root = Path(first.nas_path)
    assert (artifact_root / "page-set-manifest.json").read_bytes() == (
        rendered.manifest_path.read_bytes()
    )
    assert (artifact_root / "pages/page-0001.png").read_bytes() == (
        rendered.page_paths[0].read_bytes()
    )
    assert not (artifact_root / "preview.pdf").exists()
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
