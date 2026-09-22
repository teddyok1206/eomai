from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import PdfDocumentReviewIntakeManifest, validate_contract
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.pdf_document_review_intake import (
    PdfDocumentReviewIntakeError,
    PdfDocumentReviewIntakeService,
    PdfReviewArtifactCommitter,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]


def _png(width: int = 1200, height: int = 1800) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


class _ArtifactRecorder:
    values: dict[str, Any] | None = None
    document_manifest: dict[str, object] | None = None
    mismatch: bool = False

    def commit_file_set(self, **values: Any) -> CatalogArtifact:
        self.values = values
        expected = cast(dict[str, str], values["expected_file_sha256"])
        for member, path in cast(dict[str, Path], values["files"]).items():
            assert path.is_file(), member
        manifest_path = cast(dict[str, Path], values["files"])["document-manifest.json"]
        loaded: object = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        self.document_manifest = loaded
        committed_hashes = dict(expected)
        if self.mismatch:
            committed_hashes["source/original.pdf"] = "sha256:" + "f" * 64
        return CatalogArtifact(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash=expected["document-manifest.json"],
            manifest_hash="sha256:" + "4" * 64,
            content_bytes=1,
            nas_path="/non-live/artifact",
            manifest={
                "files": [
                    {"file_name": member, "sha256": sha256}
                    for member, sha256 in sorted(committed_hashes.items())
                ]
            },
        )


def _service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    PdfDocumentReviewIntakeService,
    _ArtifactRecorder,
]:
    pdfinfo = tmp_path / "pdfinfo"
    pdftoppm = tmp_path / "pdftoppm"
    pdfinfo.write_bytes(b"fixed-pdfinfo")
    pdftoppm.write_bytes(b"fixed-pdftoppm")
    monkeypatch.setattr(
        "eom_catalog_service.pdf_document_review_intake._require_executable",
        lambda value: value,
    )

    def run(arguments: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[bytes]:
        assert timeout_seconds > 0
        if arguments[0] == str(pdfinfo):
            return subprocess.CompletedProcess(arguments, 0, b"Pages: 2\nEncrypted: no\n", b"")
        Path(arguments[-1] + ".png").write_bytes(_png())
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr("eom_catalog_service.pdf_document_review_intake._run", run)
    settings = CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "nas",
        intake_root=tmp_path / "intake",
    )
    settings.staging_root.mkdir()
    service = PdfDocumentReviewIntakeService(
        create_engine("sqlite+pysqlite:///:memory:"),
        settings,
        pdfinfo=pdfinfo,
        pdftoppm=pdftoppm,
    )
    recorder = _ArtifactRecorder()
    service.artifacts = cast(PdfReviewArtifactCommitter, recorder)
    return service, recorder


def test_pdf_document_review_intake_schema_mirror_and_model() -> None:
    canonical = ROOT / "schemas/document-review/pdf-document-review-intake-manifest-v1.schema.json"
    packaged = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/document-review"
        / canonical.name
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


def test_pdf_document_review_intake_commits_original_and_ordered_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / "uploaded.pdf"
    source.write_bytes(b"%PDF-1.7\nimmutable-source\n%%EOF\n")

    pointer = service.ingest(
        source,
        original_filename="9월_모의고사.pdf",
        actor_id="operator_" + "a" * 32,
        idempotency_key="api:document-review:fixed",
    )

    assert pointer.source_pdf.sha256.startswith("sha256:")
    assert pointer.page_count == 2
    assert tuple(page.page_number for page in pointer.pages) == (1, 2)
    assert tuple(page.page_image.member_path for page in pointer.pages) == (
        "pages/page-0001.png",
        "pages/page-0002.png",
    )
    assert recorder.values is not None
    assert recorder.values["protocol_version"] == "catalog/1.16"
    assert recorder.values["artifact_type"] == "pdf-document-review-source"
    assert not any(
        isinstance(value, bytes)
        for container in (recorder.values["request"], recorder.values["result"])
        for value in cast(dict[str, object], container).values()
    )
    assert set(recorder.values["files"]) == {
        "document-manifest.json",
        "source/original.pdf",
        "pages/page-0001.png",
        "pages/page-0002.png",
    }
    assert recorder.document_manifest is not None
    raw_manifest = recorder.document_manifest
    validate_contract("pdf-document-review-intake-manifest", raw_manifest)
    manifest = PdfDocumentReviewIntakeManifest.model_validate(raw_manifest)
    assert manifest.manifest_sha256 == content_sha256(
        manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    )
    assert source.read_bytes() == b"%PDF-1.7\nimmutable-source\n%%EOF\n"
    assert list(service.settings.staging_root.iterdir()) == []


def test_pdf_document_review_intake_rejects_conflicting_artifact_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    recorder.mismatch = True
    source = tmp_path / "uploaded.pdf"
    source.write_bytes(b"%PDF-2.0\nimmutable-source\n%%EOF\n")

    with pytest.raises(PdfDocumentReviewIntakeError) as error:
        service.ingest(
            source,
            original_filename="N제.pdf",
            actor_id="operator_" + "a" * 32,
            idempotency_key="api:document-review:conflict",
        )

    assert error.value.code == "PDF_DOCUMENT_REVIEW_ARTIFACT_REPLAY_MISMATCH"
    assert list(service.settings.staging_root.iterdir()) == []


def test_pdf_document_review_intake_rejects_non_pdf_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / "not-a-pdf.pdf"
    source.write_bytes(b"not pdf bytes")

    with pytest.raises(PdfDocumentReviewIntakeError) as error:
        service.ingest(
            source,
            original_filename="invalid.pdf",
            actor_id="operator_" + "a" * 32,
            idempotency_key="api:document-review:invalid",
        )

    assert error.value.code == "PDF_DOCUMENT_REVIEW_SIGNATURE_INVALID"
    assert recorder.values is None
    assert list(service.settings.staging_root.iterdir()) == []


def test_pdf_document_review_intake_rejects_hardlinked_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / "uploaded.pdf"
    alias = tmp_path / "uploaded-hardlink.pdf"
    source.write_bytes(b"%PDF-1.7\nimmutable-source\n%%EOF\n")
    alias.hardlink_to(source)

    with pytest.raises(PdfDocumentReviewIntakeError) as error:
        service.ingest(
            source,
            original_filename="주간지.pdf",
            actor_id="operator_" + "a" * 32,
            idempotency_key="api:document-review:hardlink",
        )

    assert error.value.code == "PDF_DOCUMENT_REVIEW_SOURCE_INVALID"
    assert recorder.values is None
