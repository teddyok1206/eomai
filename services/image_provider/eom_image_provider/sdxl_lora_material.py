"""Bounded staged safetensors materialization for evaluation, never implicit latest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from eom_image_contracts import LocalImageSdxlLoraMicroAdapterManifest
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraAdapterManifest

from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import read_staged_member

MAX_SDXL_LORA_FILE_BYTES = 64 * 1024**2
_TARGETS = ("to_k", "to_out.0", "to_q", "to_v")


@dataclass(frozen=True, slots=True)
class SdxlLoraAdapterMaterial:
    manifest: LocalImageSdxlLoraMicroAdapterManifest | LocalImageSdxlNativeLoraAdapterManifest
    weights: bytes
    strength: float


def load_sdxl_lora_material(
    root: int,
    manifest: LocalImageSdxlLoraMicroAdapterManifest | LocalImageSdxlNativeLoraAdapterManifest,
    *,
    strength: float,
) -> SdxlLoraAdapterMaterial:
    if not 0 < strength <= 1:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    payloads = {}
    for file in manifest.files:
        limit = 64 * 1024 if file.relative_path.endswith(".json") else MAX_SDXL_LORA_FILE_BYTES
        if file.size_bytes > limit:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        raw = read_staged_member(
            root,
            "inputs/adapter/" + file.relative_path,
            maximum_bytes=file.size_bytes,
            expected_sha256=file.sha256,
            expected_owner_uid=0,
        )
        if len(raw) != file.size_bytes:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        payloads[file.relative_path] = raw
    expected = {
        "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
        "bias": "none",
        "inference_mode": True,
        "lora_alpha": 8,
        "peft_type": "LORA",
        "r": 8,
        "target_modules": list(_TARGETS),
        "task_type": None,
    }
    try:
        if json.loads(payloads["adapter_config.json"]) != expected:
            raise ValueError("unexpected adapter configuration")
    except (ValueError, TypeError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
    return SdxlLoraAdapterMaterial(manifest, payloads["adapter_model.safetensors"], strength)


def apply_sdxl_lora(unet: Any, material: SdxlLoraAdapterMaterial) -> None:
    """Load only finite exact UNet LoRA tensors via the pinned public PEFT loader."""
    try:
        from safetensors.torch import load  # type: ignore[import-not-found]

        state = load(material.weights)
        shapes = {}
        for name, module in unet.named_modules():
            if any(name.endswith("." + target) for target in _TARGETS):
                if len(module.weight.shape) != 2:
                    raise ValueError("nonlinear target")
                out_features, in_features = module.weight.shape
                shapes[name + ".lora_A.weight"] = (8, in_features)
                shapes[name + ".lora_B.weight"] = (out_features, 8)
        if not shapes or set(state) != set(shapes):
            raise ValueError("missing or unexpected LoRA target")
        for key, tensor in state.items():
            if (
                tuple(tensor.shape) != shapes[key]
                or not tensor.is_floating_point()
                or not bool(tensor.isfinite().all().item())
            ):
                raise ValueError("invalid LoRA tensor")
        unet.load_lora_adapter(
            state,
            prefix=None,
            adapter_name="exam_style",
            local_files_only=True,
            metadata={
                "r": 8,
                "lora_alpha": 8,
                "target_modules": list(_TARGETS),
                "bias": "none",
                "peft_type": "LORA",
                "rank_pattern": {},
                "alpha_pattern": {},
            },
        )
        unet.set_adapters("exam_style", weights=material.strength)
    except Exception as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
