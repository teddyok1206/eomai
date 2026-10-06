"""Pinned CPU global-style embedding; no source admission, diffusion or dispatch authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from eom_image_contracts.models import ImageEvaluationArtifactMember, Sha256
from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer, SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from pydantic import TypeAdapter

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_encoder_input import (
    CLIP_BATCH_SHAPE,
    PreparedSdxlIpStyleEncoderInput,
)
from eom_image_provider.sdxl_ip_style_io import (
    VerifiedSdxlIpStyleLoadInputs,
    open_sdxl_ip_style_load_inputs,
)

CFG_SHAPE = (2, 1, 1024)
ENCODER_POLICY = "CPU_FLOAT32_EAGER_GLOBAL_CFG/1.0"


@dataclass(frozen=True, slots=True)
class PreparedSdxlIpStyleEmbedding:
    """Small immutable numerical value, not a persistent/cross-service tensor payload."""

    model: SdxlIpStyleModelPointer
    source: ImageEvaluationArtifactMember
    preprocessing: SdxlIpStylePreprocessing
    source_rgb_sha256: str
    encoder_input_sha256: str
    policy: str
    shape: tuple[int, int, int]
    cfg_float32_le_bytes: bytes
    cfg_float32_le_sha256: str


def _new_meta_encoder(config: bytes) -> Any:
    import torch  # type: ignore[import-not-found]
    from transformers import (  # type: ignore[import-not-found]
        CLIPVisionConfig,
        CLIPVisionModelWithProjection,
    )

    # Config bytes have already passed the exact upstream hash/architecture gate.
    configuration = CLIPVisionConfig(**json.loads(config), attn_implementation="eager")
    with torch.device("meta"):
        return CLIPVisionModelWithProjection(configuration)


def _encode_cpu(inputs: VerifiedSdxlIpStyleLoadInputs, pixels: Any) -> Any:
    import torch
    from safetensors import safe_open  # type: ignore[import-not-found]

    model = _new_meta_encoder(inputs.encoder_config)
    state: dict[str, Any] = {}
    expected: dict[str, Any] = {}
    tensor = None
    try:
        expected = model.state_dict()
        # Consume the held inode inside the verified scope, never reopen a model pathname.
        with safe_open(f"/proc/self/fd/{inputs.encoder_weights_fd}", framework="pt") as reader:
            if set(reader.keys()) != set(expected):
                raise ValueError("SDXL_IP_STYLE_ENCODER_STATE_KEYS_INVALID")
            for name, target in expected.items():
                tensor = reader.get_tensor(name)
                if (
                    tuple(tensor.shape) != tuple(target.shape)
                    or tensor.dtype not in (torch.float16, torch.float32)
                    or tensor.device.type != "cpu"
                    or not torch.isfinite(tensor).all().item()
                ):
                    raise ValueError("SDXL_IP_STYLE_ENCODER_STATE_TENSOR_INVALID")
                state[name] = tensor
            model.load_state_dict(state, strict=True, assign=True)
        state.clear()
        expected.clear()
        tensor = None
        model.to(dtype=torch.float32)
        # CLIP's nonpersistent position IDs are not in safetensors/state_dict.
        embeddings = model.vision_model.embeddings
        positions = embeddings.position_ids
        embeddings.register_buffer(
            "position_ids",
            torch.arange(positions.numel(), dtype=positions.dtype, device="cpu").expand((1, -1)),
            persistent=False,
        )
        if any(value.device.type != "cpu" for value in model.parameters()) or any(
            value.device.type != "cpu" for value in model.buffers()
        ):
            raise ValueError("SDXL_IP_STYLE_ENCODER_META_REMAINS")
        model.eval().requires_grad_(False)
        # Own the one bounded mutable CPU input; never pass an immutable NumPy view to Torch.
        batch = torch.from_numpy(pixels.copy())
        with torch.inference_mode():
            projected = model(
                pixel_values=batch,
                output_attentions=False,
                output_hidden_states=False,
                interpolate_pos_encoding=False,
            ).image_embeds
        return projected.detach().cpu().numpy()
    finally:
        # No model/session cache; release weights before the verified outer scope closes.
        state.clear()
        expected.clear()
        tensor = None
        del model


def encode_sdxl_ip_style_embedding(
    model_store_root: Path,
    pointer: SdxlIpStyleModelPointer,
    prepared: PreparedSdxlIpStyleEncoderInput,
    *,
    sample: SdxlNativeLoraSample,
    expected_input_sha256: Sha256,
    expected_owner_uid: int = 0,
) -> PreparedSdxlIpStyleEmbedding:
    """Caller admits TRAIN lineage; return only after final model-scope checks pass."""
    try:
        pointer = SdxlIpStyleModelPointer.model_validate(pointer.model_dump(mode="json"))
        sample = SdxlNativeLoraSample.model_validate(sample.model_dump(mode="json"))
        source = ImageEvaluationArtifactMember.model_validate(
            prepared.source.model_dump(mode="json")
        )
        profile = SdxlIpStylePreprocessing.model_validate(
            prepared.preprocessing.model_dump(mode="json")
        )
        expected = TypeAdapter(Sha256).validate_python(expected_input_sha256)
        rgb_sha = TypeAdapter(Sha256).validate_python(prepared.source_rgb_sha256)
        if (
            source != sample.source_image
            or prepared.shape != CLIP_BATCH_SHAPE
            or not isinstance(prepared.float32_le_bytes, bytes)
            or len(prepared.float32_le_bytes) != 1 * 3 * 224 * 224 * 4
        ):
            raise ValueError("SDXL_IP_STYLE_ENCODER_INPUT_INVALID")
        input_sha = "sha256:" + hashlib.sha256(prepared.float32_le_bytes).hexdigest()
        if input_sha != expected or input_sha != prepared.float32_le_sha256:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        import numpy as np

        pixels = np.frombuffer(prepared.float32_le_bytes, dtype="<f4").reshape(CLIP_BATCH_SHAPE)
        if not np.isfinite(pixels).all():
            raise ValueError("SDXL_IP_STYLE_ENCODER_PIXELS_NONFINITE")
    except (ValueError, TypeError, KeyError, ImportError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc

    try:
        for name, version in (
            ("torch", "2.7.1"),
            ("transformers", "4.56.2"),
            ("safetensors", "0.6.2"),
            ("numpy", "2.4.6"),
        ):
            if metadata.version(name).split("+", 1)[0] != version:
                raise ValueError("SDXL_IP_STYLE_ENCODER_RUNTIME_INVALID")
        with open_sdxl_ip_style_load_inputs(
            model_store_root, pointer, expected_owner_uid=expected_owner_uid
        ) as inputs:
            if inputs.manifest.preprocessing != profile:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            embedding = _encode_cpu(inputs, pixels)
            if (
                not isinstance(embedding, np.ndarray)
                or embedding.shape != (1, 1024)
                or embedding.dtype != np.dtype("float32")
                or not np.isfinite(embedding).all()
            ):
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            # Global IP adapter unconditional branch is zero EMBEDDING, not encoded zero pixels.
            conditional = np.ascontiguousarray(embedding, dtype="<f4").tobytes(order="C")
            cfg = bytes(1024 * 4) + conditional
            result = PreparedSdxlIpStyleEmbedding(
                pointer,
                source,
                profile,
                rgb_sha,
                input_sha,
                ENCODER_POLICY,
                CFG_SHAPE,
                cfg,
                "sha256:" + hashlib.sha256(cfg).hexdigest(),
            )
        return result
    except ProviderError:
        raise
    except MemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except (ValueError, TypeError, RuntimeError, OSError, KeyError, ImportError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
