"""Deterministic, fail-closed PDF overlays for document-review findings."""

from __future__ import annotations

import re
import stat
import subprocess
from array import array
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts import (
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationRole,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationRenderer,
    DocumentReviewPdfAnnotationRendererV2,
    DocumentReviewPdfAnnotationRendererV3,
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
    presentation_style: Literal["LEGACY_BOXES", "READABLE_MARGIN_GUIDES_V1"] = "LEGACY_BOXES",
    primary_anchor_ids: frozenset[str] = frozenset(),
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
    layout_document: Any | None = None
    overlay_pages: list[Path] = []
    overlay_root = destination.parent / f".{destination.stem}.overlays"
    overlay_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        if presentation_style == "READABLE_MARGIN_GUIDES_V1":
            if not primary_anchor_ids.issubset({value.anchor_id for value in annotations}):
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_PRIMARY_INVALID",
                    "A primary annotation is not in the validated mark set",
                )
            pymupdf, _, _ = _pymupdf_runtime()
            layout_document = pymupdf.open(str(source))
            if layout_document.page_count != page_count:
                raise DocumentReviewPdfAnnotationError(
                    "DOCUMENT_REVIEW_ANNOTATION_PAGE_COUNT_MISMATCH",
                    "The layout source PDF page count differs",
                )
        for page_number in range(1, page_count + 1):
            width, height = _pdf_page_size(source, page_number)
            svg = overlay_root / f"page-{page_number:04d}.svg"
            overlay = overlay_root / f"page-{page_number:04d}.pdf"
            page_marks = tuple(by_page.get(page_number, ()))
            if layout_document is None:
                overlay_svg = _overlay_svg(width, height, page_marks)
            else:
                page = layout_document[page_number - 1]
                if abs(page.cropbox.width - width) > 0.1 or abs(page.cropbox.height - height) > 0.1:
                    raise DocumentReviewPdfAnnotationError(
                        "DOCUMENT_REVIEW_ANNOTATION_GEOMETRY_INVALID",
                        "The PDF display geometry differs from its rendered page",
                    )
                overlay_svg = _readable_overlay_svg(
                    page.rect.width,
                    page.rect.height,
                    page_marks,
                    primary_anchor_ids,
                    _page_ink_grid(page, pymupdf) if page_marks else None,
                )
            svg.write_text(overlay_svg, encoding="utf-8")
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
        if layout_document is not None:
            layout_document.close()
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
    presentation_style: Literal["LEGACY_BOXES", "READABLE_MARGIN_GUIDES_V1"] = "LEGACY_BOXES",
) -> DocumentReviewPdfAnnotationRendererV2 | DocumentReviewPdfAnnotationRendererV3:
    """Render visible boxes plus standard PDF annotations for viewer comment panels."""

    base_identity = annotate_pdf(
        source,
        destination,
        role=role,
        page_count=page_count,
        annotations=annotations,
        presentation_style=presentation_style,
        primary_anchor_ids=(
            frozenset(value.descriptor.anchor_id for value in panel_comments)
            if presentation_style == "READABLE_MARGIN_GUIDES_V1"
            else frozenset()
        ),
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
                rect = _native_rect(
                    pymupdf,
                    page.rect,
                    value.region,
                )
                if presentation_style == "READABLE_MARGIN_GUIDES_V1":
                    rect = rect * page.derotation_matrix
                annotation = page.add_rect_annot(rect)
                annotation.set_border(width=0)
                annotation.set_colors(
                    stroke=(79 / 255, 70 / 255, 229 / 255)
                    if presentation_style == "READABLE_MARGIN_GUIDES_V1"
                    else (0.843137, 0.0, 0.082353)
                )
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
            presentation_style=presentation_style,
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
    renderer_type = (
        DocumentReviewPdfAnnotationRendererV3
        if presentation_style == "READABLE_MARGIN_GUIDES_V1"
        else DocumentReviewPdfAnnotationRendererV2
    )
    return renderer_type(
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


@dataclass(frozen=True)
class _InkGrid:
    width: int
    height: int
    page_width: float
    page_height: float
    prefix: array[int]

    def count(self, rect: tuple[float, float, float, float]) -> int:
        x0, y0, x1, y1 = rect
        left = max(0, min(self.width, int(x0 * self.width / self.page_width)))
        top = max(0, min(self.height, int(y0 * self.height / self.page_height)))
        right = max(left, min(self.width, int(x1 * self.width / self.page_width + 0.9999)))
        bottom = max(top, min(self.height, int(y1 * self.height / self.page_height + 0.9999)))
        stride = self.width + 1
        return int(
            self.prefix[bottom * stride + right]
            - self.prefix[top * stride + right]
            - self.prefix[bottom * stride + left]
            + self.prefix[top * stride + left]
        )


def _page_ink_grid(page: Any, pymupdf: Any) -> _InkGrid:
    if page.rect.width <= 0 or page.rect.height <= 0:
        raise DocumentReviewPdfAnnotationError(
            "DOCUMENT_REVIEW_ANNOTATION_GEOMETRY_INVALID",
            "The source PDF page has invalid display geometry",
        )
    scale = min(1.0, 1024.0 / max(page.rect.width, page.rect.height))
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        colorspace=pymupdf.csGRAY,
        alpha=False,
        annots=False,
    )
    width, height = pixmap.width, pixmap.height
    prefix = array("I", [0]) * ((width + 1) * (height + 1))
    samples = pixmap.samples
    for y in range(height):
        row_sum = 0
        row_start = y * pixmap.stride
        current = (y + 1) * (width + 1)
        previous = y * (width + 1)
        for x in range(width):
            row_sum += samples[row_start + x] < 245
            prefix[current + x + 1] = prefix[previous + x + 1] + row_sum
    return _InkGrid(width, height, page.rect.width, page.rect.height, prefix)


def _mark_rect(
    width: float,
    height: float,
    mark: DocumentReviewPdfAnnotationMark,
) -> tuple[float, float, float, float]:
    x0 = width * mark.region.x_ppm / 1_000_000
    y0 = height * mark.region.y_ppm / 1_000_000
    return (
        x0,
        y0,
        x0 + width * mark.region.width_ppm / 1_000_000,
        y0 + height * mark.region.height_ppm / 1_000_000,
    )


class _RowBins:
    """Small page-local spatial index for badge/region collision checks."""

    def __init__(self) -> None:
        self._rows: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)

    def add(self, rect: tuple[float, float, float, float]) -> None:
        for row in range(int(rect[1] // 24), int(max(rect[1], rect[3] - 0.001) // 24) + 1):
            self._rows[row].append(rect)

    def intersects(self, rect: tuple[float, float, float, float]) -> bool:
        for row in range(int(rect[1] // 24), int(max(rect[1], rect[3] - 0.001) // 24) + 1):
            for other in self._rows.get(row, ()):
                if (
                    rect[0] < other[2]
                    and rect[2] > other[0]
                    and rect[1] < other[3]
                    and rect[3] > other[1]
                ):
                    return True
        return False


def _readable_overlay_svg(
    width: float,
    height: float,
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...],
    primary_anchor_ids: frozenset[str],
    ink: _InkGrid | None,
) -> str:
    regions = _RowBins()
    region_rects: dict[str, tuple[float, float, float, float]] = {}
    boxes: list[str] = []
    for mark in annotations:
        rect = _mark_rect(width, height, mark)
        region_rects[mark.anchor_id] = rect
        regions.add(rect)
        stroke_width = "1.2" if mark.anchor_id not in primary_anchor_ids else "2.0"
        boxes.append(
            f'<rect x="{rect[0]:.4f}" y="{rect[1]:.4f}" '
            f'width="{rect[2] - rect[0]:.4f}" height="{rect[3] - rect[1]:.4f}" '
            f'fill="none" stroke="#4F46E5" stroke-opacity="0.65" '
            f'stroke-width="{stroke_width}"/>'
        )
    badges = _RowBins()
    leaders: list[str] = []
    labels: list[str] = []
    for mark in annotations:
        if mark.anchor_id not in primary_anchor_ids:
            continue
        x0, y0, x1, y1 = region_rects[mark.anchor_id]
        badge_width = max(18.0, 9.0 + 7.0 * len(str(mark.ordinal)))
        badge_height = 16.0
        candidates = (
            (x0 - badge_width - 4.0, y0),
            (x1 + 4.0, y0),
            (x0, y0 - badge_height - 4.0),
            (x0, y1 + 4.0),
            (2.0, y0),
            (width - badge_width - 2.0, y0),
            (2.0, y1 + 4.0),
            (width - badge_width - 2.0, y1 + 4.0),
        )
        choices: list[tuple[int, int, float, int, tuple[float, float, float, float]]] = []
        for order, (x, y) in enumerate(candidates):
            if x < 0 or y < 0 or x + badge_width > width or y + badge_height > height:
                continue
            rect = (x, y, x + badge_width, y + badge_height)
            collision = regions.intersects(rect) or badges.intersects(rect)
            ink_count = ink.count(rect) if ink is not None else 0
            distance = abs(x + badge_width / 2 - x0) + abs(y + badge_height / 2 - y0)
            choices.append((int(collision), ink_count, distance, order, rect))
        if not choices:
            raise DocumentReviewPdfAnnotationError(
                "DOCUMENT_REVIEW_ANNOTATION_GEOMETRY_INVALID",
                "The PDF page has no room for a review marker",
            )
        selected_collision, ink_count, _, _, selected = min(choices)
        badges.add(selected)
        center_x = selected[0] + badge_width / 2
        center_y = selected[1] + badge_height / 2
        leaders.append(
            f'<line x1="{center_x:.4f}" y1="{center_y:.4f}" '
            f'x2="{x0:.4f}" y2="{y0:.4f}" stroke="#4F46E5" '
            'stroke-opacity="0.48" stroke-width="0.8"/>'
        )
        # A hollow fallback badge obscures less text when no clear whitespace exists.
        clear = selected_collision == 0 and ink_count == 0
        fill = "#EEF2FF" if clear else "#FFFFFF"
        text_color = "#4338CA"
        labels.extend(
            (
                f'<rect x="{selected[0]:.4f}" y="{selected[1]:.4f}" '
                f'width="{badge_width:.4f}" height="{badge_height:.4f}" '
                f'rx="3" fill="{fill}" fill-opacity="0.58" stroke="#4F46E5" '
                'stroke-opacity="0.75" stroke-width="0.8"/>',
                f'<text x="{center_x:.4f}" y="{selected[1] + 12:.4f}" '
                'font-family="DejaVu Sans" font-size="10" font-weight="bold" '
                f'fill="{text_color}" text-anchor="middle">{mark.ordinal}</text>',
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.4f}pt" '
        f'height="{height:.4f}pt" '
        f'viewBox="0 0 {width:.4f} {height:.4f}">' + "".join(leaders + boxes + labels) + "</svg>\n"
    )


def _verify_native_panel_comments(
    pymupdf: Any,
    path: Path,
    *,
    page_count: int,
    expected: tuple[NativePanelCommentPayload, ...],
    presentation_style: Literal["LEGACY_BOXES", "READABLE_MARGIN_GUIDES_V1"] = "LEGACY_BOXES",
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
            if presentation_style == "READABLE_MARGIN_GUIDES_V1":
                expected_rect = expected_rect * page.derotation_matrix
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
