"""Preview projection reuses original Intake bytes only as a temporary input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.external_item_preview import ExternalItemPreviewManifest
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.external_item_document_media import (
    ExternalDocumentMediaType,
    ResolvedExternalItemDocumentMedia,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    _copy_verified_source,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_file


def _media(
    payload: bytes,
    *,
    media_type: ExternalDocumentMediaType = "application/vnd.hancom.hwp",
) -> ResolvedExternalItemDocumentMedia:
    return ResolvedExternalItemDocumentMedia(
        member=VerifiedArtifactMemberStream(
            stream=BytesIO(payload),
            content_length=len(payload),
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        ),
        media_type=media_type,
        filename="문항_12345.hwp",
        source_file_id="sourcefile_" + "3" * 32,
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        member_path="source/문항_12345.hwp",
    )


def test_copy_rejects_changed_verified_input(tmp_path: Path) -> None:
    source = _media(b"original source bytes")
    source = replace(
        source,
        member=VerifiedArtifactMemberStream(
            stream=BytesIO(b"changed source bytes"),
            content_length=source.member.content_length,
            sha256=source.member.sha256,
        ),
    )
    try:
        _copy_verified_source(source, tmp_path / "original.hwp")
    except ValueError as exc:
        assert "changed during materialization" in str(exc)
    else:
        raise AssertionError("changed source was accepted")
    assert source.member.stream.closed


def test_build_commits_only_derivative_pdf_and_pinned_manifest(tmp_path: Path) -> None:
    source = _media(
        b"PK\x03\x04" + b"source bytes",
        media_type="application/vnd.hancom.hwpx",
    )
    workspace = tmp_path / "office-conversion" / ("officeconv_" + "a" * 32)
    workspace.mkdir(parents=True)
    pdf_bytes = b"%PDF-1.7\npreview\n%%EOF"

    class FakeConverter:
        def create_workspace(self) -> Path:
            return workspace

        def convert(
            self, path: Path, *, source_format: str
        ) -> OfficeDocumentReviewConversionIdentity:
            assert path == workspace
            assert source_format == "HWPX"
            assert (path / "original.hwpx").read_bytes() == b"PK\x03\x04" + b"source bytes"
            output = path / "converted"
            output.mkdir()
            (output / "original.pdf").write_bytes(pdf_bytes)
            return OfficeDocumentReviewConversionIdentity(
                conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
                review_pdf_sha256=sha256_file(output / "original.pdf"),
                libreoffice_version="LibreOffice 24.2",
                libreoffice_sha256="sha256:" + "8" * 64,
                h2orestart_sha256="sha256:" + "9" * 64,
            )

    def commit(**arguments):
        assert set(arguments["files"]) == {"preview-manifest.json", "preview/original.pdf"}
        assert all("original.hwpx" not in member for member in arguments["files"])
        manifest_raw = json.loads(arguments["files"]["preview-manifest.json"].read_bytes())
        manifest = ExternalItemPreviewManifest.model_validate(manifest_raw)
        assert manifest.source_member_path == "source/문항_12345.hwp"
        assert manifest.source_format == "HWPX"
        assert manifest.pdf_sha256 == sha256_file(arguments["files"]["preview/original.pdf"])
        assert arguments["expected_file_sha256"]["preview/original.pdf"] == manifest.pdf_sha256
        assert arguments["request"]["conversion"]["review_pdf_sha256"] == manifest.pdf_sha256
        return SimpleNamespace(artifact_id="artifact_" + "f" * 32)

    service = object.__new__(ExternalItemPreviewProjectionService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    service.source_media = SimpleNamespace(open=Mock(return_value=source))
    service.converter = FakeConverter()
    service.artifacts = SimpleNamespace(commit_file_set=Mock(side_effect=commit))
    result = service.build(
        ExternalItemDocumentMediaQuery(
            source_id="extitem_" + "1" * 32,
            source_revision_id="extitemrev_" + "2" * 32,
            edition=3,
        )
    )
    assert result.artifact_id == "artifact_" + "f" * 32
    assert not workspace.exists()
    assert source.member.stream.closed
    service.artifacts.commit_file_set.assert_called_once()


def test_build_rejects_workspace_outside_converter_boundary(tmp_path: Path) -> None:
    source = _media(b"original source bytes")
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    service = object.__new__(ExternalItemPreviewProjectionService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    service.source_media = SimpleNamespace(open=Mock(return_value=source))
    service.converter = SimpleNamespace(create_workspace=lambda: tmp_path)
    service.artifacts = SimpleNamespace(commit_file_set=Mock())
    with pytest.raises(ValueError, match="outside the fixed boundary"):
        service.build(
            ExternalItemDocumentMediaQuery(
                source_id="extitem_" + "1" * 32,
                source_revision_id="extitemrev_" + "2" * 32,
                edition=3,
            )
        )
    assert sentinel.read_text() == "keep"
    assert source.member.stream.closed
    service.artifacts.commit_file_set.assert_not_called()
