from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from eom_catalog_contracts import (
    CreateDocumentReviewAnnotatedPdfs,
    DocumentReviewAnnotationPage,
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationSource,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewResultMemberPointer,
    PdfReviewArtifactMemberPointer,
)
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.document_review_pdf_annotation import annotate_pdf
from eom_catalog_service.document_review_pdf_annotation_service import (
    DocumentReviewPdfAnnotationService,
)
from eom_identifiers import content_sha256, sha256_bytes, sha256_file
from eom_workflow import PdfDocumentReviewRoleResult


def _source_pdf(tmp_path: Path) -> Path:
    page_pdfs: list[Path] = []
    for page_number in (1, 2):
        svg = tmp_path / f"source-{page_number}.svg"
        pdf = tmp_path / f"source-{page_number}.pdf"
        svg.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="595pt" height="842pt">'
                f'<text x="50" y="80">page {page_number}</text></svg>'
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["/usr/bin/rsvg-convert", "--format=pdf", f"--output={pdf}", str(svg)],
            check=True,
        )
        page_pdfs.append(pdf)
    source = tmp_path / "source.pdf"
    subprocess.run(
        [
            "/usr/bin/qpdf",
            "--empty",
            "--pages",
            str(page_pdfs[0]),
            "1",
            str(page_pdfs[1]),
            "1",
            "--",
            str(source),
        ],
        check=True,
    )
    return source


def _marks() -> tuple[DocumentReviewPdfAnnotationMark, ...]:
    return (
        DocumentReviewPdfAnnotationMark(
            finding_id=f"reviewfinding_{'a' * 32}",
            anchor_id=f"reviewanchor_{'a' * 32}",
            ordinal=1,
            document_role="DOCUMENT",
            page_number=1,
            page_image_sha256=f"sha256:{'a' * 64}",
            region=DocumentReviewAnnotationRegion(
                x_ppm=100_000,
                y_ppm=100_000,
                width_ppm=300_000,
                height_ppm=120_000,
            ),
        ),
        DocumentReviewPdfAnnotationMark(
            finding_id=f"reviewfinding_{'b' * 32}",
            anchor_id=f"reviewanchor_{'b' * 32}",
            ordinal=2,
            document_role="DOCUMENT",
            page_number=2,
            page_image_sha256=f"sha256:{'b' * 64}",
            region=DocumentReviewAnnotationRegion(
                x_ppm=200_000,
                y_ppm=250_000,
                width_ppm=250_000,
                height_ppm=100_000,
            ),
        ),
    )


def test_annotation_is_deterministic_and_preserves_source(tmp_path: Path) -> None:
    source = _source_pdf(tmp_path)
    source_sha256 = sha256_file(source)
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"

    identity = annotate_pdf(
        source,
        first,
        role="DOCUMENT",
        page_count=2,
        annotations=_marks(),
    )
    annotate_pdf(
        source,
        second,
        role="DOCUMENT",
        page_count=2,
        annotations=_marks(),
    )

    assert identity.stroke_color == "#D70015"
    assert sha256_file(source) == source_sha256
    assert sha256_file(first) == sha256_file(second)
    assert sha256_file(first) != source_sha256
    subprocess.run(["/usr/bin/qpdf", "--check", str(first)], check=True)


class _Artifacts:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.committed: dict[str, bytes] = {}
        self.commit_calls: list[dict[str, Any]] = []

    def read_member(self, **values: Any) -> bytes:
        member_path = values["member_path"]
        if member_path == "source/original.pdf":
            return self.source
        if member_path == "result.json":
            return b"{}"
        return self.committed[member_path]

    def commit_file_set(self, **values: Any) -> CatalogArtifact:
        self.commit_calls.append(values)
        files = values["files"]
        expected = values["expected_file_sha256"]
        self.committed = {name: path.read_bytes() for name, path in files.items()}
        assert {name: sha256_bytes(payload) for name, payload in self.committed.items()} == expected
        return CatalogArtifact(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash=expected["result.json"],
            manifest_hash="sha256:" + "4" * 64,
            content_bytes=len(self.committed["result.json"]),
            nas_path="/immutable/test",
            manifest={},
        )


def _annotation_source(source_path: Path) -> DocumentReviewAnnotationSource:
    artifact_id = "artifact_" + "5" * 32
    revision_id = "rev_" + "6" * 32

    def pointer(path: str, sha256: str, media_type: str, schema_ref: str) -> Any:
        return PdfReviewArtifactMemberPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path=path,
            sha256=sha256,
            content_length=source_path.stat().st_size,
            media_type=media_type,
            schema_ref=schema_ref,
        )

    return DocumentReviewAnnotationSource(
        role="DOCUMENT",
        document_id="document_" + "7" * 32,
        document_revision_id="documentrev_" + "8" * 32,
        source_pdf=pointer(
            "source/original.pdf",
            sha256_file(source_path),
            "application/pdf",
            "eom://schemas/document-review/pdf-source/1.0",
        ),
        page_count=2,
        pages=(
            DocumentReviewAnnotationPage(
                page_number=1,
                page_image=pointer(
                    "pages/page-0001.png",
                    "sha256:" + "a" * 64,
                    "image/png",
                    "eom://schemas/document-review/pdf-page-render/1.0",
                ),
            ),
            DocumentReviewAnnotationPage(
                page_number=2,
                page_image=pointer(
                    "pages/page-0002.png",
                    "sha256:" + "b" * 64,
                    "image/png",
                    "eom://schemas/document-review/pdf-page-render/1.0",
                ),
            ),
        ),
    )


def test_catalog_annotation_service_commits_byte_and_semantic_hashes_separately(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    source_path = _source_pdf(tmp_path)
    source = _annotation_source(source_path)
    annotations = _marks()
    payload: dict[str, Any] = {
        "schema_version": "document-review-pdf-annotation-request/1.0",
        "operation": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS",
        "actor_id": "operator_test",
        "idempotency_key": "annotation-service-test",
        "workflow_id": "workflow_" + "9" * 32,
        "review_result": DocumentReviewResultMemberPointer(
            artifact_id="artifact_" + "c" * 32,
            artifact_revision_id="rev_" + "d" * 32,
            sha256="sha256:" + "e" * 64,
            content_length=100,
            schema_ref=(
                "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
            ),
        ),
        "sources": (source,),
        "annotations": annotations,
        "annotation_set_sha256": content_sha256(
            [value.model_dump(mode="json") for value in annotations]
        ),
    }
    payload["request_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "idempotency_key"}
    )
    command = CreateDocumentReviewAnnotatedPdfs.model_validate(payload)
    findings = tuple(
        SimpleNamespace(
            finding_id=mark.finding_id,
            ordinal=mark.ordinal,
            anchors=(
                SimpleNamespace(
                    anchor_id=mark.anchor_id,
                    page_number=mark.page_number,
                    page_image_sha256=mark.page_image_sha256,
                    region=mark.region,
                ),
            ),
        )
        for mark in annotations
    )
    parsed = PdfDocumentReviewRoleResult.model_construct(
        workflow_id=command.workflow_id,
        output=SimpleNamespace(
            document_id=source.document_id,
            document_revision_id=source.document_revision_id,
            source_pdf_sha256=source.source_pdf.sha256,
            findings=findings,
        ),
    )
    artifacts = _Artifacts(source_path.read_bytes())
    service = cast(
        DocumentReviewPdfAnnotationService, object.__new__(DocumentReviewPdfAnnotationService)
    )
    service.settings = SimpleNamespace(staging_root=tmp_path)
    service.artifacts = cast(Any, artifacts)
    monkeypatch.setattr(service, "_validated_result", lambda _: parsed)

    response = service.create(command)
    replay_payload = command.model_dump(mode="json")
    replay_payload["idempotency_key"] = "annotation-service-replay"
    replay = service.create(CreateDocumentReviewAnnotatedPdfs.model_validate(replay_payload))

    assert response.manifest is not None
    assert response.result is not None
    assert response.manifest.sha256 == sha256_bytes(artifacts.committed["manifest.json"])
    assert response.manifest.sha256 != response.result.manifest_sha256
    assert response.outputs is not None
    assert response.outputs[0].sha256 == sha256_bytes(artifacts.committed["annotated/document.pdf"])
    assert replay.result is not None
    assert replay.result.annotation_id == response.result.annotation_id
    assert len(artifacts.commit_calls) == 2
    assert {value["idempotency_key"] for value in artifacts.commit_calls} == {
        f"document-review-pdf-annotation:{command.request_sha256}"
    }
    assert all("idempotency_key" not in value["request"] for value in artifacts.commit_calls)
