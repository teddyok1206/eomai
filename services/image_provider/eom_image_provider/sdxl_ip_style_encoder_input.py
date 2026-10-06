"""Pinned CPU CLIP normalization, not source authority, encoder weights or image generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from eom_image_contracts.models import ImageEvaluationArtifactMember, Sha256
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from PIL import Image
from pydantic import TypeAdapter

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_pixels import PreparedSdxlIpStylePixels

NUMPY_VERSION = "2.4.6"
CLIP_BATCH_SHAPE = (1, 3, 224, 224)


@dataclass(frozen=True, slots=True)
class PreparedSdxlIpStyleEncoderInput:
    source: ImageEvaluationArtifactMember
    preprocessing: SdxlIpStylePreprocessing
    source_rgb_sha256: str
    shape: tuple[int, int, int, int]
    float32_le_bytes: bytes
    float32_le_sha256: str


def _clip_processor(profile: SdxlIpStylePreprocessing) -> Any:
    # Direct slow constructor: never a Hub lookup or a default fast processor.
    # The optional pinned runtime is deliberately absent from the light type-check environment.
    from transformers.models.clip.image_processing_clip import (  # type: ignore[import-not-found]
        CLIPImageProcessor,
    )

    return CLIPImageProcessor(
        do_resize=False,
        do_center_crop=False,
        do_convert_rgb=False,
        do_rescale=True,
        rescale_factor=profile.rescale_factor,
        do_normalize=True,
        image_mean=list(profile.image_mean),
        image_std=list(profile.image_std),
    )


def prepare_sdxl_ip_style_encoder_input(
    prepared: PreparedSdxlIpStylePixels,
    *,
    sample: SdxlNativeLoraSample,
    expected_rgb_sha256: Sha256,
) -> PreparedSdxlIpStyleEncoderInput:
    """The caller admits TRAIN lineage first; compare the planned pixel trace before processing."""
    try:
        sample = SdxlNativeLoraSample.model_validate(sample.model_dump(mode="json"))
        source = ImageEvaluationArtifactMember.model_validate(
            prepared.source.model_dump(mode="json")
        )
        profile = SdxlIpStylePreprocessing.model_validate(
            prepared.preprocessing.model_dump(mode="json")
        )
        expected = TypeAdapter(Sha256).validate_python(expected_rgb_sha256)
        if source != sample.source_image or not isinstance(prepared.rgb_bytes, bytes):
            raise ValueError("SDXL_IP_STYLE_ENCODER_SOURCE_INVALID")
        if len(prepared.rgb_bytes) != 224 * 224 * 3:
            raise ValueError("SDXL_IP_STYLE_ENCODER_RGB_BOUND_INVALID")
        rgb_sha = "sha256:" + hashlib.sha256(prepared.rgb_bytes).hexdigest()
        if rgb_sha != expected or rgb_sha != prepared.rgb_sha256:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        for package, version in (
            ("Pillow", profile.pillow_version),
            ("transformers", profile.transformers_version),
            ("numpy", NUMPY_VERSION),
        ):
            if metadata.version(package) != version:
                raise ValueError("SDXL_IP_STYLE_ENCODER_RUNTIME_VERSION_MISMATCH")
        import numpy as np

        processor = _clip_processor(profile)
        with Image.frombytes("RGB", (224, 224), prepared.rgb_bytes) as image:
            batch = processor(
                images=image,
                return_tensors="np",
                input_data_format="channels_last",
                data_format="channels_first",
            )["pixel_values"]
        if (
            not isinstance(batch, np.ndarray)
            or batch.shape != CLIP_BATCH_SHAPE
            or batch.dtype != np.dtype("float32")
            or not np.isfinite(batch).all()
        ):
            raise ValueError("SDXL_IP_STYLE_ENCODER_BATCH_INVALID")
        encoded = np.ascontiguousarray(batch, dtype="<f4").tobytes(order="C")
        return PreparedSdxlIpStyleEncoderInput(
            source,
            profile,
            rgb_sha,
            CLIP_BATCH_SHAPE,
            encoded,
            "sha256:" + hashlib.sha256(encoded).hexdigest(),
        )
    except (
        ValueError,
        TypeError,
        OSError,
        KeyError,
        ImportError,
        metadata.PackageNotFoundError,
    ) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
