from __future__ import annotations

import subprocess
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER,
    CreateDocumentReviewAnnotatedPdfs,
    CreateDocumentReviewAnnotatedPdfsV2,
    CreateDocumentReviewAnnotatedPdfsV4,
    CreateDocumentReviewAnnotatedPdfsV5,
    DocumentReviewAnnotationPage,
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationSource,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfPanelComment,
    DocumentReviewResultMemberPointer,
    DocumentReviewResultMemberPointerV2,
    PdfReviewArtifactMemberPointer,
)
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.document_review_pdf_annotation import (
    NativePanelCommentPayload,
    _readable_overlay_svg,
    annotate_pdf,
    annotate_pdf_with_native_comments,
)
from eom_catalog_service.document_review_pdf_annotation_service import (
    DocumentReviewPdfAnnotationService,
    DocumentReviewPdfAnnotationServiceError,
    _native_panel_comments,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_orchestrator.artifacts import stage_file_set_artifact
from eom_workflow import PdfDocumentReviewRoleResult, PdfDocumentReviewRoleResultV4


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


def test_native_panel_annotation_is_deterministic_and_carries_comment_text(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    pymupdf = import_module("pymupdf")
    pymupdf_native = import_module("pymupdf._extra")
    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation._pymupdf_runtime",
        lambda: (
            pymupdf,
            Path(str(pymupdf.__file__)),
            Path(str(pymupdf_native.__file__)),
        ),
    )
    source = _source_pdf(tmp_path)
    source_sha256 = sha256_file(source)
    mark = _marks()[0]
    contents = (
        "검토 #1 · 과학 표기 확인\n분류: TYPOGRAPHY\n중요도: MEDIUM\n\n"
        "문항의 표기를 확인해야 합니다.\n\n수정 권고 (VERIFY)\n원문과 대조하세요."
    )
    descriptor = DocumentReviewPdfPanelComment(
        comment_id="reviewcomment_" + "c" * 32,
        finding_id=mark.finding_id,
        anchor_id=mark.anchor_id,
        ordinal=mark.ordinal,
        document_role=mark.document_role,
        page_number=mark.page_number,
        contents_sha256=sha256_bytes(contents.encode("utf-8")),
        contents_utf8_length=len(contents.encode("utf-8")),
    )
    payload = NativePanelCommentPayload(
        descriptor=descriptor,
        contents=contents,
        region=mark.region,
    )
    first = tmp_path / "native-first.pdf"
    second = tmp_path / "native-second.pdf"

    identity = annotate_pdf_with_native_comments(
        source,
        first,
        role="DOCUMENT",
        page_count=2,
        annotations=(mark,),
        panel_comments=(payload,),
    )
    annotate_pdf_with_native_comments(
        source,
        second,
        role="DOCUMENT",
        page_count=2,
        annotations=(mark,),
        panel_comments=(payload,),
    )

    assert identity.renderer_key == "pymupdf-qpdf-rsvg-document-review-annotation"
    assert sha256_file(source) == source_sha256
    assert sha256_file(first) == sha256_file(second)
    document = pymupdf.open(str(first))
    try:
        page = document[0]
        annotations = tuple(page.annots() or ())
        assert len(annotations) == 1
        annotation = annotations[0]
        assert annotation.type[1] == "Square"
        assert annotation.info["id"] == descriptor.comment_id
        assert annotation.info["title"] == "EOM 문서 검토"
        assert annotation.info["subject"] == "검토 #1"
        assert annotation.info["content"] == contents
        assert tuple(document[1].annots() or ()) == ()
    finally:
        document.close()


def test_readable_pdf_has_one_number_and_native_comment_for_two_locations(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    pymupdf = import_module("pymupdf")
    pymupdf_native = import_module("pymupdf._extra")
    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation._pymupdf_runtime",
        lambda: (
            pymupdf,
            Path(str(pymupdf.__file__)),
            Path(str(pymupdf_native.__file__)),
        ),
    )
    source = _source_pdf(tmp_path)
    source_sha256 = sha256_file(source)
    first_mark = _marks()[0]
    second_mark = first_mark.model_copy(
        update={
            "anchor_id": "reviewanchor_" + "c" * 32,
            "region": DocumentReviewAnnotationRegion(
                x_ppm=100_000,
                y_ppm=20_000,
                width_ppm=300_000,
                height_ppm=60_000,
            ),
        }
    )
    marks = (first_mark, second_mark)
    finding = SimpleNamespace(
        finding_id=first_mark.finding_id,
        ordinal=1,
        category="TYPOGRAPHY",
        severity="HIGH",
        title="표기 수정",
        description="원문의 표기를 수정해야 합니다.",
        recommendation=SimpleNamespace(
            operation="REPLACE",
            instruction="표기를 바로잡으세요.",
            before_text="틀린 표기",
            after_text="바른 표기",
        ),
        anchors=(
            SimpleNamespace(anchor_id=first_mark.anchor_id, quote="주변 설명"),
            SimpleNamespace(anchor_id=second_mark.anchor_id, quote="틀린 표기"),
        ),
    )
    parsed = SimpleNamespace(output=SimpleNamespace(findings=(finding,)))
    comments = _native_panel_comments(
        cast(Any, parsed), marks, presentation_style="READABLE_MARGIN_GUIDES_V1"
    )
    assert len(comments) == 1
    assert comments[0].descriptor.anchor_id == second_mark.anchor_id
    assert "문서 1쪽" in comments[0].contents
    assert "해당 문구\n틀린 표기" in comments[0].contents
    svg = _readable_overlay_svg(595.0, 842.0, marks, frozenset({second_mark.anchor_id}), None)
    assert svg.count("<text ") == 1
    assert svg.count("<rect ") == 3  # two locations and one badge
    assert 'stroke="#4F46E5"' in svg
    assert 'fill-opacity="0.58"' in svg
    assert '#D70015' not in svg

    output = tmp_path / "readable.pdf"
    annotate_pdf_with_native_comments(
        source,
        output,
        role="DOCUMENT",
        page_count=2,
        annotations=marks,
        panel_comments=comments,
        presentation_style="READABLE_MARGIN_GUIDES_V1",
    )
    assert sha256_file(source) == source_sha256
    subprocess.run(["/usr/bin/qpdf", "--check", str(output)], check=True)
    document = pymupdf.open(str(output))
    try:
        native = tuple(document[0].annots() or ())
        assert len(native) == 1
        assert native[0].info["content"] == comments[0].contents
    finally:
        document.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_readable_comment_respects_rotated_cropped_page(
    tmp_path: Path,
    monkeypatch: Any,
    rotation: int,
) -> None:
    pymupdf = import_module("pymupdf")
    pymupdf_native = import_module("pymupdf._extra")
    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation._pymupdf_runtime",
        lambda: (pymupdf, Path(str(pymupdf.__file__)), Path(str(pymupdf_native.__file__))),
    )
    base = _source_pdf(tmp_path)
    source = tmp_path / "rotated-cropped.pdf"
    document = pymupdf.open(str(base))
    try:
        document[0].set_cropbox(pymupdf.Rect(40, 50, 550, 790))
        document[0].set_rotation(rotation)
        document.save(str(source))
    finally:
        document.close()
    mark = _marks()[0]
    contents = "검토 #1\n문서 1쪽\n수정 권고"
    descriptor = DocumentReviewPdfPanelComment(
        comment_id="reviewcomment_" + "d" * 32,
        finding_id=mark.finding_id,
        anchor_id=mark.anchor_id,
        ordinal=mark.ordinal,
        document_role=mark.document_role,
        page_number=1,
        contents_sha256=sha256_bytes(contents.encode("utf-8")),
        contents_utf8_length=len(contents.encode("utf-8")),
    )
    output = tmp_path / "rotated-cropped-annotated.pdf"
    annotate_pdf_with_native_comments(
        source,
        output,
        role="DOCUMENT",
        page_count=2,
        annotations=(mark,),
        panel_comments=(NativePanelCommentPayload(descriptor, contents, mark.region),),
        presentation_style="READABLE_MARGIN_GUIDES_V1",
    )
    result = pymupdf.open(str(output))
    try:
        assert result[0].rotation == rotation
        assert next(iter(result[0].annots() or ())).info["content"] == contents
        pixmap = result[0].get_pixmap(annots=False)
        brand_pixels = [
            (x, y)
            for y in range(pixmap.height)
            for x in range(pixmap.width)
            if (
                pixmap.samples[y * pixmap.stride + x * pixmap.n] < 180
                and pixmap.samples[y * pixmap.stride + x * pixmap.n + 1] < 170
                and pixmap.samples[y * pixmap.stride + x * pixmap.n + 2] > 190
            )
        ]
        assert brand_pixels
        expected_x = 0.4 * result[0].rect.width
        expected_y = 0.16 * result[0].rect.height
        assert any(abs(x - expected_x) <= 3 and abs(y - expected_y) <= 5 for x, y in brand_pixels)
    finally:
        result.close()


class _StructuredResultArtifacts:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def load_json_revision(self, **values: object) -> dict[str, object]:
        self.calls.append(values)
        return self.result

    def read_member(self, **_values: object) -> bytes:
        raise AssertionError("structured role results must not use the file-set member resolver")


@pytest.mark.parametrize(
    ("schema_ref", "expected_result_schema"),
    [
        (
            "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
            "pdf-document-review-result@1.0",
        ),
        (
            "https://eom.local/schemas/workflow/roles/paired-document-review-result-v2.schema.json",
            "pdf-document-review-result@2.0",
        ),
        (
            "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v4.schema.json",
            "pdf-document-review-result@4.0",
        ),
    ],
)
def test_annotation_resolves_orchestrator_role_result_as_structured_artifact(
    monkeypatch: Any,
    schema_ref: str,
    expected_result_schema: str,
) -> None:
    raw: dict[str, object] = {"schema_version": "test/1.0", "status": "ok"}
    digest = content_sha256(raw)
    pointer = DocumentReviewResultMemberPointerV2(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id="rev_" + "d" * 32,
        sha256=digest,
        content_length=len(canonical_json_bytes(raw)),
        schema_ref=cast(Any, schema_ref),
    )
    command = cast(
        CreateDocumentReviewAnnotatedPdfs,
        SimpleNamespace(
            workflow_id="workflow_" + "9" * 32,
            review_result=pointer,
        ),
    )
    parsed = PdfDocumentReviewRoleResult.model_construct(workflow_id=command.workflow_id)
    artifacts = _StructuredResultArtifacts(raw)
    service = object.__new__(DocumentReviewPdfAnnotationService)
    service.artifacts = cast(Any, artifacts)
    validated_schemas: list[str] = []

    def validate_result(_raw: object, _role: str, result_schema: str) -> object:
        validated_schemas.append(result_schema)
        return parsed

    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation_service.validate_role_result",
        validate_result,
    )

    assert service._validated_result(command) is parsed
    assert artifacts.calls == [
        {
            "artifact_id": pointer.artifact_id,
            "revision_id": pointer.artifact_revision_id,
            "content_hash": pointer.sha256,
            "max_bytes": 16 * 1024 * 1024,
        }
    ]
    assert validated_schemas == [expected_result_schema]


def test_annotation_rejects_structured_result_pointer_length_mismatch(
    monkeypatch: Any,
) -> None:
    raw: dict[str, object] = {"schema_version": "test/1.0", "status": "ok"}
    pointer = DocumentReviewResultMemberPointer(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id="rev_" + "d" * 32,
        sha256=content_sha256(raw),
        content_length=len(canonical_json_bytes(raw)) + 1,
        schema_ref=(
            "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
        ),
    )
    command = cast(
        CreateDocumentReviewAnnotatedPdfs,
        SimpleNamespace(
            workflow_id="workflow_" + "9" * 32,
            review_result=pointer,
        ),
    )
    service = object.__new__(DocumentReviewPdfAnnotationService)
    service.artifacts = cast(Any, _StructuredResultArtifacts(raw))
    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation_service.validate_role_result",
        lambda *_args: AssertionError("validation must not run after a pointer mismatch"),
    )

    with pytest.raises(DocumentReviewPdfAnnotationServiceError) as raised:
        service._validated_result(command)

    assert raised.value.code == "DOCUMENT_REVIEW_ANNOTATION_POINTER_INVALID"


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
        stage_file_set_artifact(
            files=files,
            primary_file=values["primary_file"],
            job_id="job_" + "1" * 32,
            logical_artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            artifact_type=values["artifact_type"],
            staging=files[values["primary_file"]].parent / "real-artifact-stage",
            manifest_version=values["manifest_version"],
            file_metadata=values["file_metadata"],
        )
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
    assert response.manifest.member_path == DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER
    assert response.manifest.sha256 == sha256_bytes(
        artifacts.committed[DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER]
    )
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


@pytest.mark.parametrize(
    ("target_aware", "readable"),
    [(False, False), (True, False), (True, True)],
)
def test_catalog_native_panel_service_commits_v2_receipt_and_pdf_comments(
    tmp_path: Path,
    monkeypatch: Any,
    target_aware: bool,
    readable: bool,
) -> None:
    pymupdf = import_module("pymupdf")
    pymupdf_native = import_module("pymupdf._extra")
    monkeypatch.setattr(
        "eom_catalog_service.document_review_pdf_annotation._pymupdf_runtime",
        lambda: (
            pymupdf,
            Path(str(pymupdf.__file__)),
            Path(str(pymupdf_native.__file__)),
        ),
    )
    source_path = _source_pdf(tmp_path)
    source = _annotation_source(source_path)
    annotation = (_marks()[0],)
    payload: dict[str, Any] = {
        "schema_version": (
            "document-review-pdf-annotation-request/5.0"
            if readable
            else "document-review-pdf-annotation-request/4.0"
            if target_aware
            else "document-review-pdf-annotation-request/2.0"
        ),
        "operation": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2",
        "annotation_profile": "NUMBERED_BOXES_WITH_NATIVE_COMMENTS",
        "actor_id": "operator_test",
        "idempotency_key": "native-annotation-service-test",
        "workflow_id": "workflow_" + "9" * 32,
        "review_result": DocumentReviewResultMemberPointerV2(
            artifact_id="artifact_" + "c" * 32,
            artifact_revision_id="rev_" + "d" * 32,
            sha256="sha256:" + "e" * 64,
            content_length=100,
            schema_ref=(
                "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v4.schema.json"
                if target_aware
                else "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
            ),
        ),
        "sources": (source,),
        "annotations": annotation,
        "annotation_set_sha256": content_sha256(
            [value.model_dump(mode="json") for value in annotation]
        ),
    }
    if readable:
        payload["presentation_style"] = "READABLE_MARGIN_GUIDES_V1"
    payload["request_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "idempotency_key"}
    )
    command_model = (
        CreateDocumentReviewAnnotatedPdfsV5
        if readable
        else CreateDocumentReviewAnnotatedPdfsV4
        if target_aware
        else CreateDocumentReviewAnnotatedPdfsV2
    )
    command = command_model.model_validate(payload)
    mark = annotation[0]
    finding = SimpleNamespace(
        finding_id=mark.finding_id,
        ordinal=mark.ordinal,
        category="TYPOGRAPHY",
        severity="MEDIUM",
        title="과학 표기 확인",
        description="문항의 표기를 원문과 대조해야 합니다.",
        recommendation=SimpleNamespace(
            operation="VERIFY",
            instruction="원문과 대조하세요.",
            before_text=None,
            after_text=None,
        ),
        anchors=(
            SimpleNamespace(
                anchor_id=mark.anchor_id,
                page_number=mark.page_number,
                page_image_sha256=mark.page_image_sha256,
                region=mark.region,
                quote=None,
            ),
        ),
    )
    result_model = PdfDocumentReviewRoleResultV4 if target_aware else PdfDocumentReviewRoleResult
    parsed = result_model.model_construct(
        workflow_id=command.workflow_id,
        output=SimpleNamespace(
            document_id=source.document_id,
            document_revision_id=source.document_revision_id,
            source_pdf_sha256=source.source_pdf.sha256,
            findings=(finding,),
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

    assert response.schema_version == (
        "document-review-pdf-annotation-response/3.0"
        if readable
        else "document-review-pdf-annotation-response/2.0"
    )
    assert response.result is not None
    assert response.result.panel_comment_count == 1
    assert response.manifest is not None
    assert response.manifest.schema_ref.endswith(
        "annotation-manifest/3.0" if readable else "annotation-manifest/2.0"
    )
    commit = artifacts.commit_calls[0]
    assert commit["protocol_version"] == (
        "catalog/1.24" if readable else "catalog/1.23" if target_aware else "catalog/1.21"
    )
    assert commit["manifest_version"] == (
        "document-review-pdf-annotation-file-set/3.0"
        if readable
        else "document-review-pdf-annotation-file-set/2.0"
    )
    document = pymupdf.open(stream=artifacts.committed["annotated/document.pdf"], filetype="pdf")
    try:
        page = document[0]
        native = tuple(page.annots() or ())
        assert len(native) == 1
        assert native[0].info["subject"] == "검토 #1"
        assert "원문과 대조하세요." in native[0].info["content"]
    finally:
        document.close()
