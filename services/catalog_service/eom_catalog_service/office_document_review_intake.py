"""Catalog-owned immutable PDF/HWP/HWPX review intake through one PDF projection."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import (
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewIntakeManifest,
    OfficeDocumentReviewMemberPointer,
    OfficeDocumentReviewSourcePointer,
    PdfDocumentReviewPageMember,
    PdfDocumentReviewRendererIdentity,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.office_converter_worker import HWP_SIGNATURE
from eom_catalog_service.office_document_converter import (
    OfficeDocumentConversionError,
    SystemdOfficeDocumentConverter,
)
from eom_catalog_service.pdf_document_review_intake import (
    MAX_PAGE_BYTES,
    MAX_RENDERED_BYTES,
    MAX_SOURCE_BYTES,
    _identity,
    _pdf_page_count,
    _png_dimensions,
    _require_executable,
    _run,
)
from eom_catalog_service.settings import CatalogSettings

OFFICE_DOCUMENT_REVIEW_PROTOCOL_VERSION = "catalog/1.17"
OFFICE_DOCUMENT_REVIEW_SCHEMA_HASH = content_sha256(
    {
        "protocol": OFFICE_DOCUMENT_REVIEW_PROTOCOL_VERSION,
        "contracts": [
            "document-review-intake-manifest/2.0",
            "pdf-source/1.0",
            "hwp-source/2.0",
            "editable-hwpx/1.0",
            "pdf-page-render/1.0",
        ],
    }
)
_PDF_SIGNATURE = b"%PDF-"
_HWPX_SIGNATURE = b"PK\x03\x04"


class OfficeDocumentReviewIntakeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OfficeReviewArtifactCommitter(Protocol):
    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, object],
        result: dict[str, object],
        file_metadata: dict[str, dict[str, str]] | None = None,
        manifest_version: str = "catalog-file-set/1.0",
        protocol_version: str,
        protocol_schema_hash: str,
        expected_file_sha256: dict[str, str] | None = None,
    ) -> CatalogArtifact: ...


def _copy_exact_source(source: Path, target: Path, *, source_format: str) -> tuple[str, int]:
    try:
        descriptor = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise OfficeDocumentReviewIntakeError(
            "DOCUMENT_REVIEW_SOURCE_UNREADABLE",
            "Document review source could not be opened safely",
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 8 <= before.st_size <= MAX_SOURCE_BYTES
        ):
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_SOURCE_INVALID",
                "Document review source is not one bounded regular file",
            )
        prefix = os.read(descriptor, 8)
        valid_signature = {
            "PDF": prefix.startswith(_PDF_SIGNATURE),
            "HWP": prefix == HWP_SIGNATURE,
            "HWPX": prefix.startswith(_HWPX_SIGNATURE),
        }.get(source_format, False)
        if not valid_signature:
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_SIGNATURE_INVALID",
                "Document review source signature differs from its declared format",
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        target_descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_SOURCE_CHANGED",
                        "Document review source ended before its opened size",
                    )
                view = memoryview(chunk)
                while view:
                    written = os.write(target_descriptor, view)
                    if written < 1:
                        raise OfficeDocumentReviewIntakeError(
                            "DOCUMENT_REVIEW_SOURCE_WRITE_FAILED",
                            "Document review source could not be staged exactly",
                        )
                    view = view[written:]
                remaining -= len(chunk)
            os.fsync(target_descriptor)
        finally:
            os.close(target_descriptor)
        if _identity(before) != _identity(os.fstat(descriptor)):
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_SOURCE_CHANGED",
                "Document review source changed during intake",
            )
        return sha256_file(target), before.st_size
    finally:
        os.close(descriptor)


class OfficeDocumentReviewIntakeService:
    """Commit an immutable original plus exact reviewed PDF/page projections."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        converter: SystemdOfficeDocumentConverter | None = None,
        pdfinfo: Path = Path("/usr/bin/pdfinfo"),
        pdftoppm: Path = Path("/usr/bin/pdftoppm"),
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts: OfficeReviewArtifactCommitter = CatalogArtifactService(
            engine, self.settings
        )
        self.converter = converter
        self.pdfinfo = _require_executable(pdfinfo)
        self.pdftoppm = _require_executable(pdftoppm)

    def _workspace(self, source_format: str) -> Path:
        if source_format in {"HWP", "HWPX"}:
            converter = self.converter
            if converter is None:
                try:
                    converter = SystemdOfficeDocumentConverter(self.settings.staging_root)
                except OfficeDocumentConversionError as exc:
                    raise OfficeDocumentReviewIntakeError(exc.code, str(exc)) from exc
                self.converter = converter
            return converter.create_workspace()
        return Path(
            tempfile.mkdtemp(prefix="office-document-review.", dir=self.settings.staging_root)
        )

    def ingest(
        self,
        source: Path,
        *,
        original_filename: str,
        source_format: str,
        actor_id: str,
        idempotency_key: str,
    ) -> OfficeDocumentReviewSourcePointer:
        if source_format not in {"PDF", "HWP", "HWPX"}:
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_FORMAT_UNSUPPORTED",
                "Document review source format is unsupported",
            )
        workspace = self._workspace(source_format)
        try:
            suffix = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}[source_format]
            source_target = workspace / f"original{suffix}"
            source_hash, source_bytes = _copy_exact_source(
                source,
                source_target,
                source_format=source_format,
            )
            if source_format == "PDF":
                review_pdf = source_target
                conversion = OfficeDocumentReviewConversionIdentity(
                    conversion_kind="IDENTITY_PDF",
                    review_pdf_sha256=source_hash,
                )
            else:
                converter = self.converter
                if converter is None:
                    raise OfficeDocumentReviewIntakeError(
                        "OFFICE_DOCUMENT_CONVERTER_UNAVAILABLE",
                        "Office converter is unavailable",
                    )
                try:
                    conversion = converter.convert(workspace, source_format=source_format)
                except OfficeDocumentConversionError as exc:
                    raise OfficeDocumentReviewIntakeError(exc.code, str(exc)) from exc
                review_pdf = workspace / "converted/original.pdf"
            identity_seed = {
                "idempotency_key": idempotency_key,
                "actor_id": actor_id,
                "original_filename": original_filename,
                "source_format": source_format,
                "source_sha256": source_hash,
            }
            identity_hash = content_sha256(identity_seed).removeprefix("sha256:")
            revision_hash = content_sha256(
                {
                    **identity_seed,
                    "identity": "document-review-revision/2.0",
                    "conversion": conversion.model_dump(mode="json"),
                }
            ).removeprefix("sha256:")
            document_id = f"document_{identity_hash[:32]}"
            document_revision_id = f"documentrev_{revision_hash[:32]}"
            try:
                page_count = _pdf_page_count(self.pdfinfo, review_pdf)
            except RuntimeError as exc:
                raise OfficeDocumentReviewIntakeError(
                    "DOCUMENT_REVIEW_PDF_INVALID",
                    "Document review PDF projection is invalid",
                ) from exc
            page_directory = workspace / "pages"
            page_directory.mkdir(mode=0o700)
            pages: list[PdfDocumentReviewPageMember] = []
            total_rendered_bytes = 0
            for page_number in range(1, page_count + 1):
                prefix = page_directory / f"page-{page_number:04d}"
                try:
                    completed = _run(
                        [
                            str(self.pdftoppm),
                            "-f",
                            str(page_number),
                            "-l",
                            str(page_number),
                            "-singlefile",
                            "-png",
                            "-scale-to",
                            "2400",
                            str(review_pdf),
                            str(prefix),
                        ],
                        timeout_seconds=60.0,
                    )
                except RuntimeError as exc:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_PAGE_RENDER_FAILED",
                        "Document review page renderer failed",
                    ) from exc
                if completed.returncode != 0 or len(completed.stderr) > 256 * 1024:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_PAGE_RENDER_FAILED",
                        f"Document review page {page_number} could not be rendered",
                    )
                output = prefix.with_suffix(".png")
                try:
                    width, height, content_length = _png_dimensions(output)
                except RuntimeError as exc:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_PAGE_RENDER_INVALID",
                        "Document review page render is invalid",
                    ) from exc
                if content_length > MAX_PAGE_BYTES:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_PAGE_RENDER_INVALID",
                        "Document review page render exceeds the bound",
                    )
                total_rendered_bytes += content_length
                if total_rendered_bytes > MAX_RENDERED_BYTES:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_RENDERED_BYTES_EXCEEDED",
                        "Document review pages exceed the total byte bound",
                    )
                pages.append(
                    PdfDocumentReviewPageMember(
                        page_number=page_number,
                        member_path=f"pages/page-{page_number:04d}.png",
                        sha256=sha256_file(output),
                        content_length=content_length,
                        width_px=width,
                        height_px=height,
                    )
                )
            source_schema = {
                "PDF": "eom://schemas/document-review/pdf-source/1.0",
                "HWP": "eom://schemas/document-review/hwp-source/2.0",
                "HWPX": "eom://schemas/document-review/editable-hwpx/1.0",
            }[source_format]
            source_media = {
                "PDF": "application/pdf",
                "HWP": "application/vnd.hancom.hwp",
                "HWPX": "application/vnd.hancom.hwpx",
            }[source_format]
            source_member = {
                "member_path": f"source/original{suffix}",
                "sha256": source_hash,
                "content_length": source_bytes,
                "media_type": source_media,
                "schema_ref": source_schema,
            }
            review_pdf_member = {
                "member_path": "source/original.pdf",
                "sha256": conversion.review_pdf_sha256,
                "content_length": review_pdf.stat().st_size,
                "media_type": "application/pdf",
                "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
            }
            manifest_value: dict[str, object] = {
                "schema_version": "document-review-intake-manifest/2.0",
                "document_id": document_id,
                "document_revision_id": document_revision_id,
                "original_filename": original_filename,
                "source_format": source_format,
                "original_source": source_member,
                "review_pdf": review_pdf_member,
                "editable_hwpx": source_member if source_format == "HWPX" else None,
                "conversion": conversion.model_dump(mode="json"),
                "renderer": PdfDocumentReviewRendererIdentity(
                    pdfinfo_sha256=sha256_file(self.pdfinfo),
                    pdftoppm_sha256=sha256_file(self.pdftoppm),
                ).model_dump(mode="json"),
                "page_count": page_count,
                "pages": [page.model_dump(mode="json") for page in pages],
            }
            manifest_value["manifest_sha256"] = content_sha256(manifest_value)
            manifest = OfficeDocumentReviewIntakeManifest.model_validate(manifest_value)
            validate_contract(
                "document-review-intake-manifest-v2",
                manifest.model_dump(mode="json"),
            )
            manifest_path = workspace / "manifest.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
            manifest_path.chmod(0o600)
            files = {
                "manifest.json": manifest_path,
                f"source/original{suffix}": source_target,
                **({"source/original.pdf": review_pdf} if source_format != "PDF" else {}),
                **{page.member_path: workspace / page.member_path for page in pages},
            }
            file_metadata = {
                "manifest.json": {
                    "media_type": "application/json",
                    "schema_ref": (
                        "eom://schemas/document-review/document-review-intake-manifest/2.0"
                    ),
                },
                f"source/original{suffix}": {
                    "media_type": source_media,
                    "schema_ref": source_schema,
                },
                **(
                    {
                        "source/original.pdf": {
                            "media_type": "application/pdf",
                            "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
                        }
                    }
                    if source_format != "PDF"
                    else {}
                ),
                **{
                    page.member_path: {
                        "media_type": "image/png",
                        "schema_ref": "eom://schemas/document-review/pdf-page-render/1.0",
                    }
                    for page in pages
                },
            }
            expected_hashes = {
                "manifest.json": sha256_file(manifest_path),
                f"source/original{suffix}": source_hash,
                **(
                    {"source/original.pdf": conversion.review_pdf_sha256}
                    if source_format != "PDF"
                    else {}
                ),
                **{page.member_path: page.sha256 for page in pages},
            }
            artifact = self.artifacts.commit_file_set(
                files=files,
                primary_file="manifest.json",
                artifact_type="document-review-source-v2",
                idempotency_key=f"document-review-source-v2:{idempotency_key}",
                request={
                    **identity_seed,
                    "conversion": conversion.model_dump(mode="json"),
                },
                result={
                    "document_id": document_id,
                    "document_revision_id": document_revision_id,
                    "source_sha256": source_hash,
                    "review_pdf_sha256": conversion.review_pdf_sha256,
                    "page_count": page_count,
                    "manifest_sha256": manifest.manifest_sha256,
                },
                file_metadata=file_metadata,
                manifest_version="document-review-file-set/2.0",
                protocol_version=OFFICE_DOCUMENT_REVIEW_PROTOCOL_VERSION,
                protocol_schema_hash=OFFICE_DOCUMENT_REVIEW_SCHEMA_HASH,
                expected_file_sha256=expected_hashes,
            )
            self._validate_committed_artifact(artifact, expected_hashes)
            return self._document_pointer(artifact, manifest)
        finally:
            shutil.rmtree(workspace)

    @staticmethod
    def _validate_committed_artifact(
        artifact: CatalogArtifact,
        expected_hashes: dict[str, str],
    ) -> None:
        raw_files = artifact.manifest.get("files")
        files = (
            {
                entry.get("file_name"): entry.get("sha256")
                for entry in raw_files
                if isinstance(entry, dict)
            }
            if isinstance(raw_files, list)
            else {}
        )
        if files != expected_hashes or artifact.content_hash != expected_hashes["manifest.json"]:
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_ARTIFACT_REPLAY_MISMATCH",
                "Committed document-review Artifact differs from the exact intake",
            )

    @staticmethod
    def _document_pointer(
        artifact: CatalogArtifact,
        manifest: OfficeDocumentReviewIntakeManifest,
    ) -> OfficeDocumentReviewSourcePointer:
        def pointer(value: object) -> OfficeDocumentReviewMemberPointer:
            descriptor = value.model_dump(mode="json")  # type: ignore[attr-defined]
            return OfficeDocumentReviewMemberPointer(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                **descriptor,
            )

        original = pointer(manifest.original_source)
        review_pdf = PdfReviewArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            **manifest.review_pdf.model_dump(mode="json"),
        )
        review_document = PdfReviewDocumentPointer(
            document_id=manifest.document_id,
            document_revision_id=manifest.document_revision_id,
            original_filename="review.pdf",
            source_pdf=review_pdf,
            page_count=manifest.page_count,
            pages=tuple(
                PdfReviewPagePointer(
                    page_number=page.page_number,
                    width_px=page.width_px,
                    height_px=page.height_px,
                    rotation_degrees=0,
                    page_image=PdfReviewArtifactMemberPointer(
                        artifact_id=artifact.artifact_id,
                        artifact_revision_id=artifact.revision_id,
                        member_path=page.member_path,
                        sha256=page.sha256,
                        schema_ref="eom://schemas/document-review/pdf-page-render/1.0",
                        media_type="image/png",
                        content_length=page.content_length,
                    ),
                    text_layer=None,
                )
                for page in manifest.pages
            ),
        )
        return OfficeDocumentReviewSourcePointer(
            document_id=manifest.document_id,
            document_revision_id=manifest.document_revision_id,
            original_filename=manifest.original_filename,
            source_format=manifest.source_format,
            original_source=original,
            review_document=review_document,
            editable_hwpx=original if manifest.source_format == "HWPX" else None,
            intake_manifest=OfficeDocumentReviewMemberPointer(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                member_path="manifest.json",
                sha256=artifact.content_hash,
                content_length=len(canonical_json_bytes(manifest.model_dump(mode="json"))),
                media_type="application/json",
                schema_ref=("eom://schemas/document-review/document-review-intake-manifest/2.0"),
            ),
            conversion=manifest.conversion,
        )
