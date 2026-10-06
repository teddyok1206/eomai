"""Whole-frame style input preparation; neither source authorization nor model inference."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from importlib import metadata

from eom_image_contracts.models import ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from PIL import Image, ImageOps, UnidentifiedImageError

from eom_image_provider.provider import ProviderError

MAX_STYLE_PNG_BYTES = 8 * 1024**2


@dataclass(frozen=True, slots=True)
class PreparedSdxlIpStylePixels:
    source: ImageEvaluationArtifactMember
    preprocessing: SdxlIpStylePreprocessing
    fitted_size: tuple[int, int]
    offset: tuple[int, int]
    rgb_bytes: bytes
    rgb_sha256: str


def prepare_sdxl_ip_style_pixels(
    source_png: bytes,
    *,
    sample: SdxlNativeLoraSample,
    preprocessing: SdxlIpStylePreprocessing,
) -> PreparedSdxlIpStylePixels:
    """Caller admits exact TRAIN provenance first; this function only verifies/prepares pixels."""
    try:
        sample = SdxlNativeLoraSample.model_validate(sample.model_dump(mode="json"))
        preprocessing = SdxlIpStylePreprocessing.model_validate(
            preprocessing.model_dump(mode="json")
        )
        if metadata.version("Pillow") != preprocessing.pillow_version:
            raise ValueError("SDXL_IP_STYLE_PILLOW_VERSION_MISMATCH")
        if not isinstance(source_png, bytes) or not 0 < len(source_png) <= MAX_STYLE_PNG_BYTES:
            raise ValueError("SDXL_IP_STYLE_PIXEL_BYTES_INVALID")
        if "sha256:" + hashlib.sha256(source_png).hexdigest() != sample.source_image.sha256:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source_png)) as source:
                if (
                    source.format != "PNG"
                    or source.mode != "RGB"
                    or source.size != sample.width_height
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ValueError("SDXL_IP_STYLE_PIXEL_MEDIA_INVALID")
                source.load()
                fitted = ImageOps.contain(
                    source,
                    (preprocessing.width_px, preprocessing.height_px),
                    Image.Resampling.BICUBIC,
                )
        offset = (
            (preprocessing.width_px - fitted.width) // 2,
            (preprocessing.height_px - fitted.height) // 2,
        )
        fitted_size = fitted.size
        canvas = Image.new("RGB", (preprocessing.width_px, preprocessing.height_px), "white")
        try:
            canvas.paste(fitted, offset)
            rgb = canvas.tobytes()
        finally:
            canvas.close()
            fitted.close()
        return PreparedSdxlIpStylePixels(
            sample.source_image,
            preprocessing,
            fitted_size,
            offset,
            rgb,
            "sha256:" + hashlib.sha256(rgb).hexdigest(),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        metadata.PackageNotFoundError,
    ) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
