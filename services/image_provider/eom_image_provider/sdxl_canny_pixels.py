"""Optional, pinned OpenCV Canny; retains the existing SDXL reference placement."""

from __future__ import annotations

import io
from importlib import metadata
from typing import Protocol

from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy, SdxlCannyRuntime
from PIL import Image, ImageOps

from eom_image_provider.provider import ProviderError


class CannyPixels(Protocol):
    def __call__(
        self, gray: bytes, *, width: int, height: int, policy: SdxlCannyPolicy
    ) -> bytes: ...


def read_canny_runtime() -> SdxlCannyRuntime:
    """No model imports; package provenance is verified by the protected installer."""
    try:
        import cv2  # type: ignore[import-not-found]

        for conflicting in (
            "opencv-python",
            "opencv-contrib-python",
            "opencv-contrib-python-headless",
        ):
            try:
                metadata.version(conflicting)
            except metadata.PackageNotFoundError:
                continue
            raise ValueError("ambiguous cv2 namespace")
        return SdxlCannyRuntime.model_validate(
            dict(
                opencv_package_version=metadata.version("opencv-python-headless"),
                opencv_module_version=cv2.__version__,
                pillow_version=metadata.version("Pillow"),
                numpy_version=metadata.version("numpy"),
            )
        )
    except (ImportError, ValueError, metadata.PackageNotFoundError) as exc:
        raise ProviderError("SDXL_CANNY_RUNTIME_INVALID") from exc


def opencv_canny_pixels(gray: bytes, *, width: int, height: int, policy: SdxlCannyPolicy) -> bytes:
    try:
        import cv2
        import numpy as np

        if len(gray) != width * height:
            raise ValueError("Canny grayscale input size mismatch")
        # This oneshot is CPU-only even if an optional system OpenCL implementation exists.
        cv2.setNumThreads(1)
        cv2.ocl.setUseOpenCL(False)
        source = np.frombuffer(gray, dtype=np.uint8).reshape((height, width))
        edges = cv2.Canny(
            source,
            policy.threshold_low,
            policy.threshold_high,
            apertureSize=policy.aperture_size,
            L2gradient=policy.l2_gradient,
        )
        if edges.shape != (height, width) or edges.dtype != np.uint8:
            raise ValueError("Canny grayscale output shape/type mismatch")
        return bytes(edges.tobytes())
    except (ImportError, ValueError) as exc:
        raise ProviderError("SDXL_CANNY_EDGE_INVALID") from exc


def sdxl_canny_source_canvas(payload: bytes, *, policy: SdxlCannyPolicy) -> Image.Image:
    """One shared placement for edge extraction and a separate white-paper initializer."""
    return _source_canvas(
        payload, source_size=(policy.source_width_px, policy.source_height_px), policy=policy
    )


def sdxl_canny_native_source_canvas(
    payload: bytes, *, width_px: int, height_px: int
) -> Image.Image:
    """Reserved native crops are fitted, never relabeled as prepared TRAIN targets."""
    if not (32 <= width_px <= 4096 and 32 <= height_px <= 4096):
        raise ProviderError("SDXL_CANNY_INPUT_INVALID")
    return _source_canvas(payload, source_size=(width_px, height_px), policy=SdxlCannyPolicy())


def _source_canvas(
    payload: bytes, *, source_size: tuple[int, int], policy: SdxlCannyPolicy
) -> Image.Image:
    try:
        if not 0 < len(payload) <= 16 * 1024**2:
            raise ValueError("Canny input byte budget exceeded")
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.size != source_size
                or source.mode not in ("L", "RGB")
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ValueError("Canny source media/dimensions/mode mismatch")
            source.load()
            gray = source.convert("L")
        fitted = ImageOps.contain(
            gray, (policy.fit_width_px, policy.fit_height_px), Image.Resampling.LANCZOS
        )
        canvas = Image.new("L", (policy.width_px, policy.height_px), 255)
        canvas.paste(
            fitted,
            ((policy.width_px - fitted.width) // 2, (policy.height_px - fitted.height) // 2),
        )
        return canvas
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("SDXL_CANNY_INPUT_INVALID") from exc


def canny_conditioning_png(
    payload: bytes,
    *,
    policy: SdxlCannyPolicy,
    extractor: CannyPixels = opencv_canny_pixels,
) -> bytes:
    """Declared source materialization; no prompt, morphology rewrite or model path."""
    return canny_conditioning_canvas_png(
        sdxl_canny_source_canvas(payload, policy=policy), policy=policy, extractor=extractor
    )


def canny_conditioning_canvas_png(
    canvas: Image.Image, *, policy: SdxlCannyPolicy, extractor: CannyPixels = opencv_canny_pixels
) -> bytes:
    """Extract once from the exact initializer placement, with no second fit."""
    try:
        if canvas.mode != "L" or canvas.size != (policy.width_px, policy.height_px):
            raise ProviderError("SDXL_CANNY_INPUT_INVALID")
        edges = extractor(
            canvas.tobytes(), width=policy.width_px, height=policy.height_px, policy=policy
        )
        if len(edges) != policy.width_px * policy.height_px or set(edges) != {0, 255}:
            raise ProviderError("SDXL_CANNY_EDGE_INVALID")
        image = Image.frombytes("L", canvas.size, edges).convert("RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", compress_level=9)
        return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("SDXL_CANNY_INPUT_INVALID") from exc


def canny_png_edge_count(payload: bytes) -> int:
    """Receipt/media verification only; never re-extracts edges or claims quality."""
    try:
        if not 0 < len(payload) <= 16 * 1024**2:
            raise ValueError("Canny output byte budget exceeded")
        with Image.open(io.BytesIO(payload)) as image:
            if (
                image.format != "PNG"
                or image.size != (832, 512)
                or image.mode != "RGB"
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("Canny output media/dimensions/mode mismatch")
            image.load()
            red, green, blue = (channel.tobytes() for channel in image.split())
        if red != green or green != blue or set(red) != {0, 255}:
            raise ValueError("Canny output is not binary RGB")
        return int(red.count(255))
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("SDXL_CANNY_EDGE_INVALID") from exc
