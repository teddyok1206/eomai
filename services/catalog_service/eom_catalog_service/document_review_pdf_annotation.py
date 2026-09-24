"""Deterministic, fail-closed PDF overlays for document-review findings."""

from __future__ import annotations

import re
import stat
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationRole,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationRenderer,
    DocumentReviewPdfAnnotationRendererV2,
    DocumentReviewPdfPanelComment,
)
from eom_identifiers import sha256_bytes, sha256_file

QPDF = Path("/usr/bin/qpdf")
RSVG_CONVERT = Path("/usr/bin/rsvg-convert")
PDFINFO = Path("/usr/bin/pdfinfo")
MAX_ANNOTATED_PDF_BYTES = 512 * 1024 * 1024
_PAGE_SIZE = re.compile(
    r"^Page\s+[0-9]+\s+size:\s+([0-9]+(?:\.[0-9]+)?)\s+x\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s+pts(?:\s+\([^)]*\))?\s*$",
    re.MULTILINE,
)
_PAGE_COUNT = re.compile(r"^Pages:\s+([0-9]+)\s*$", re.MULTILINE)
_SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "SOURCE_DATE_EPOCH": "946684800",
}


class DocumentReviewPdfAnnotationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NativePanelCommentPayload:
    descriptor: DocumentReviewPdfPanelComment
    contents: str
    region: DocumentReviewAnnotationRegion


def renderer_identity() -> DocumentReviewPdfAnnotationRenderer:
    for executable in (QPDF, RSVG_CONVERT, PDFINFO):
        try:
            metadata = executable.stat()
        except OSError as exc:
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_RENDERER_UNAVAILABLE",
                "A required PDF annotation renderer is unavailable",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o022
        ):
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_RENDERER_UNTRUSTED",
                "A required PDF annotation renderer has unsafe metadata",
            )
    qpdf_version = _run((str(QPDF), "--version"), timeout=10).stdout.splitlines()[0]
    rsvg_version = _run((str(RSVG_CONVERT), "--version"), timeout=10).stdout.splitlines()[0]
    pdfinfo_version = _run((str(PDFINFO), "-v"), timeout=10).stderr.splitlines()[0]
    if (
        not qpdf_version.startswith("qpdf version 11.9.")
        or not rsvg_version.startswith("rsvg-convert version 2.58.")
        or not pdfinfo_version.startswith("pdfinfo version 24.02.")
    ):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_RENDERER_VERSION_UNSUPPORTED",
            "The installed PDF annotation renderer version is unsupported",
        )
    return DocumentReviewPdfAnnotationRenderer(
        qpdf_version=qpdf_version,
        qpdf_sha256=sha256_file(QPDF),
        rsvg_convert_version=rsvg_version,
        rsvg_convert_sha256=sha256_file(RSVG_CONVERT),
        pdfinfo_version=pdfinfo_version,
        pdfinfo_sha256=sha256_file(PDFINFO),
    )


def annotate_pdf(
    source: Path,
    destination: Path,
    *,
    role: DocumentReviewAnnotationRole,
    page_count: int,
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...],
) -> DocumentReviewPdfAnnotationRenderer:
    """Render role-local numbered rectangles and return the exact tool identity."""

    identity = renderer_identity()
    _require_regular_bounded_pdf(source)
    if any(value.document_role != role for value in annotations):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_ROLE_MISMATCH",
            "An annotation belongs to another document role",
        )
    metadata = _run((str(PDFINFO), str(source)), timeout=30).stdout
    match = _PAGE_COUNT.search(metadata)
    if match is None or int(match.group(1)) != page_count:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_PAGE_COUNT_MISMATCH",
            "The source PDF page count differs from its immutable pointer",
        )
    by_page: dict[int, list[DocumentReviewPdfAnnotationMark]] = defaultdict(list)
    for annotation in annotations:
        if not 1 <= annotation.page_number <= page_count:
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_PAGE_INVALID",
                "An annotation page is outside the source PDF",
            )
        by_page[annotation.page_number].append(annotation)
    overlay_pages: list[Path] = []
    overlay_root = destination.parent / f".{destination.stem}.overlays"
    overlay_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for page_number in range(1, page_count + 1):
            width, height = _pdf_page_size(source, page_number)
            svg = overlay_root / f"page-{page_number:04d}.svg"
            overlay = overlay_root / f"page-{page_number:04d}.pdf"
            svg.write_text(
                _overlay_svg(width, height, tuple(by_page.get(page_number, ()))),
                encoding="utf-8",
            )
            svg.chmod(0o600)
            _run(
                (
                    str(RSVG_CONVERT),
                    "--format=pdf",
                    f"--output={overlay}",
                    str(svg),
                ),
                timeout=30,
            )
            overlay.chmod(0o600)
            overlay_pages.append(overlay)
        combined = overlay_root / "combined.pdf"
        command = [str(QPDF), "--empty", "--pages"]
        for overlay in overlay_pages:
            command.extend((str(overlay), "1"))
        command.extend(("--", str(combined)))
        _run(tuple(command), timeout=60)
        combined.chmod(0o600)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _run(
            (
                str(QPDF),
                "--deterministic-id",
                str(source),
                "--overlay",
                str(combined),
                "--",
                str(destination),
            ),
            timeout=120,
        )
        destination.chmod(0o600)
        _require_regular_bounded_pdf(destination)
        _run((str(QPDF), "--check", str(destination)), timeout=60)
        sanitized = overlay_root / "sanitized.qdf.pdf"
        _run(
            (
                str(QPDF),
                "--qdf",
                "--object-streams=disable",
                str(destination),
                str(sanitized),
            ),
            timeout=120,
        )
        payload = sanitized.read_bytes()
        forbidden_tokens = (b"/Filespec", b"/EmbeddedFile", b"/GoToR", b"/Launch")
        if any(token in payload for token in forbidden_tokens):
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_EXTERNAL_REFERENCE_REJECTED",
                "The annotated PDF contains an external or embedded file reference",
            )
    finally:
        for child in overlay_root.iterdir() if overlay_root.exists() else ():
            child.unlink(missing_ok=True)
        overlay_root.rmdir()
    return identity


def annotate_pdf_with_native_comments(
    source: Path,
    destination: Path,
    *,
    role: DocumentReviewAnnotationRole,
    page_count: int,
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...],
    panel_comments: tuple[NativePanelCommentPayload, ...],
) -> DocumentReviewPdfAnnotationRendererV2:
    """Render visible boxes plus standard PDF annotations for viewer comment panels."""

    base_identity = annotate_pdf(
        source,
        destination,
        role=role,
        page_count=page_count,
        annotations=annotations,
    )
    if any(value.descriptor.document_role != role for value in panel_comments):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_ROLE_MISMATCH",
            "A native panel comment belongs to another document role",
        )
    pymupdf, pymupdf_module, pymupdf_native = _pymupdf_runtime()
    native_output = destination.parent / f".{destination.name}.native.pdf"
    try:
        document = pymupdf.open(str(destination))
        try:
            if document.page_count != page_count:
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_PAGE_COUNT_MISMATCH",
                    "The native annotation PDF page count differs",
                )
            for value in panel_comments:
                page = document[value.descriptor.page_number - 1]
                rect = _native_rect(pymupdf, page.rect, value.region)
                annotation = page.add_rect_annot(rect)
                annotation.set_border(width=0)
                annotation.set_colors(stroke=(0.843137, 0.0, 0.082353))
                annotation.set_info(
                    title="EOM 문서 검토",
                    subject=f"검토 #{value.descriptor.ordinal}",
                    content=value.contents,
                    creationDate="D:20000101000000Z",
                    modDate="D:20000101000000Z",
                )
                annotation.set_flags(4)
                document.xref_set_key(
                    annotation.xref,
                    "NM",
                    pymupdf.get_pdf_str(value.descriptor.comment_id),
                )
                annotation.update()
            document.save(
                str(native_output),
                garbage=4,
                clean=1,
                deflate=1,
                deflate_images=1,
                deflate_fonts=1,
                no_new_id=1,
                appearance=0,
                pretty=0,
                preserve_metadata=1,
                use_objstms=0,
            )
        finally:
            document.close()
        native_output.chmod(0o600)
        native_output.replace(destination)
        _require_regular_bounded_pdf(destination)
        _run((str(QPDF), "--check", str(destination)), timeout=60)
        _verify_native_panel_comments(
            pymupdf,
            destination,
            page_count=page_count,
            expected=panel_comments,
        )
        _reject_unsafe_pdf_references(destination, destination.parent)
    except DocumentReviewPdfAnnotationError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_FAILED",
            "The native PDF comment panel could not be created",
        ) from exc
    finally:
        native_output.unlink(missing_ok=True)
    return DocumentReviewPdfAnnotationRendererV2(
        qpdf_version=base_identity.qpdf_version,
        qpdf_sha256=base_identity.qpdf_sha256,
        rsvg_convert_version=base_identity.rsvg_convert_version,
        rsvg_convert_sha256=base_identity.rsvg_convert_sha256,
        pdfinfo_version=base_identity.pdfinfo_version,
        pdfinfo_sha256=base_identity.pdfinfo_sha256,
        pymupdf_version=str(pymupdf.__version__),
        pymupdf_module_sha256=sha256_file(pymupdf_module),
        pymupdf_native_sha256=sha256_file(pymupdf_native),
    )


def _pymupdf_runtime() -> tuple[Any, Path, Path]:
    try:
        pymupdf = import_module("pymupdf")
        native = import_module("pymupdf._extra")
        module_path = Path(str(pymupdf.__file__)).resolve(strict=True)
        native_path = Path(str(native.__file__)).resolve(strict=True)
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as exc:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_RENDERER_UNAVAILABLE",
            "The native PDF annotation renderer is unavailable",
        ) from exc
    for path in (module_path, native_path):
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o022
        ):
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_RENDERER_UNTRUSTED",
                "The native PDF annotation renderer has unsafe metadata",
            )
    if not str(pymupdf.__version__).startswith("1.26."):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_RENDERER_VERSION_UNSUPPORTED",
            "The installed native PDF annotation renderer version is unsupported",
        )
    return pymupdf, module_path, native_path


def _native_rect(pymupdf: Any, page_rect: Any, region: DocumentReviewAnnotationRegion) -> Any:
    x0 = page_rect.width * region.x_ppm / 1_000_000
    y0 = page_rect.height * region.y_ppm / 1_000_000
    x1 = x0 + page_rect.width * region.width_ppm / 1_000_000
    y1 = y0 + page_rect.height * region.height_ppm / 1_000_000
    return pymupdf.Rect(x0, y0, x1, y1)


def _verify_native_panel_comments(
    pymupdf: Any,
    path: Path,
    *,
    page_count: int,
    expected: tuple[NativePanelCommentPayload, ...],
) -> None:
    by_id = {value.descriptor.comment_id: value for value in expected}
    if len(by_id) != len(expected):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_INVALID",
            "Native PDF panel comment identities are not unique",
        )
    found: dict[str, tuple[int, int]] = {}
    document = pymupdf.open(str(path))
    try:
        if document.page_count != page_count:
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_PAGE_COUNT_MISMATCH",
                "The native annotation PDF page count differs",
            )
        for page_index in range(document.page_count):
            page = document[page_index]
            for annotation in page.annots() or ():
                identity = str(annotation.info.get("id") or "")
                if not identity.startswith("reviewcomment_"):
                    continue
                if identity in found:
                    raise DocumentReviewPdfAnnotationError(
                        "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_INVALID",
                        "A native PDF panel comment is duplicated",
                    )
                found[identity] = (page_index + 1, annotation.xref)
        if set(found) != set(by_id):
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_INVALID",
                "Native PDF panel comments differ from the canonical set",
            )
        for identity, value in by_id.items():
            page_number, annotation_xref = found[identity]
            page = document[page_number - 1]
            annotation = page.load_annot(annotation_xref)
            if annotation is None:
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_INVALID",
                    "A native PDF panel comment could not be reloaded",
                )
            info = annotation.info
            expected_rect = _native_rect(
                pymupdf,
                page.rect,
                value.region,
            )
            # PyMuPDF stores a fixed one-point rectangle difference (`/RD`) around Square
            # annotations even when the border width is zero.  The visible red box remains the
            # exact SVG overlay; verify this deterministic native hit-target expansion explicitly.
            expected_coordinates = (
                expected_rect.x0 - 1.0,
                expected_rect.y0 - 1.0,
                expected_rect.x1 + 1.0,
                expected_rect.y1 + 1.0,
            )
            actual_rect = annotation.rect
            coordinates_match = all(
                abs(float(actual) - float(wanted)) <= 0.05
                for actual, wanted in zip(actual_rect, expected_coordinates, strict=True)
            )
            if (
                annotation.type[1] != "Square"
                or page_number != value.descriptor.page_number
                or info.get("title") != "EOM 문서 검토"
                or info.get("subject") != f"검토 #{value.descriptor.ordinal}"
                or sha256_bytes(str(info.get("content") or "").encode("utf-8"))
                != value.descriptor.contents_sha256
                or len(str(info.get("content") or "").encode("utf-8"))
                != value.descriptor.contents_utf8_length
                or not coordinates_match
            ):
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_NATIVE_COMMENT_INVALID",
                    "A native PDF panel comment differs from its manifest descriptor",
                )
            raw_object = document.xref_object(annotation.xref, compressed=False)
            if any(token in raw_object for token in ("/A ", "/AA ", "/FS ", "/Dest ")):
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_EXTERNAL_REFERENCE_REJECTED",
                    "A native PDF panel comment contains an unsafe action",
                )
    finally:
        document.close()


def _reject_unsafe_pdf_references(path: Path, temporary_root: Path) -> None:
    sanitized = temporary_root / f".{path.name}.native.qdf.pdf"
    try:
        _run(
            (
                str(QPDF),
                "--qdf",
                "--object-streams=disable",
                str(path),
                str(sanitized),
            ),
            timeout=120,
        )
        payload = sanitized.read_bytes()
        forbidden_tokens = (
            b"/Filespec",
            b"/EmbeddedFile",
            b"/GoToR",
            b"/Launch",
            b"/JavaScript",
            b"/SubmitForm",
            b"/ImportData",
        )
        if any(token in payload for token in forbidden_tokens):
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_EXTERNAL_REFERENCE_REJECTED",
                "The annotated PDF contains an unsafe external action or file reference",
            )
    finally:
        sanitized.unlink(missing_ok=True)


def _pdf_page_size(source: Path, page_number: int) -> tuple[float, float]:
    result = _run(
        (str(PDFINFO), "-f", str(page_number), "-l", str(page_number), str(source)),
        timeout=30,
    )
    match = _PAGE_SIZE.search(result.stdout)
    if match is None:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_PAGE_GEOMETRY_INVALID",
            "The source PDF page geometry could not be resolved",
        )
    width, height = float(match.group(1)), float(match.group(2))
    if not 36 <= width <= 20_000 or not 36 <= height <= 20_000:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_PAGE_GEOMETRY_INVALID",
            "The source PDF page geometry is outside the supported bound",
        )
    return width, height


def _overlay_svg(
    width: float,
    height: float,
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...],
) -> str:
    shapes: list[str] = []
    for value in annotations:
        x = width * value.region.x_ppm / 1_000_000
        y = height * value.region.y_ppm / 1_000_000
        box_width = width * value.region.width_ppm / 1_000_000
        box_height = height * value.region.height_ppm / 1_000_000
        label_width = max(18.0, 9.0 + 7.0 * len(str(value.ordinal)))
        label_height = 16.0
        label_x = min(max(0.0, x), max(0.0, width - label_width))
        label_y = min(max(0.0, y - label_height), max(0.0, height - label_height))
        shapes.extend(
            (
                (
                    f'<rect x="{x:.4f}" y="{y:.4f}" width="{box_width:.4f}" '
                    f'height="{box_height:.4f}" fill="none" stroke="#D70015" '
                    'stroke-width="2.5"/>'
                ),
                (
                    f'<rect x="{label_x:.4f}" y="{label_y:.4f}" width="{label_width:.4f}" '
                    f'height="{label_height:.4f}" rx="3" fill="#D70015"/>'
                ),
                (
                    f'<text x="{label_x + label_width / 2:.4f}" y="{label_y + 12:.4f}" '
                    'font-family="DejaVu Sans" font-size="10" font-weight="bold" '
                    f'fill="#FFFFFF" text-anchor="middle">{value.ordinal}</text>'
                ),
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.4f}pt" '
        f'height="{height:.4f}pt" viewBox="0 0 {width:.4f} {height:.4f}">'
        + "".join(shapes)
        + "</svg>\n"
    )


def _require_regular_bounded_pdf(path: Path) -> None:
    try:
        metadata = path.lstat()
        with path.open("rb") as stream:
            header = stream.read(5)
    except OSError as exc:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_PDF_INVALID",
            "The PDF could not be read safely",
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 8 <= metadata.st_size <= MAX_ANNOTATED_PDF_BYTES
        or header != b"%PDF-"
    ):
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_PDF_INVALID",
            "The PDF is not a bounded regular file",
        )


def _run(command: tuple[str, ...], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**_SAFE_ENV, "HOME": "/nonexistent"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_RENDER_FAILED",
            "The PDF annotation renderer failed",
        ) from exc
