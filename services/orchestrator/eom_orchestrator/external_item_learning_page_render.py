"""Render one pinned creative preview PDF into bounded, local worker page inputs.

The caller owns Artifact publication. This adapter never writes to NAS or changes
Item/Graph state, and it leaves its exclusive workspace available for audit.
"""

from __future__ import annotations

import os
import stat
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.external_item_learning_pages import (
    EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA,
    ExternalItemLearningPageSet,
    validate_external_item_learning_page_set_for_source,
)
from eom_catalog_contracts.external_item_learning_result import (
    validate_external_item_learning_result_for_source,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file

from eom_orchestrator.pdf_render_isolation import PDF_RENDER_SANDBOX

_MAX_PDF_BYTES = 256 * 1024 * 1024
_MAX_PAGE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_PAGE_BYTES = 256 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class RenderedExternalItemLearningPages:
    manifest: ExternalItemLearningPageSet
    workspace: Path
    manifest_path: Path
    page_paths: tuple[Path, ...]


class PdfToolRunner(Protocol):
    def __call__(
        self,
        executable: Path,
        arguments: tuple[str, ...],
        pdf_bytes: bytes,
        *,
        timeout_seconds: float,
        maximum_stdout: int,
    ) -> bytes: ...


def _trusted_executable(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise ValueError("CREATIVE_PAGE_RENDERER_UNAVAILABLE") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise ValueError("CREATIVE_PAGE_RENDERER_UNTRUSTED")
    return resolved


def _run_isolated(
    executable: Path,
    arguments: tuple[str, ...],
    pdf_bytes: bytes,
    *,
    timeout_seconds: float,
    maximum_stdout: int,
) -> bytes:
    """Parse the untrusted PDF only in the existing eom-image systemd sandbox."""

    command = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--unit=eom-creative-pdf-" + uuid4().hex[:20],
        "--uid=eom-image",
        "--gid=eom-image",
        "--service-type=exec",
    ]
    command.extend(flag for value in PDF_RENDER_SANDBOX for flag in ("--property", value))
    # One invocation handles up to 32 pages; the existing crop renderer keeps its
    # shorter 45-second bound while this source-only page set gets a bounded 120s.
    command.extend(("--property", "RuntimeMaxSec=120"))
    command.extend(("--", str(executable), *arguments))
    try:
        completed = subprocess.run(
            command,
            input=pdf_bytes,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("CREATIVE_PAGE_RENDERER_FAILED") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > maximum_stdout
        or len(completed.stderr) > 64 * 1024
    ):
        raise ValueError("CREATIVE_PAGE_RENDERER_FAILED")
    return completed.stdout


def _page_count(pdfinfo: Path, pdf_bytes: bytes, run: PdfToolRunner) -> int:
    raw = run(
        pdfinfo,
        ("-",),
        pdf_bytes,
        timeout_seconds=35.0,
        maximum_stdout=256 * 1024,
    )
    try:
        fields = {
            key.strip(): value.strip()
            for line in raw.decode("utf-8", errors="strict").splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
    except UnicodeError as exc:
        raise ValueError("CREATIVE_PAGE_PDF_INFO_INVALID") from exc
    if fields.get("Encrypted", "no").split(maxsplit=1)[0].lower() != "no":
        raise ValueError("CREATIVE_PAGE_PDF_ENCRYPTED")
    count = fields.get("Pages", "")
    if not count.isdigit() or not 1 <= int(count) <= 32:
        raise ValueError("CREATIVE_PAGE_COUNT_UNSUPPORTED")
    return int(count)


def _png_dimensions_and_size(path: Path, *, minimum_dimension: int = 64) -> tuple[int, int, int]:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 24 <= metadata.st_size <= _MAX_PAGE_BYTES
        ):
            raise ValueError("CREATIVE_PAGE_PNG_INVALID")
        with path.open("rb") as source:
            header = source.read(26)
    except OSError as exc:
        raise ValueError("CREATIVE_PAGE_PNG_INVALID") from exc
    if header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("CREATIVE_PAGE_PNG_INVALID")
    width, height = struct.unpack(">II", header[16:24])
    if (
        not minimum_dimension <= width <= 2400
        or not minimum_dimension <= height <= 2400
        or header[24] != 8
    ):
        raise ValueError("CREATIVE_PAGE_PNG_DIMENSIONS_INVALID")
    return width, height, metadata.st_size


def _split_png_stream(payload: bytes, *, expected_pages: int) -> tuple[memoryview, ...]:
    """Split one bounded Poppler stdout into exactly the expected PNG frames."""

    if not payload or len(payload) > _MAX_TOTAL_PAGE_BYTES:
        raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
    view = memoryview(payload)
    frames: list[memoryview] = []
    cursor = 0
    while cursor < len(view):
        start = cursor
        if len(view) - cursor < 8 or view[cursor : cursor + 8] != _PNG_SIGNATURE:
            raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
        cursor += 8
        seen_header = False
        seen_image = False
        while True:
            if cursor + 12 > len(view):
                raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
            length = struct.unpack_from(">I", view, cursor)[0]
            end = cursor + length + 12
            if end > len(view) or end - start > _MAX_PAGE_BYTES:
                raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
            kind = bytes(view[cursor + 4 : cursor + 8])
            actual_crc = zlib.crc32(view[cursor + 4 : end - 4])
            expected_crc = struct.unpack_from(">I", view, end - 4)[0]
            if actual_crc != expected_crc:
                raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
            if kind == b"IHDR":
                if seen_header or cursor != start + 8 or length != 13:
                    raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
                seen_header = True
            elif kind == b"IDAT":
                if not seen_header:
                    raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
                seen_image = True
            elif kind == b"IEND":
                if length != 0 or not seen_header or not seen_image:
                    raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
                cursor = end
                frames.append(view[start:cursor])
                break
            cursor = end
        if len(frames) > expected_pages:
            raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
    if len(frames) != expected_pages:
        raise ValueError("CREATIVE_PAGE_STREAM_INVALID")
    return tuple(frames)


def render_external_item_learning_pages(
    source: ExternalItemLearningSource,
    pdf_bytes: bytes,
    *,
    workspace: Path,
    pdfinfo: Path = Path("/usr/bin/pdfinfo"),
    pdftoppm: Path = Path("/usr/bin/pdftoppm"),
    run: PdfToolRunner = _run_isolated,
) -> RenderedExternalItemLearningPages:
    """Create an exact, bounded page set from the already-authorized PDF bytes."""

    if (
        not workspace.is_absolute()
        or os.path.lexists(workspace)
        or not 8 <= len(pdf_bytes) <= _MAX_PDF_BYTES
        or not pdf_bytes.startswith(b"%PDF-")
        or sha256_bytes(pdf_bytes) != source.preview_manifest.pdf_sha256
    ):
        raise ValueError("CREATIVE_PAGE_SOURCE_INVALID")
    info_executable = _trusted_executable(pdfinfo)
    render_executable = _trusted_executable(pdftoppm)
    try:
        workspace.mkdir(mode=0o700)
        page_directory = workspace / "pages"
        page_directory.mkdir(mode=0o700)
    except OSError as exc:
        raise ValueError("CREATIVE_PAGE_WORKSPACE_INVALID") from exc
    count = _page_count(info_executable, pdf_bytes, run)
    pages: list[dict[str, object]] = []
    page_paths: list[Path] = []
    total_bytes = 0
    rendered = run(
        render_executable,
        ("-f", "1", "-l", str(count), "-png", "-scale-to", "2400", "-"),
        pdf_bytes,
        timeout_seconds=90.0,
        maximum_stdout=_MAX_TOTAL_PAGE_BYTES,
    )
    for physical_page, payload in enumerate(
        _split_png_stream(rendered, expected_pages=count), start=1
    ):
        output = page_directory / f"page-{physical_page:04d}.png"
        try:
            descriptor = os.open(
                output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
        except OSError as exc:
            raise ValueError("CREATIVE_PAGE_OUTPUT_INVALID") from exc
        width, height, content_length = _png_dimensions_and_size(output)
        total_bytes += content_length
        if total_bytes > _MAX_TOTAL_PAGE_BYTES:
            raise ValueError("CREATIVE_PAGE_TOTAL_BYTES_EXCEEDED")
        pages.append(
            {
                "physical_page": physical_page,
                "member_path": f"pages/page-{physical_page:04d}.png",
                "sha256": sha256_file(output),
                "content_length": content_length,
                "width_px": width,
                "height_px": height,
            }
        )
        page_paths.append(output)
    if {path.name for path in page_directory.iterdir()} != {path.name for path in page_paths}:
        raise ValueError("CREATIVE_PAGE_OUTPUT_CLOSURE_INVALID")
    value: dict[str, object] = {
        "schema_version": "external-item-learning-page-set/1.0",
        "source_input_sha256": source.input_sha256,
        "preview_artifact_id": source.preview_artifact_id,
        "preview_artifact_revision_id": source.preview_artifact_revision_id,
        "preview_pdf_sha256": source.preview_manifest.pdf_sha256,
        "renderer": {
            "profile": "PDFTOPPM_PNG_SCALE_2400_V1",
            "pdfinfo_sha256": sha256_file(info_executable),
            "pdftoppm_sha256": sha256_file(render_executable),
        },
        "pages": pages,
    }
    value["manifest_sha256"] = content_sha256(value)
    validate_contract(EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA, value)
    manifest = ExternalItemLearningPageSet.model_validate(value)
    validate_external_item_learning_page_set_for_source(manifest, source)
    manifest_path = workspace / "page-set-manifest.json"
    descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(canonical_json_bytes(manifest.model_dump(mode="json")))
        target.flush()
        os.fsync(target.fileno())
    return RenderedExternalItemLearningPages(manifest, workspace, manifest_path, tuple(page_paths))


@dataclass(frozen=True, slots=True)
class RenderedCreativeSourceVisual:
    source_region_id: str
    physical_page: int
    source_page_sha256: str
    pixel_box: tuple[int, int, int, int]
    member_path: str
    path: Path
    sha256: str
    width_px: int
    height_px: int
    content_length: int


def render_creative_source_visuals(
    source: ExternalItemLearningSource,
    pages: ExternalItemLearningPageSet,
    result: ExternalItemLearningResultV2,
    pdf_bytes: bytes,
    *,
    workspace: Path,
    pdftoppm: Path = Path("/usr/bin/pdftoppm"),
    run: PdfToolRunner = _run_isolated,
) -> tuple[RenderedCreativeSourceVisual, ...]:
    """Render only declared target crops through the existing isolated PDF tool.

    This local adapter does not publish files, grant source access, or register an
    Item. The owner validates actual source/role/page Artifact pointers before it
    calls here and publishes the returned files with their derivation receipt.
    PDF bytes and the executable are hashed once per bounded crop set. Repeated
    references to one observed region share one output member.
    """
    source = ExternalItemLearningSource.model_validate(source.model_dump(mode="json"))
    pages = ExternalItemLearningPageSet.model_validate(pages.model_dump(mode="json"))
    result = ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json"))
    validate_external_item_learning_page_set_for_source(pages, source)
    validate_external_item_learning_result_for_source(
        result,
        source.input_sha256,
        source.source_id,
        source.source_revision_id,
        source.external_number,
    )
    if (
        not workspace.is_absolute()
        or os.path.lexists(workspace)
        or not 8 <= len(pdf_bytes) <= _MAX_PDF_BYTES
        or not pdf_bytes.startswith(b"%PDF-")
        or sha256_bytes(pdf_bytes) != source.preview_manifest.pdf_sha256
        or result.proposal is None
    ):
        raise ValueError("CREATIVE_VISUAL_CROP_INPUT_INVALID")
    selected = dict.fromkeys(
        block.source_region_id
        for block in result.proposal.content.body
        if isinstance(block, SourceImageBlock)
    )
    if not selected:
        return ()
    page_by_number = {page.physical_page: page for page in pages.pages}
    regions = {region.region_id: region for region in result.regions}
    recipes = []
    for region_id in selected:
        region = regions[region_id]
        page = page_by_number.get(region.physical_page)
        if page is None:
            raise ValueError("CREATIVE_VISUAL_CROP_PAGE_MISSING")
        box = region.bounding_box
        pixel_box = (
            box.left * page.width_px // 10000,
            box.top * page.height_px // 10000,
            (box.right * page.width_px + 9999) // 10000,
            (box.bottom * page.height_px + 9999) // 10000,
        )
        recipes.append((region, page, pixel_box))
    executable = _trusted_executable(pdftoppm)
    if sha256_file(executable) != pages.renderer.pdftoppm_sha256:
        raise ValueError("CREATIVE_VISUAL_CROP_RENDERER_CHANGED")
    workspace.mkdir(mode=0o700)
    images = workspace / "images"
    images.mkdir(mode=0o700)
    outputs = []
    total = 0
    for region, page, pixel_box in recipes:
        left, top, right, bottom = pixel_box
        width, height = right - left, bottom - top
        raw = run(
            executable,
            (
                "-f",
                str(region.physical_page),
                "-l",
                str(region.physical_page),
                "-png",
                "-singlefile",
                "-scale-to",
                "2400",
                "-x",
                str(left),
                "-y",
                str(top),
                "-W",
                str(width),
                "-H",
                str(height),
                "-",
            ),
            pdf_bytes,
            timeout_seconds=90.0,
            maximum_stdout=_MAX_PAGE_BYTES,
        )
        frames = _split_png_stream(raw, expected_pages=1)
        total += len(raw)
        if total > _MAX_TOTAL_PAGE_BYTES:
            raise ValueError("CREATIVE_VISUAL_CROP_TOTAL_BYTES_EXCEEDED")
        member = "images/" + region.region_id + ".png"
        path = workspace / member
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(frames[0])
            stream.flush()
            os.fsync(stream.fileno())
        actual_width, actual_height, content_length = _png_dimensions_and_size(
            path, minimum_dimension=1
        )
        if (actual_width, actual_height) != (width, height):
            raise ValueError("CREATIVE_VISUAL_CROP_DIMENSIONS_MISMATCH")
        outputs.append(
            RenderedCreativeSourceVisual(
                region.region_id,
                region.physical_page,
                page.sha256,
                pixel_box,
                member,
                path,
                sha256_bytes(raw),
                width,
                height,
                content_length,
            )
        )
    return tuple(outputs)
