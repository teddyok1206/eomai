"""Catalog-owned immutable PDF/HWP/HWPX review intake through one PDF projection."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import (
    OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewIntakeManifest,
    OfficeDocumentReviewIntakeManifestV3,
    OfficeDocumentReviewMemberPointer,
    OfficeDocumentReviewMemberPointerV2,
    OfficeDocumentReviewSourcePointer,
    OfficeDocumentReviewSourcePointerV2,
    OfficeDocumentReviewSourceUploadManifest,
    PdfDocumentReviewPageMember,
    PdfDocumentReviewRendererIdentity,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_orchestrator.errors import PlatformError
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.office_converter_worker import (
    HWP_SIGNATURE,
    OfficeConverterError,
    validate_office_source,
)
from eom_catalog_service.office_document_converter import (
    OfficeDocumentConversionError,
    SystemdOfficeDocumentConverter,
    create_office_conversion_workspace,
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
OFFICE_DOCUMENT_REVIEW_V3_PROTOCOL_VERSION = "catalog/1.20"
OFFICE_DOCUMENT_REVIEW_V3_SCHEMA_HASH = content_sha256(
    {
        "protocol": OFFICE_DOCUMENT_REVIEW_V3_PROTOCOL_VERSION,
        "contracts": [
            "document-review-source-upload-manifest/1.0",
            "document-review-intake-manifest/3.0",
            "office-document-conversion-outcome/1.0",
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
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retained_source: OfficeDocumentReviewMemberPointerV2 | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retained_source = retained_source


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
            try:
                return create_office_conversion_workspace(self.settings.staging_root)
            except OfficeDocumentConversionError as exc:
                raise OfficeDocumentReviewIntakeError(exc.code, str(exc)) from exc
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
        durable_source: bool = False,
    ) -> OfficeDocumentReviewSourcePointer | OfficeDocumentReviewSourcePointerV2:
        if source_format not in {"PDF", "HWP", "HWPX"}:
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_FORMAT_UNSUPPORTED",
                "Document review source format is unsupported",
            )
        workspace = self._workspace(source_format)
        retained_source: OfficeDocumentReviewMemberPointerV2 | None = None
        try:
            suffix = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}[source_format]
            source_target = workspace / f"original{suffix}"
            source_hash, source_bytes = _copy_exact_source(
                source,
                source_target,
                source_format=source_format,
            )
            if source_format in {"HWP", "HWPX"}:
                try:
                    validate_office_source(source_target, source_format, os.getuid())
                except OfficeConverterError as exc:
                    raise OfficeDocumentReviewIntakeError(
                        "DOCUMENT_REVIEW_SOURCE_INVALID",
                        "Office review source package failed bounded validation",
                    ) from exc
            retained_source = (
                self._commit_source_upload(
                    source_target,
                    original_filename=original_filename,
                    source_format=source_format,
                    source_hash=source_hash,
                    source_bytes=source_bytes,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    workspace=workspace,
                )
                if durable_source and source_format in {"HWP", "HWPX"}
                else None
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
                    try:
                        converter = SystemdOfficeDocumentConverter(self.settings.staging_root)
                    except OfficeDocumentConversionError as exc:
                        raise OfficeDocumentReviewIntakeError(exc.code, str(exc)) from exc
                    self.converter = converter
                try:
                    conversion = converter.convert(workspace, source_format=source_format)
                except OfficeDocumentConversionError as exc:
                    raise OfficeDocumentReviewIntakeError(
                        exc.code,
                        str(exc),
                        retained_source=retained_source,
                    ) from exc
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
                "schema_version": (
                    "document-review-intake-manifest/2.0"
                    if retained_source is None
                    else "document-review-intake-manifest/3.0"
                ),
                "document_id": document_id,
                "document_revision_id": document_revision_id,
                "original_filename": original_filename,
                "source_format": source_format,
                "original_source": (
                    source_member
                    if retained_source is None
                    else retained_source.model_dump(mode="json")
                ),
                "review_pdf": review_pdf_member,
                "editable_hwpx": (
                    source_member
                    if retained_source is None and source_format == "HWPX"
                    else (
                        retained_source.model_dump(mode="json")
                        if retained_source is not None and source_format == "HWPX"
                        else None
                    )
                ),
                "conversion": conversion.model_dump(mode="json"),
                "renderer": PdfDocumentReviewRendererIdentity(
                    pdfinfo_sha256=sha256_file(self.pdfinfo),
                    pdftoppm_sha256=sha256_file(self.pdftoppm),
                ).model_dump(mode="json"),
                "page_count": page_count,
                "pages": [page.model_dump(mode="json") for page in pages],
            }
            manifest_value["manifest_sha256"] = content_sha256(manifest_value)
            manifest = (
                OfficeDocumentReviewIntakeManifest.model_validate(manifest_value)
                if retained_source is None
                else OfficeDocumentReviewIntakeManifestV3.model_validate(manifest_value)
            )
            validate_contract(
                (
                    "document-review-intake-manifest-v2"
                    if retained_source is None
                    else "document-review-intake-manifest-v3"
                ),
                manifest.model_dump(mode="json"),
            )
            manifest_path = workspace / OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER
            manifest_path.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
            manifest_path.chmod(0o600)
            files = {
                OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER: manifest_path,
                **({f"source/original{suffix}": source_target} if retained_source is None else {}),
                **({"source/original.pdf": review_pdf} if source_format != "PDF" else {}),
                **{page.member_path: workspace / page.member_path for page in pages},
            }
            file_metadata = {
                OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER: {
                    "media_type": "application/json",
                    "schema_ref": (
                        "eom://schemas/document-review/document-review-intake-manifest/2.0"
                        if retained_source is None
                        else ("eom://schemas/document-review/document-review-intake-manifest/3.0")
                    ),
                },
                **(
                    {
                        f"source/original{suffix}": {
                            "media_type": source_media,
                            "schema_ref": source_schema,
                        }
                    }
                    if retained_source is None
                    else {}
                ),
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
                OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER: sha256_file(manifest_path),
                **({f"source/original{suffix}": source_hash} if retained_source is None else {}),
                **(
                    {"source/original.pdf": conversion.review_pdf_sha256}
                    if source_format != "PDF"
                    else {}
                ),
                **{page.member_path: page.sha256 for page in pages},
            }
            artifact = self.artifacts.commit_file_set(
                files=files,
                primary_file=OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
                artifact_type=(
                    "document-review-source-v2"
                    if retained_source is None
                    else "document-review-projection-v3"
                ),
                idempotency_key=(
                    f"document-review-source-v2:{idempotency_key}"
                    if retained_source is None
                    else f"document-review-projection-v3:{idempotency_key}"
                ),
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
                manifest_version=(
                    "document-review-file-set/2.0"
                    if retained_source is None
                    else "document-review-projection-file-set/3.0"
                ),
                protocol_version=(
                    OFFICE_DOCUMENT_REVIEW_PROTOCOL_VERSION
                    if retained_source is None
                    else OFFICE_DOCUMENT_REVIEW_V3_PROTOCOL_VERSION
                ),
                protocol_schema_hash=(
                    OFFICE_DOCUMENT_REVIEW_SCHEMA_HASH
                    if retained_source is None
                    else OFFICE_DOCUMENT_REVIEW_V3_SCHEMA_HASH
                ),
                expected_file_sha256=expected_hashes,
            )
            self._validate_committed_artifact(
                artifact,
                expected_hashes,
                primary_file=OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
            )
            if retained_source is None:
                assert isinstance(manifest, OfficeDocumentReviewIntakeManifest)
                return self._document_pointer(artifact, manifest)
            assert isinstance(manifest, OfficeDocumentReviewIntakeManifestV3)
            return self._document_pointer_v3(artifact, manifest)
        except OfficeDocumentReviewIntakeError as exc:
            if retained_source is None or exc.retained_source is not None:
                raise
            raise OfficeDocumentReviewIntakeError(
                exc.code,
                str(exc),
                retained_source=retained_source,
            ) from exc
        except PlatformError as exc:
            raise OfficeDocumentReviewIntakeError(
                "CATALOG_ARTIFACT_COMMIT_FAILED",
                "Document-review projection Artifact could not be committed",
                retained_source=retained_source,
            ) from exc
        except Exception as exc:
            if retained_source is None:
                raise
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_PROJECTION_FAILED",
                "Durable Office source was retained but its review projection failed",
                retained_source=retained_source,
            ) from exc
        finally:
            shutil.rmtree(workspace)

    def _commit_source_upload(
        self,
        source: Path,
        *,
        original_filename: str,
        source_format: str,
        source_hash: str,
        source_bytes: int,
        actor_id: str,
        idempotency_key: str,
        workspace: Path,
    ) -> OfficeDocumentReviewMemberPointerV2:
        suffix = {"HWP": ".hwp", "HWPX": ".hwpx"}[source_format]
        media_type = {
            "HWP": "application/vnd.hancom.hwp",
            "HWPX": "application/vnd.hancom.hwpx",
        }[source_format]
        schema_ref = {
            "HWP": "eom://schemas/document-review/hwp-source/2.0",
            "HWPX": "eom://schemas/document-review/editable-hwpx/1.0",
        }[source_format]
        member_path = f"source/original{suffix}"
        descriptor = {
            "member_path": member_path,
            "sha256": source_hash,
            "content_length": source_bytes,
            "media_type": media_type,
            "schema_ref": schema_ref,
        }
        manifest_value: dict[str, object] = {
            "schema_version": "document-review-source-upload-manifest/1.0",
            "original_filename": original_filename,
            "source_format": source_format,
            "original_source": descriptor,
        }
        manifest_value["manifest_sha256"] = content_sha256(manifest_value)
        manifest = OfficeDocumentReviewSourceUploadManifest.model_validate(manifest_value)
        validate_contract(
            "document-review-source-upload-manifest-v1",
            manifest.model_dump(mode="json"),
        )
        manifest_path = workspace / "source-upload-manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
        manifest_path.chmod(0o600)
        expected_hashes = {
            "source-upload-manifest.json": sha256_file(manifest_path),
            member_path: source_hash,
        }
        artifact = self.artifacts.commit_file_set(
            files={
                "source-upload-manifest.json": manifest_path,
                member_path: source,
            },
            primary_file="source-upload-manifest.json",
            artifact_type="document-review-source-upload-v1",
            idempotency_key=f"document-review-source-upload-v1:{idempotency_key}",
            request={
                "actor_id": actor_id,
                "original_filename": original_filename,
                "source_format": source_format,
                "source_sha256": source_hash,
                "source_bytes": source_bytes,
            },
            result={
                "original_filename": original_filename,
                "source_format": source_format,
                "source_sha256": source_hash,
                "source_bytes": source_bytes,
                "manifest_sha256": manifest.manifest_sha256,
            },
            file_metadata={
                "source-upload-manifest.json": {
                    "media_type": "application/json",
                    "schema_ref": (
                        "eom://schemas/document-review/document-review-source-upload-manifest/1.0"
                    ),
                },
                member_path: {
                    "media_type": media_type,
                    "schema_ref": schema_ref,
                },
            },
            manifest_version="document-review-source-upload-file-set/1.0",
            protocol_version=OFFICE_DOCUMENT_REVIEW_V3_PROTOCOL_VERSION,
            protocol_schema_hash=OFFICE_DOCUMENT_REVIEW_V3_SCHEMA_HASH,
            expected_file_sha256=expected_hashes,
        )
        self._validate_committed_artifact(
            artifact,
            expected_hashes,
            primary_file="source-upload-manifest.json",
        )
        return OfficeDocumentReviewMemberPointerV2(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member_path,
            sha256=source_hash,
            content_length=source_bytes,
            media_type=media_type,  # type: ignore[arg-type]
            schema_ref=schema_ref,
        )

    @staticmethod
    def _validate_committed_artifact(
        artifact: CatalogArtifact,
        expected_hashes: dict[str, str],
        *,
        primary_file: str = "manifest.json",
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
        if files != expected_hashes or artifact.content_hash != expected_hashes[primary_file]:
            raise OfficeDocumentReviewIntakeError(
                "DOCUMENT_REVIEW_ARTIFACT_REPLAY_MISMATCH",
                "Committed document-review Artifact differs from the exact intake",
            )

    @staticmethod
    def _document_pointer_v3(
        artifact: CatalogArtifact,
        manifest: OfficeDocumentReviewIntakeManifestV3,
    ) -> OfficeDocumentReviewSourcePointerV2:
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
        return OfficeDocumentReviewSourcePointerV2(
            document_id=manifest.document_id,
            document_revision_id=manifest.document_revision_id,
            original_filename=manifest.original_filename,
            source_format=manifest.source_format,
            original_source=manifest.original_source,
            review_document=review_document,
            editable_hwpx=manifest.editable_hwpx,
            intake_manifest=OfficeDocumentReviewMemberPointerV2(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                member_path=OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
                sha256=artifact.content_hash,
                content_length=len(canonical_json_bytes(manifest.model_dump(mode="json"))),
                media_type="application/json",
                schema_ref=("eom://schemas/document-review/document-review-intake-manifest/3.0"),
            ),
            conversion=manifest.conversion,
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
                member_path=OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
                sha256=artifact.content_hash,
                content_length=len(canonical_json_bytes(manifest.model_dump(mode="json"))),
                media_type="application/json",
                schema_ref=("eom://schemas/document-review/document-review-intake-manifest/2.0"),
            ),
            conversion=manifest.conversion,
        )
