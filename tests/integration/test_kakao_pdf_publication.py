"""Disposable DB + local artifact storage, synthetic already-accepted PDF receipt.

Actual isolated rendering is tested separately. These cases test existing Catalog
commit/replay ownership, never production NAS or current private-source authority.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pymupdf
import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_pdf_publication import publish_kakao_pdf
from eom_kakao_archive_contracts import (
    LocalMember,
    RenderCommand,
    RenderResult,
    canonical_bytes,
    sha256,
    subset_sha256,
)
from eom_kakao_archive_contracts.layout import RenderLayoutReceipt
from eom_orchestrator.kakao_pdf_execution import AcceptedKakaoPdf
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_catalog_artifact_created_recovery import _settings

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def publication_case(creative_engine, tmp_path):
    def identity(kind):
        return f"kakao{kind}_{uuid4().hex}"

    output = tmp_path / "accepted"
    output.mkdir(mode=0o700)
    question_id = identity("questionrev")
    manifest = {
        "schema_version": "kakao-question-render-manifest/1.0",
        "source_binding_id": identity("binding"),
        "packet_revision_id": identity("packetrev"),
        "student_id": identity("student"),
        "student_display_name": "synthetic private student",
        "subset_sha256": subset_sha256((question_id,)),
        "mode": "FINAL",
        "questions": [
            {
                "question_revision_id": question_id,
                "header_date": "2026-11-16",
                "text_blocks": [{"span_id": "line-1", "text": "Example question"}],
                "images": [],
                "ordered_blocks": [{"kind": "TEXT", "span_id": "line-1"}],
            }
        ],
    }
    # Byte identity is independent of canonical model serialization.
    raw_manifest = b" \n" + canonical_bytes(manifest)
    command = RenderCommand.model_validate(
        {
            "schema_version": "kakao-question-render/1.0",
            "execution": {
                "command_id": identity("command"),
                "task_id": identity("task"),
                "attempt_id": identity("attempt"),
                "attempt_number": 1,
                "fence": 1,
            },
            "export_id": identity("export"),
            **{
                key: manifest[key]
                for key in (
                    "source_binding_id",
                    "packet_revision_id",
                    "student_id",
                    "subset_sha256",
                    "mode",
                )
            },
            "renderer_release_sha256": "sha256:" + "a" * 64,
            "layout_policy": "student-question-a4/1.0",
            "manifest": {
                "relative_path": "manifest.json",
                "sha256": sha256(raw_manifest),
                "size_bytes": len(raw_manifest),
                "media_type": "application/json",
            },
            "font": {
                "relative_path": "font.otf",
                "sha256": sha256(b"fixture-font"),
                "size_bytes": 12,
                "media_type": "font/otf",
            },
        }
    )
    command_hash = sha256(canonical_bytes(command.model_dump(mode="json")))
    layout = RenderLayoutReceipt.model_validate(
        {
            "schema_version": "kakao-question-layout-receipt/1.0",
            "command_sha256": command_hash,
            "manifest_sha256": command.manifest.sha256,
            "font_sha256": command.font.sha256,
            "layout_policy": command.layout_policy,
            "renderer_release_sha256": command.renderer_release_sha256,
            "mode": "FINAL",
            "pages": [
                {
                    "question_revision_id": question_id,
                    "page_number": 1,
                    "font_size_pt": 11.0,
                    "image_columns": 1,
                    "text_blocks": [
                        {
                            "span_id": "line-1",
                            "start_codepoint": 0,
                            "end_codepoint": 16,
                            "bounds_pt": [50.0, 100.0, 180.0, 120.0],
                        }
                    ],
                    "image_blocks": [],
                }
            ],
        }
    )
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((50, 111), "Example question", fontsize=11)
        payloads = {
            "report.pdf": (document.tobytes(), "application/pdf"),
            "page-0001.png": (page.get_pixmap().tobytes("png"), "image/png"),
            "layout.json": (canonical_bytes(layout.model_dump(mode="json")), "application/json"),
        }
    members = []
    for name, (raw, media) in payloads.items():
        path = output / name
        path.write_bytes(raw)
        path.chmod(0o640)
        members.append(
            LocalMember(
                relative_path=name, sha256=sha256(raw), size_bytes=len(raw), media_type=media
            )
        )
    result = RenderResult(
        schema_version="kakao-question-render-result/1.0",
        execution=command.execution,
        export_id=command.export_id,
        command_sha256=command_hash,
        manifest_sha256=command.manifest.sha256,
        status="COMPLETED",
        page_count=1,
        outputs=tuple(members),
        error_code=None,
        question_revision_id=None,
    )
    artifacts = CatalogArtifactService(creative_engine, _settings(tmp_path))
    return artifacts, dict(
        command=command,
        manifest_bytes=raw_manifest,
        accepted=AcceptedKakaoPdf(result, layout, result.outputs, output),
        authorize=lambda: None,
    )


def test_pdf_pointer_publication_has_no_binary_or_private_text_in_database(publication_case):
    artifacts, args = publication_case
    first = publish_kakao_pdf(artifacts, **args)
    second = publish_kakao_pdf(artifacts, **args)
    assert first == second
    with Session(artifacts.engine) as session:
        job = session.get(JobRecord, first.publication_job_id)
        revision = session.get(ArtifactRevisionRecord, first.pdf.artifact_revision_id)
        assert job.status == "SUCCEEDED"
        assert revision.job_id == job.job_id
        assert "Example question" not in repr(job.request)
        assert "synthetic private student" not in repr(job.request)
        assert b"%PDF" not in canonical_bytes(job.request)
        entries = {entry["file_name"]: entry for entry in revision.manifest["files"]}
        for pointer in (first.pdf, first.layout, *first.previews):
            assert entries[pointer.member_path]["sha256"] == pointer.sha256
            assert entries[pointer.member_path]["media_type"] == pointer.media_type
        assert (
            sum(
                1
                for _ in session.scalars(
                    select(ArtifactRevisionRecord).where(
                        ArtifactRevisionRecord.job_id == job.job_id
                    )
                )
            )
            == 1
        )


def test_pdf_concurrent_publication_is_one_job_revision(publication_case):
    artifacts, args = publication_case
    barrier = Barrier(3)

    def publish(_):
        barrier.wait(timeout=15)
        writer = CatalogArtifactService(artifacts.engine, artifacts.settings)
        return publish_kakao_pdf(writer, **args)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(publish, range(3)))
    assert results[0] == results[1] == results[2]
    with Session(artifacts.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == results[0].publication_job_id)
            )
            == 1
        )


def test_pdf_commit_followed_by_authority_loss_reuses_publication_without_rerender(
    publication_case,
):
    artifacts, args = publication_case
    original = args["authorize"]
    calls = 0

    def authorize():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PermissionError("synthetic postcommit revocation")

    args["authorize"] = authorize
    with pytest.raises(PermissionError):
        publish_kakao_pdf(artifacts, **args)
    with Session(artifacts.engine) as session:
        prior = tuple(
            session.scalars(select(JobRecord).where(JobRecord.task_type == "kakao-question-pdf"))
        )
        old_ids = {record.job_id for record in prior}
    args["authorize"] = original
    recovered = publish_kakao_pdf(artifacts, **args)
    assert recovered.publication_job_id in old_ids
    assert recovered == publish_kakao_pdf(artifacts, **args)
