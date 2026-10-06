"""One owned seeded generator and its actual bounded state, not a persisted RNG payload."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from eom_image_provider.provider import ProviderError


@dataclass(frozen=True, slots=True)
class PreparedSdxlGenerator:
    seed: int
    device: str
    initial_state_sha256: str
    generator: Any


def _generator_state_sha256(torch: Any, generator: Any) -> str:
    state = generator.get_state()
    if (
        state.dtype != torch.uint8
        or state.device.type != "cpu"
        or state.ndim != 1
        or not 0 < state.numel() <= 64 * 1024
    ):
        raise ProviderError("SDXL_PROBE_MODEL_INVALID")
    raw = state.numpy().tobytes(order="C")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def prepare_sdxl_generator(
    torch: Any, seed: int, *, device: Literal["cpu", "cuda"]
) -> PreparedSdxlGenerator:
    if (
        type(seed) is not int
        or not 0 <= seed <= 2**32 - 1
        or not isinstance(device, str)
        or device not in {"cpu", "cuda"}
    ):
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    try:
        generator = torch.Generator(device=device).manual_seed(seed)
        value = PreparedSdxlGenerator(
            seed, str(generator.device), _generator_state_sha256(torch, generator), generator
        )
        validate_sdxl_generator(torch, value, seed=seed)
        return value
    except ProviderError:
        raise
    except torch.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except MemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except Exception as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc


def validate_sdxl_generator(torch: Any, value: PreparedSdxlGenerator, *, seed: int) -> None:
    try:
        if (
            type(seed) is not int
            or type(value.seed) is not int
            or value.seed != seed
            or value.generator.initial_seed() != seed
            or str(value.generator.device) != value.device
            or value.generator.device.type not in {"cpu", "cuda"}
            or value.generator.device.index not in {None, 0}
            or _generator_state_sha256(torch, value.generator) != value.initial_state_sha256
        ):
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
    except ProviderError:
        raise
    except (AttributeError, TypeError, RuntimeError, ValueError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
