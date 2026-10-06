"""One bounded CFG tensor per case, cast once and checked before/after matched inference."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from eom_image_contracts.models import ImageEvaluationArtifactMember, Sha256
from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer, SdxlIpStylePreprocessing
from pydantic import TypeAdapter

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_encoder import (
    CFG_SHAPE,
    ENCODER_POLICY,
    PreparedSdxlIpStyleEmbedding,
)


@dataclass(frozen=True, slots=True)
class BoundSdxlIpStyleEmbedding:
    """Internal owned tensor handle, not wire identity, source admission or a global cache."""

    model: SdxlIpStyleModelPointer
    cfg_float32_le_sha256: str
    device: str
    dtype: str
    cast_sha256: str
    tensor: Any


def _tensor_sha256(torch: Any, tensor: Any) -> str:
    try:
        return _finite_tensor_sha256(torch, tensor)
    except torch.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc


def _finite_tensor_sha256(torch: Any, tensor: Any) -> str:
    if (
        not isinstance(tensor, torch.Tensor)
        or tuple(tensor.shape) != CFG_SHAPE
        or tensor.dtype not in (torch.float16, torch.float32)
        or tensor.requires_grad
        or not torch.isfinite(tensor).all().item()
        or torch.count_nonzero(tensor[0]).item() != 0
    ):
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
    raw = tensor.detach().cpu().contiguous().numpy().tobytes(order="C")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _cast_cfg_embedding(torch: Any, pixels: Any, pipeline: Any) -> Any:
    try:
        return torch.from_numpy(pixels.copy()).to(
            device=pipeline.unet.device, dtype=pipeline.unet.dtype
        )
    except torch.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc


def materialize_sdxl_ip_style_embedding(
    pipeline: Any, prepared: PreparedSdxlIpStyleEmbedding, pointer: SdxlIpStyleModelPointer
) -> BoundSdxlIpStyleEmbedding:
    try:
        pointer = SdxlIpStyleModelPointer.model_validate(pointer.model_dump(mode="json"))
        ImageEvaluationArtifactMember.model_validate(prepared.source.model_dump(mode="json"))
        SdxlIpStylePreprocessing.model_validate(prepared.preprocessing.model_dump(mode="json"))
        for sha in (prepared.encoder_input_sha256, prepared.source_rgb_sha256):
            TypeAdapter(Sha256).validate_python(sha)
        if (
            prepared.model != pointer
            or prepared.policy != ENCODER_POLICY
            or prepared.shape != CFG_SHAPE
            or not isinstance(prepared.cfg_float32_le_bytes, bytes)
            or len(prepared.cfg_float32_le_bytes) != 8192
            or prepared.cfg_float32_le_bytes[:4096] != bytes(4096)
        ):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        raw_sha = "sha256:" + hashlib.sha256(prepared.cfg_float32_le_bytes).hexdigest()
        if raw_sha != prepared.cfg_float32_le_sha256:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        import numpy as np
        import torch  # type: ignore[import-not-found]

        pixels = np.frombuffer(prepared.cfg_float32_le_bytes, dtype="<f4").reshape(CFG_SHAPE)
        if not np.isfinite(pixels).all():
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        if (
            pipeline.unet.config.encoder_hid_dim_type != "ip_image_proj"
            or pipeline.image_encoder is not None
            or pipeline.unet.dtype not in (torch.float16, torch.float32)
            or pipeline.unet.device.type not in {"cpu", "cuda"}
            or pipeline.unet.device.index not in {None, 0}
        ):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        tensor = _cast_cfg_embedding(torch, pixels, pipeline)
        value = BoundSdxlIpStyleEmbedding(
            pointer,
            raw_sha,
            str(tensor.device),
            str(tensor.dtype),
            _tensor_sha256(torch, tensor),
            tensor,
        )
        validate_bound_sdxl_ip_style_embedding(pipeline, pointer, value)
        return value
    except ProviderError:
        raise
    except MemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc


def validate_bound_sdxl_ip_style_embedding(
    pipeline: Any, pointer: SdxlIpStyleModelPointer, value: BoundSdxlIpStyleEmbedding
) -> None:
    try:
        import torch

        if (
            value.model != pointer
            or str(pipeline.unet.device) != value.device
            or str(pipeline.unet.dtype) != value.dtype
            or str(value.tensor.device) != value.device
            or str(value.tensor.dtype) != value.dtype
            or pipeline.unet.config.encoder_hid_dim_type != "ip_image_proj"
            or pipeline.image_encoder is not None
            or _tensor_sha256(torch, value.tensor) != value.cast_sha256
        ):
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
    except ProviderError:
        raise
    except (ImportError, AttributeError, TypeError, RuntimeError, ValueError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
