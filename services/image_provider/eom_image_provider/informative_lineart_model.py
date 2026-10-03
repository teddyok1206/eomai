"""Fixed attributed numerical architecture and restricted, CPU-only weight conversion.

Adapted from Caroline Chan's MIT Informative Drawings implementation, pinned by the
manifest's architecture-source SHA. See notices/informative-drawings-MIT.txt. The
upstream app and its unrestricted pickle loader are deliberately not executed.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from eom_image_contracts import InformativeLineartUpstream, content_json_bytes

from eom_image_provider.provider import ProviderError


def informative_lineart_config_bytes() -> bytes:
    """One small immutable config shared by acquisition and runtime validation."""
    return content_json_bytes(
        {
            "architecture": "RGB_INSTANCE_NORM_RESNET3_SIGMOID/1.0",
            "dtype": "float32",
            "input_channels": 3,
            "output_channels": 1,
            "residual_blocks": 3,
        }
    )


def informative_lineart_license_bytes() -> bytes:
    return files("eom_image_provider").joinpath("notices/informative-drawings-MIT.txt").read_bytes()


def informative_lineart_generator(torch: Any) -> Any:
    """Reconstruct only the fine/style-1 architecture with upstream state-dict names."""
    nn = torch.nn

    # Torch is an optional numerical adapter, loaded only by the protected image environment.
    class ResidualBlock(nn.Module):  # type: ignore[misc, name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.conv_block = nn.Sequential(
                nn.ReflectionPad2d(1),
                nn.Conv2d(256, 256, 3),
                nn.InstanceNorm2d(256),
                nn.ReLU(),
                nn.ReflectionPad2d(1),
                nn.Conv2d(256, 256, 3),
                nn.InstanceNorm2d(256),
            )

        def forward(self, value: Any) -> Any:
            return value + self.conv_block(value)

    class Generator(nn.Module):  # type: ignore[misc, name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.model0 = nn.Sequential(
                nn.ReflectionPad2d(3),
                nn.Conv2d(3, 64, 7),
                nn.InstanceNorm2d(64),
                nn.ReLU(),
            )
            self.model1 = nn.Sequential(
                nn.Conv2d(64, 128, 3, stride=2, padding=1),
                nn.InstanceNorm2d(128),
                nn.ReLU(),
                nn.Conv2d(128, 256, 3, stride=2, padding=1),
                nn.InstanceNorm2d(256),
                nn.ReLU(),
            )
            self.model2 = nn.Sequential(ResidualBlock(), ResidualBlock(), ResidualBlock())
            self.model3 = nn.Sequential(
                nn.ConvTranspose2d(256, 128, 3, stride=2, padding=1, output_padding=1),
                nn.InstanceNorm2d(128),
                nn.ReLU(),
                nn.ConvTranspose2d(128, 64, 3, stride=2, padding=1, output_padding=1),
                nn.InstanceNorm2d(64),
                nn.ReLU(),
            )
            self.model4 = nn.Sequential(nn.ReflectionPad2d(3), nn.Conv2d(64, 1, 7), nn.Sigmoid())

        def forward(self, value: Any) -> Any:
            return self.model4(self.model3(self.model2(self.model1(self.model0(value)))))

    # CPU-only conversion must remain CPU-only even if another SDK caller has changed Torch's
    # default device. Moving an already-created CUDA model to CPU would be too late.
    with torch.device("cpu"):
        return Generator().float().eval().requires_grad_(False)


def validate_informative_lineart_tensors(
    state: Mapping[str, Any],
    *,
    model: Any,
    torch: Any,
) -> None:
    """Reject extra/missing keys, non-F32 CPU tensors, wrong shape and non-finite values."""
    expected = model.state_dict()
    if set(state) != set(expected):
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
    for name, reference in expected.items():
        tensor = state[name]
        if (
            type(tensor) is not torch.Tensor
            or tensor.device.type != "cpu"
            or tensor.dtype != torch.float32
            or tensor.layout != torch.strided
            or tuple(tensor.shape) != tuple(reference.shape)
            or not bool(torch.isfinite(tensor).all())
        ):
            raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")


def load_informative_lineart_safetensors(payload: bytes, *, torch: Any) -> Any:
    if not 0 < len(payload) <= 32 * 1024**2:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
    from safetensors.torch import load  # type: ignore[import-not-found]

    try:
        state = load(payload)
        model = informative_lineart_generator(torch)
        validate_informative_lineart_tensors(state, model=model, torch=torch)
        model.load_state_dict(state, strict=True)
        return model
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID") from exc


@dataclass(frozen=True)
class InformativeLineartConversion:
    safetensors_bytes: bytes = field(repr=False)
    tensor_count: int
    parameter_count: int


def convert_informative_lineart_weights(
    payload: bytes,
    upstream: InformativeLineartUpstream,
) -> InformativeLineartConversion:
    """Acquisition owner only; verify original bytes before restricted deserialization."""
    upstream = InformativeLineartUpstream.model_validate_json(upstream.model_dump_json())
    if len(payload) != upstream.weight_bytes:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
    if "sha256:" + hashlib.sha256(payload).hexdigest() != upstream.weight_sha256:
        raise ProviderError("LINEART_EXTRACTOR_HASH_MISMATCH")
    import torch  # type: ignore[import-not-found]
    from safetensors.torch import load, save

    try:
        state = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
        if not isinstance(state, Mapping) or not all(isinstance(name, str) for name in state):
            raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
        model = informative_lineart_generator(torch)
        validate_informative_lineart_tensors(state, model=model, torch=torch)
        serialized: bytes = save({name: state[name].contiguous() for name in sorted(state)})
        if not 0 < len(serialized) <= 32 * 1024**2:
            raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
        recovered = load(serialized)
        if set(recovered) != set(state) or any(
            not torch.equal(recovered[name], state[name]) for name in state
        ):
            raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
        return InformativeLineartConversion(
            safetensors_bytes=serialized,
            tensor_count=len(state),
            parameter_count=sum(tensor.numel() for tensor in state.values()),
        )
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID") from exc
