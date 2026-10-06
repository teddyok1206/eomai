"""Held-file global adapter attachment, not inference, dispatch or pipeline ownership."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any

from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer
from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_io import (
    VerifiedSdxlIpStyleLoadInputs,
    open_sdxl_ip_style_load_inputs,
)
from eom_image_provider.sdxl_ip_style_routing import SdxlIpStyleScaleSession


def _validate_pipeline(pipeline: Any) -> None:
    from diffusers.models.attention_processor import (  # type: ignore[import-not-found]
        AttnProcessor2_0,
    )

    unet = pipeline.unet
    if (
        tuple(unet.config.block_out_channels) != (320, 640, 1280)
        or unet.config.cross_attention_dim != 2048
        or unet.encoder_hid_proj is not None
        or unet.config.encoder_hid_dim_type is not None
        or pipeline.image_encoder is not None
        or not callable(pipeline.load_ip_adapter)
        or not callable(pipeline.set_ip_adapter_scale)
        or not unet.attn_processors
        or any(type(proc) is not AttnProcessor2_0 for proc in unet.attn_processors.values())
    ):
        raise ValueError("SDXL_IP_STYLE_PIPELINE_NOT_FRESH")


def _adapter_shapes(unet: Any) -> dict[str, tuple[int, ...]]:
    """Mirror the pinned public loader's ordered cross-attention weight IDs, O(modules)."""
    cross_dim = unet.config.cross_attention_dim
    if type(cross_dim) is not int or cross_dim <= 0:
        raise ValueError("SDXL_IP_STYLE_CROSS_DIM_INVALID")
    shapes = {
        "image_proj.proj.weight": (4 * cross_dim, 1024),
        "image_proj.proj.bias": (4 * cross_dim,),
        "image_proj.norm.weight": (cross_dim,),
        "image_proj.norm.bias": (cross_dim,),
    }
    key_id = 1
    for name in unet.attn_processors:
        if name.endswith(".attn1.processor"):
            continue
        if not name.endswith(".attn2.processor"):
            raise ValueError("SDXL_IP_STYLE_ATTENTION_NAME_INVALID")
        attention = unet.get_submodule(name.removesuffix(".processor"))
        hidden = attention.to_q.weight.shape[0]
        if tuple(attention.to_k.weight.shape) != (hidden, cross_dim) or tuple(
            attention.to_v.weight.shape
        ) != (hidden, cross_dim):
            raise ValueError("SDXL_IP_STYLE_ATTENTION_SHAPE_INVALID")
        shapes[f"ip_adapter.{key_id}.to_k_ip.weight"] = (hidden, cross_dim)
        shapes[f"ip_adapter.{key_id}.to_v_ip.weight"] = (hidden, cross_dim)
        key_id += 2
    if key_id == 1:
        raise ValueError("SDXL_IP_STYLE_CROSS_ATTENTION_MISSING")
    return shapes


def _load_held_adapter(pipeline: Any, inputs: VerifiedSdxlIpStyleLoadInputs) -> None:
    import torch  # type: ignore[import-not-found]
    from safetensors import safe_open  # type: ignore[import-not-found]

    shapes = _adapter_shapes(pipeline.unet)
    # Public loading may add IP parameters, but must never replace base/native-LoRA parameters.
    prior = dict(pipeline.unet.named_parameters())
    state: dict[str, dict[str, Any]] = {"image_proj": {}, "ip_adapter": {}}
    tensor = None
    try:
        with safe_open(f"/proc/self/fd/{inputs.adapter_weights_fd}", framework="pt") as reader:
            if set(reader.keys()) != set(shapes):
                raise ValueError("SDXL_IP_STYLE_ADAPTER_STATE_KEYS_INVALID")
            for name, shape in shapes.items():
                tensor = reader.get_tensor(name)
                if (
                    tuple(tensor.shape) != shape
                    or tensor.dtype not in (torch.float16, torch.float32)
                    or tensor.device.type != "cpu"
                    or not torch.isfinite(tensor).all().item()
                ):
                    raise ValueError("SDXL_IP_STYLE_ADAPTER_STATE_TENSOR_INVALID")
                group, _, key = name.partition(".")
                state[group][key] = tensor
            pipeline.load_ip_adapter(
                state,
                subfolder="",
                weight_name="ip-adapter_sdxl_vit-h.safetensors",
                image_encoder_folder=None,
                local_files_only=True,
                low_cpu_mem_usage=False,
            )
        current = dict(pipeline.unet.named_parameters())
        if (
            any(current.get(name) is not value for name, value in prior.items())
            or pipeline.image_encoder is not None
            or pipeline.unet.config.encoder_hid_dim_type != "ip_image_proj"
        ):
            raise ValueError("SDXL_IP_STYLE_BASE_PARAMETERS_CHANGED")
        pipeline.set_ip_adapter_scale(0.0)
    except torch.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    finally:
        state["image_proj"].clear()
        state["ip_adapter"].clear()
        prior.clear()
        tensor = None


def bind_sdxl_ip_style_adapter(
    pipeline: Any,
    model_store_root: Path,
    pointer: SdxlIpStyleModelPointer,
    routing: SdxlIpStyleRouting,
    *,
    expected_owner_uid: int = 0,
) -> SdxlIpStyleScaleSession:
    """On ANY failure caller must discard its pipeline, never retry/unload/reuse it."""
    try:
        pointer = SdxlIpStyleModelPointer.model_validate(pointer.model_dump(mode="json"))
        routing = SdxlIpStyleRouting.model_validate(routing.model_dump(mode="json"))
        for name, version in (
            ("torch", "2.7.1"),
            ("diffusers", "0.35.2"),
            ("safetensors", "0.6.2"),
        ):
            if metadata.version(name).split("+", 1)[0] != version:
                raise ValueError("SDXL_IP_STYLE_ADAPTER_RUNTIME_INVALID")
        _validate_pipeline(pipeline)
        with open_sdxl_ip_style_load_inputs(
            model_store_root, pointer, expected_owner_uid=expected_owner_uid
        ) as inputs:
            _load_held_adapter(pipeline, inputs)
            session = SdxlIpStyleScaleSession(pipeline, routing)
        return session
    except ProviderError:
        raise
    except MemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except (
        ImportError,
        AttributeError,
        KeyError,
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
    ) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
