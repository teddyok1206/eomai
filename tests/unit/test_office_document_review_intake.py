from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewIntakeManifest,
)
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.office_document_review_intake import (
    OfficeDocumentReviewIntakeError,
    OfficeDocumentReviewIntakeService,
    OfficeReviewArtifactCommitter,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_file
from sqlalchemy import create_engine


def _png(width: int = 1200, height: int = 1800) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


class _ArtifactRecorder:
    values: dict[str, Any] | None = None
    manifest: OfficeDocumentReviewIntakeManifest | None = None

    def commit_file_set(self, **values: Any) -> CatalogArtifact:
        self.values = values
        files = cast(dict[str, Path], values["files"])
        expected = cast(dict[str, str], values["expected_file_sha256"])
        assert {name: sha256_file(path) for name, path in files.items()} == expected
        raw_manifest: object = json.loads(files["manifest.json"].read_text(encoding="utf-8"))
        self.manifest = OfficeDocumentReviewIntakeManifest.model_validate(raw_manifest)
        return CatalogArtifact(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash=expected["manifest.json"],
            manifest_hash="sha256:" + "4" * 64,
            content_bytes=sum(path.stat().st_size for path in files.values()),
            nas_path="/non-live/document-review",
            manifest={
                "files": [
                    {"file_name": name, "sha256": digest}
                    for name, digest in sorted(expected.items())
                ]
            },
        )


class _FakeOfficeConverter:
    def __init__(self, staging_root: Path) -> None:
        self.root = staging_root / "office-conversion"
        self.root.mkdir(mode=0o700)

    def create_workspace(self) -> Path:
        workspace = self.root / ("officeconv_" + "5" * 32)
        workspace.mkdir(mode=0o700)
        return workspace

    def convert(
        self,
        workspace: Path,
        *,
        source_format: str,
    ) -> OfficeDocumentReviewConversionIdentity:
        assert source_format in {"HWP", "HWPX"}
        output = workspace / "converted/original.pdf"
        output.parent.mkdir(mode=0o700)
        output.write_bytes(b"%PDF-1.7\nconverted\n%%EOF\n")
        output.chmod(0o600)
        return OfficeDocumentReviewConversionIdentity(
            conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
            review_pdf_sha256=sha256_file(output),
            libreoffice_version="LibreOffice test",
            libreoffice_sha256="sha256:" + "6" * 64,
            h2orestart_sha256="sha256:" + "7" * 64,
        )


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[OfficeDocumentReviewIntakeService, _ArtifactRecorder]:
    staging_root = tmp_path / "staging"
    staging_root.mkdir(mode=0o700)
    pdfinfo = tmp_path / "pdfinfo"
    pdftoppm = tmp_path / "pdftoppm"
    pdfinfo.write_bytes(b"fixed-pdfinfo")
    pdftoppm.write_bytes(b"fixed-pdftoppm")
    monkeypatch.setattr(
        "eom_catalog_service.office_document_review_intake._require_executable",
        lambda value: value,
    )

    def run(arguments: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[bytes]:
        assert timeout_seconds > 0
        Path(arguments[-1] + ".png").write_bytes(_png())
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr("eom_catalog_service.office_document_review_intake._run", run)
    monkeypatch.setattr(
        "eom_catalog_service.office_document_review_intake._pdf_page_count",
        lambda _binary, _source: 1,
    )
    settings = CatalogSettings(
        staging_root=staging_root,
        nas_artifact_root=tmp_path / "nas",
        intake_root=tmp_path / "intake",
    )
    service = OfficeDocumentReviewIntakeService(
        create_engine("sqlite+pysqlite:///:memory:"),
        settings,
        converter=cast(Any, _FakeOfficeConverter(staging_root)),
        pdfinfo=pdfinfo,
        pdftoppm=pdftoppm,
    )
    recorder = _ArtifactRecorder()
    service.artifacts = cast(OfficeReviewArtifactCommitter, recorder)
    return service, recorder


@pytest.mark.parametrize(
    ("source_format", "filename", "payload", "expected_source_member", "editable"),
    [
        ("PDF", "검토.pdf", b"%PDF-1.7\nsource\n%%EOF\n", "source/original.pdf", False),
        (
            "HWP",
            "검토.hwp",
            bytes.fromhex("d0cf11e0a1b11ae1") + b"source",
            "source/original.hwp",
            False,
        ),
        ("HWPX", "검토.hwpx", b"PK\x03\x04source", "source/original.hwpx", True),
    ],
)
def test_office_intake_preserves_source_and_projects_one_review_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_format: str,
    filename: str,
    payload: bytes,
    expected_source_member: str,
    editable: bool,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / filename
    source.write_bytes(payload)

    pointer = service.ingest(
        source,
        original_filename=filename,
        source_format=source_format,
        actor_id="operator_" + "a" * 32,
        idempotency_key=f"api:document-review:{source_format.casefold()}",
    )

    assert source.read_bytes() == payload
    assert pointer.source_format == source_format
    assert pointer.original_source.member_path == expected_source_member
    assert pointer.review_document.source_pdf.member_path == "source/original.pdf"
    assert pointer.review_document.page_count == 1
    assert (pointer.editable_hwpx is not None) is editable
    if pointer.editable_hwpx is not None:
        assert pointer.editable_hwpx == pointer.original_source
    assert recorder.values is not None
    assert recorder.values["protocol_version"] == "catalog/1.17"
    assert recorder.values["artifact_type"] == "document-review-source-v2"
    expected_files = {
        "manifest.json",
        expected_source_member,
        "pages/page-0001.png",
    }
    if source_format != "PDF":
        expected_files.add("source/original.pdf")
    assert set(recorder.values["files"]) == expected_files
    assert recorder.manifest is not None
    assert recorder.manifest.source_format == source_format
    assert recorder.manifest.editable_hwpx is not None if editable else True
    assert list(service.settings.staging_root.rglob("officeconv_*")) == []


def test_office_intake_rejects_declared_format_signature_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / "forged.hwpx"
    source.write_bytes(b"%PDF-1.7\nnot hwpx\n")

    with pytest.raises(OfficeDocumentReviewIntakeError) as error:
        service.ingest(
            source,
            original_filename="forged.hwpx",
            source_format="HWPX",
            actor_id="operator_" + "a" * 32,
            idempotency_key="api:document-review:forged",
        )

    assert error.value.code == "DOCUMENT_REVIEW_SIGNATURE_INVALID"
    assert recorder.values is None


def test_office_intake_does_not_offer_hwp_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _recorder = _service(tmp_path, monkeypatch)
    source = tmp_path / "legacy.hwp"
    source.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"source")

    pointer = service.ingest(
        source,
        original_filename="legacy.hwp",
        source_format="HWP",
        actor_id="operator_" + "a" * 32,
        idempotency_key="api:document-review:hwp-no-edit",
    )

    assert pointer.editable_hwpx is None
