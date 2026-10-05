"""Offline native-region PDF renderer; no model, database, NAS or orchestration behavior."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
import sys
import warnings
import zipfile

from eom_image_contracts import content_json_bytes
from eom_image_contracts.source_page_crops import ScienceSourcePageCropMember
from eom_image_contracts.source_pdf_crops import (
    NativeSourcePdfRenderRegion,
    NativeSourcePdfRenderRequest,
    NativeSourcePdfRenderResult,
    native_source_pdf_crop_dimensions,
    validate_native_source_pdf_render_result,
)
from eom_image_contracts.validation import validate_contract
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image
from PIL import __version__ as pillow_version
from pydantic import ValidationError as PydanticValidationError

from eom_image_trainer.crop_processing import average_hash, png_bytes

MAX_REQUEST_BYTES = 16 * 1024
MAX_PNG_BYTES = 8 * 1024**2


class NativePdfRenderError(ValueError):
    """A fixed technical code; never expose untrusted PDF/renderer output in an error."""


def _verify_renderer(request: NativeSourcePdfRenderRequest) -> None:
    descriptor = os.open(request.renderer.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= 4 * 1024**2
        ):
            raise NativePdfRenderError("NATIVE_PDF_RENDER_TOOL_INVALID")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 256 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or ("sha256:" + digest.hexdigest() != request.renderer.sha256):
            raise NativePdfRenderError("NATIVE_PDF_RENDER_TOOL_MISMATCH")
    finally:
        os.close(descriptor)
    version = subprocess.run(
        [request.renderer.path, "-v"], capture_output=True, check=False, timeout=5
    )
    if version.returncode != 0 or (
        len(version.stdout) + len(version.stderr) > 16 * 1024
        or not (version.stdout + version.stderr).startswith(
            ("pdftoppm version " + request.renderer.version + "\n").encode("ascii")
        )
    ):
        raise NativePdfRenderError("NATIVE_PDF_RENDER_TOOL_VERSION_MISMATCH")


def _render_region(
    request: NativeSourcePdfRenderRequest, region: NativeSourcePdfRenderRegion, pdf: bytes
) -> tuple[ScienceSourcePageCropMember, bytes]:
    width, height = native_source_pdf_crop_dimensions(region)
    left, top, _right, _bottom = region.pixel_box
    completed = subprocess.run(
        [
            request.renderer.path,
            "-f",
            str(region.physical_page),
            "-l",
            str(region.physical_page),
            "-singlefile",
            "-r",
            str(request.render_dpi),
            "-x",
            str(left * 4),
            "-y",
            str(top * 4),
            "-W",
            str(width),
            "-H",
            str(height),
            "-png",
            "-",
        ],
        input=pdf,
        capture_output=True,
        check=False,
        timeout=15,
    )
    raw = completed.stdout
    if (
        completed.returncode != 0
        or not 64 <= len(raw) <= MAX_PNG_BYTES
        or (len(completed.stderr) > 64 * 1024)
    ):
        raise NativePdfRenderError("NATIVE_PDF_RENDER_TOOL_FAILED")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.format != "PNG"
                or image.mode != "RGB"
                or getattr(image, "n_frames", 1) != 1
                or image.size != (width, height)
            ):
                raise NativePdfRenderError("NATIVE_PDF_RENDER_PNG_INVALID")
            image.load()
            # Serialize exact decoded RGB pixels; no resize, mask, threshold or enhancement.
            image.info.clear()
            payload = png_bytes(image)
            perceptual_hash, _ = average_hash(image)
    member = ScienceSourcePageCropMember(
        selection_id=region.selection_id,
        member_path="crops/" + region.selection_id + ".png",
        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        width_px=width,
        height_px=height,
        perceptual_hash=perceptual_hash,
    )
    return member, payload


def render_native_source_pdf(request: NativeSourcePdfRenderRequest, pdf: bytes) -> bytes:
    """Validate one typed request/source, render at most three frames, return one closed ZIP."""
    validate_contract("science-source-pdf-render-request", request.model_dump(mode="json"))
    request = NativeSourcePdfRenderRequest.model_validate(request.model_dump(mode="json"))
    if pillow_version != request.pillow_version:
        raise NativePdfRenderError("NATIVE_PDF_RENDER_PILLOW_MISMATCH")
    if (
        len(pdf) != request.source.bytes
        or not pdf.startswith(b"%PDF-")
        or ("sha256:" + hashlib.sha256(pdf).hexdigest() != request.source.pdf.sha256)
    ):
        raise NativePdfRenderError("NATIVE_PDF_RENDER_SOURCE_BYTES_MISMATCH")
    try:
        _verify_renderer(request)
        outputs = tuple(_render_region(request, region, pdf) for region in request.regions)
    except (OSError, subprocess.TimeoutExpired, Image.DecompressionBombWarning) as exc:
        raise NativePdfRenderError("NATIVE_PDF_RENDER_UNAVAILABLE") from exc
    result = NativeSourcePdfRenderResult(
        schema_version="local-image-science-source-pdf-render-result/1.0",
        request_sha256=request.request_sha256,
        members=tuple(member for member, _payload in outputs),
        activation_policy="FORBIDDEN",
    )
    validate_native_source_pdf_render_result(request, result)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("result.json", content_json_bytes(result.model_dump(mode="json")))
        for member, payload in outputs:
            archive.writestr(member.member_path, payload)
    return stream.getvalue()


def main() -> None:
    try:
        if len(sys.argv) != 2 or len(sys.argv[1].encode("utf-8")) > MAX_REQUEST_BYTES:
            raise NativePdfRenderError("NATIVE_PDF_RENDER_REQUEST_INVALID")
        raw = sys.argv[1].encode("utf-8")
        request = NativeSourcePdfRenderRequest.model_validate_json(raw)
        if content_json_bytes(request.model_dump(mode="json")) != raw:
            raise NativePdfRenderError("NATIVE_PDF_RENDER_REQUEST_NONCANONICAL")
        pdf = sys.stdin.buffer.read(request.source.bytes + 1)
        sys.stdout.buffer.write(render_native_source_pdf(request, pdf))
    except (ValueError, JsonSchemaValidationError, PydanticValidationError, OSError) as exc:
        code = str(exc) if isinstance(exc, NativePdfRenderError) else "NATIVE_PDF_RENDER_FAILED"
        print(code, file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
