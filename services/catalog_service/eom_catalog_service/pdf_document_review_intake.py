"""Catalog-owned immutable PDF intake and bounded Poppler page rendering."""

from __future__ import annotations

import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import (
    PdfDocumentReviewIntakeManifest,
    PdfDocumentReviewPageMember,
    PdfDocumentReviewRendererIdentity,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_workflow import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings

PDF_DOCUMENT_REVIEW_PROTOCOL_VERSION = "catalog/1.16"
PDF_DOCUMENT_REVIEW_SCHEMA_HASH = content_sha256(
    {
        "protocol": PDF_DOCUMENT_REVIEW_PROTOCOL_VERSION,
        "contracts": [
            "pdf-document-review-intake-manifest/1.0",
            "pdf-source/1.0",
            "pdf-page-render/1.0",
        ],
    }
)
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_PAGE_BYTES = 64 * 1024 * 1024
MAX_RENDERED_BYTES = 2 * 1024 * 1024 * 1024
MAX_PAGES = 2000
_PDF_SIGNATURE = re.compile(rb"^%PDF-[12]\.[0-9]")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PdfDocumentReviewIntakeError(RuntimeError):
    """Stable fail-closed error raised before an intake pointer is published."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PdfReviewArtifactCommitter(Protocol):
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


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _copy_exact_pdf(source: Path, target: Path) -> tuple[str, int]:
    descriptor = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 8
            or before.st_size > MAX_SOURCE_BYTES
        ):
            raise PdfDocumentReviewIntakeError(
                "PDF_DOCUMENT_REVIEW_SOURCE_INVALID",
                "PDF source is not one bounded regular file",
            )
        prefix = os.read(descriptor, 8)
        if _PDF_SIGNATURE.fullmatch(prefix) is None:
            raise PdfDocumentReviewIntakeError(
                "PDF_DOCUMENT_REVIEW_SIGNATURE_INVALID",
                "PDF source signature is invalid",
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
                    raise PdfDocumentReviewIntakeError(
                        "PDF_DOCUMENT_REVIEW_SOURCE_CHANGED",
                        "PDF source ended before its opened size",
                    )
                view = memoryview(chunk)
                while view:
                    written = os.write(target_descriptor, view)
                    if written < 1:
                        raise PdfDocumentReviewIntakeError(
                            "PDF_DOCUMENT_REVIEW_SOURCE_WRITE_FAILED",
                            "PDF source could not be materialized exactly",
                        )
                    view = view[written:]
                remaining -= len(chunk)
            os.fsync(target_descriptor)
        finally:
            os.close(target_descriptor)
        if _identity(before) != _identity(os.fstat(descriptor)):
            raise PdfDocumentReviewIntakeError(
                "PDF_DOCUMENT_REVIEW_SOURCE_CHANGED",
                "PDF source identity changed during intake",
            )
        return sha256_file(target), before.st_size
    finally:
        os.close(descriptor)


def _require_executable(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_RENDERER_INVALID",
            "PDF renderer executable identity is invalid",
        )
    return resolved


def _run(arguments: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_RENDERER_FAILED",
            "PDF renderer invocation failed",
        ) from exc


def _pdf_page_count(pdfinfo: Path, source: Path) -> int:
    completed = _run([str(pdfinfo), str(source)], timeout_seconds=30.0)
    if completed.returncode != 0 or len(completed.stdout) > 256 * 1024:
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PDF_INVALID",
            "PDF metadata could not be read",
        )
    try:
        lines = completed.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PDF_INVALID",
            "PDF metadata encoding is invalid",
        ) from exc
    fields = {
        key.strip(): value.strip()
        for line in lines
        if ":" in line
        for key, value in [line.split(":", 1)]
    }
    if fields.get("Encrypted", "no").split(maxsplit=1)[0].lower() != "no":
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_ENCRYPTED",
            "Encrypted PDFs are not supported",
        )
    raw_pages = fields.get("Pages", "")
    if not raw_pages.isdigit() or not 1 <= int(raw_pages) <= MAX_PAGES:
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PAGE_COUNT_INVALID",
            "PDF page count is outside the supported bound",
        )
    return int(raw_pages)


def _png_dimensions(path: Path) -> tuple[int, int, int]:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 24 <= metadata.st_size <= MAX_PAGE_BYTES
    ):
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PAGE_RENDER_INVALID",
            "Rendered page is not one bounded regular PNG",
        )
    with path.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PAGE_RENDER_INVALID",
            "Rendered page PNG header is invalid",
        )
    width, height = struct.unpack(">II", header[16:24])
    if not 64 <= width <= 2400 or not 64 <= height <= 2400:
        raise PdfDocumentReviewIntakeError(
            "PDF_DOCUMENT_REVIEW_PAGE_DIMENSIONS_INVALID",
            "Rendered page dimensions are outside the supported bound",
        )
    return width, height, metadata.st_size


class PdfDocumentReviewIntakeService:
    """Render and commit one exact PDF without ever mutating its bytes."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        pdfinfo: Path = Path("/usr/bin/pdfinfo"),
        pdftoppm: Path = Path("/usr/bin/pdftoppm"),
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts: PdfReviewArtifactCommitter = CatalogArtifactService(engine, self.settings)
        self.pdfinfo = _require_executable(pdfinfo)
        self.pdftoppm = _require_executable(pdftoppm)

    def ingest(
        self,
        source: Path,
        *,
        original_filename: str,
        actor_id: str,
        idempotency_key: str,
    ) -> PdfReviewDocumentPointer:
        workspace = Path(
            tempfile.mkdtemp(prefix="pdf-document-review.", dir=self.settings.staging_root)
        )
        try:
            source_target = workspace / "original.pdf"
            source_hash, source_bytes = _copy_exact_pdf(source, source_target)
            identity_seed = {
                "idempotency_key": idempotency_key,
                "actor_id": actor_id,
                "original_filename": original_filename,
                "source_pdf_sha256": source_hash,
            }
            identity_hash = content_sha256(identity_seed).removeprefix("sha256:")
            revision_hash = content_sha256(
                {**identity_seed, "identity": "pdf-document-review-revision/1.0"}
            ).removeprefix("sha256:")
            document_id = f"document_{identity_hash[:32]}"
            document_revision_id = f"documentrev_{revision_hash[:32]}"
            page_count = _pdf_page_count(self.pdfinfo, source_target)
            page_directory = workspace / "pages"
            page_directory.mkdir(mode=0o700)
            pages: list[PdfDocumentReviewPageMember] = []
            total_rendered_bytes = 0
            for page_number in range(1, page_count + 1):
                prefix = page_directory / f"page-{page_number:04d}"
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
                        str(source_target),
                        str(prefix),
                    ],
                    timeout_seconds=60.0,
                )
                if completed.returncode != 0 or len(completed.stderr) > 256 * 1024:
                    raise PdfDocumentReviewIntakeError(
                        "PDF_DOCUMENT_REVIEW_PAGE_RENDER_FAILED",
                        f"PDF page {page_number} could not be rendered",
                    )
                output = prefix.with_suffix(".png")
                width, height, content_length = _png_dimensions(output)
                total_rendered_bytes += content_length
                if total_rendered_bytes > MAX_RENDERED_BYTES:
                    raise PdfDocumentReviewIntakeError(
                        "PDF_DOCUMENT_REVIEW_RENDERED_BYTES_EXCEEDED",
                        "Rendered PDF pages exceed the supported total byte bound",
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
            manifest_value: dict[str, object] = {
                "schema_version": "pdf-document-review-intake-manifest/1.0",
                "document_id": document_id,
                "document_revision_id": document_revision_id,
                "original_filename": original_filename,
                "source_pdf_sha256": source_hash,
                "source_pdf_bytes": source_bytes,
                "renderer": PdfDocumentReviewRendererIdentity(
                    pdfinfo_sha256=sha256_file(self.pdfinfo),
                    pdftoppm_sha256=sha256_file(self.pdftoppm),
                ).model_dump(mode="json"),
                "page_count": page_count,
                "pages": [page.model_dump(mode="json") for page in pages],
            }
            manifest_value["manifest_sha256"] = content_sha256(manifest_value)
            manifest = PdfDocumentReviewIntakeManifest.model_validate(manifest_value)
            validate_contract(
                "pdf-document-review-intake-manifest",
                manifest.model_dump(mode="json"),
            )
            manifest_path = workspace / "document-manifest.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
            manifest_path.chmod(0o600)
            files = {
                "document-manifest.json": manifest_path,
                "source/original.pdf": source_target,
                **{page.member_path: workspace / page.member_path for page in manifest.pages},
            }
            file_metadata = {
                "document-manifest.json": {
                    "media_type": "application/json",
                    "schema_ref": (
                        "eom://schemas/document-review/pdf-document-review-intake-manifest/1.0"
                    ),
                },
                "source/original.pdf": {
                    "media_type": "application/pdf",
                    "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
                },
                **{
                    page.member_path: {
                        "media_type": "image/png",
                        "schema_ref": "eom://schemas/document-review/pdf-page-render/1.0",
                    }
                    for page in manifest.pages
                },
            }
            expected_hashes = {
                "document-manifest.json": sha256_file(manifest_path),
                "source/original.pdf": source_hash,
                **{page.member_path: page.sha256 for page in manifest.pages},
            }
            artifact = self.artifacts.commit_file_set(
                files=files,
                primary_file="document-manifest.json",
                artifact_type="pdf-document-review-source",
                idempotency_key=f"pdf-document-review-source:{idempotency_key}",
                request={
                    "document_id": document_id,
                    "document_revision_id": document_revision_id,
                    "source_pdf_sha256": source_hash,
                    "original_filename": original_filename,
                    "actor_id": actor_id,
                    "renderer": manifest.renderer.model_dump(mode="json"),
                },
                result={
                    "document_id": document_id,
                    "document_revision_id": document_revision_id,
                    "source_pdf_sha256": source_hash,
                    "page_count": page_count,
                    "manifest_sha256": manifest.manifest_sha256,
                },
                file_metadata=file_metadata,
                manifest_version="pdf-document-review-file-set/1.0",
                protocol_version=PDF_DOCUMENT_REVIEW_PROTOCOL_VERSION,
                protocol_schema_hash=PDF_DOCUMENT_REVIEW_SCHEMA_HASH,
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
        if (
            files != expected_hashes
            or artifact.content_hash != expected_hashes["document-manifest.json"]
        ):
            raise PdfDocumentReviewIntakeError(
                "PDF_DOCUMENT_REVIEW_ARTIFACT_REPLAY_MISMATCH",
                "Committed PDF review Artifact differs from the exact intake",
            )

    @staticmethod
    def _document_pointer(
        artifact: CatalogArtifact,
        manifest: PdfDocumentReviewIntakeManifest,
    ) -> PdfReviewDocumentPointer:
        source_pointer = PdfReviewArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="source/original.pdf",
            sha256=manifest.source_pdf_sha256,
            schema_ref="eom://schemas/document-review/pdf-source/1.0",
            media_type="application/pdf",
            content_length=manifest.source_pdf_bytes,
        )
        return PdfReviewDocumentPointer(
            document_id=manifest.document_id,
            document_revision_id=manifest.document_revision_id,
            original_filename=manifest.original_filename,
            source_pdf=source_pointer,
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
