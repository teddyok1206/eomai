"""Scoped style-block scales, not model loading, inference, dispatch or GPU lease ownership."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from threading import Lock
from typing import Any, Literal

from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting

from eom_image_provider.provider import ProviderError

_STYLE_KEY = re.compile(
    r"^up_blocks\.0\.attentions\.1\.transformer_blocks\.[0-9]+\.attn2\.processor$"
)
_PROCESSOR_KEY = re.compile(
    r"^(?:up_blocks\.[0-9]+|down_blocks\.[0-9]+|mid_block)"
    r"\.attentions\.[0-9]+\.transformer_blocks\.[0-9]+\.attn[12]\.processor$"
)


@dataclass(frozen=True, slots=True)
class SdxlIpStyleScaleTrace:
    arm: Literal["OFF", "ON"]
    scales: tuple[tuple[str, float], ...]


def _ip_processor_type() -> type[Any]:
    # Optional pinned numerical libraries are absent in the light type-check environment.
    from diffusers.models.attention_processor import (  # type: ignore[import-not-found]
        IPAdapterAttnProcessor2_0,
    )

    return IPAdapterAttnProcessor2_0  # type: ignore[no-any-return]


class SdxlIpStyleScaleSession:
    """Caller owns one pipeline and the external lease; failed scopes cannot be reused."""

    def __init__(self, pipeline: Any, routing: SdxlIpStyleRouting) -> None:
        try:
            self._routing = SdxlIpStyleRouting.model_validate(routing.model_dump(mode="json"))
            if metadata.version("diffusers") != "0.35.2":
                raise ValueError("SDXL_IP_STYLE_ROUTING_RUNTIME_INVALID")
            kind = _ip_processor_type()
            self._pipeline = pipeline
            self._processors = dict(pipeline.unet.attn_processors)
            self._ip_keys = frozenset(
                key for key, proc in self._processors.items() if type(proc) is kind
            )
            self._ip_order = tuple(sorted(self._ip_keys))
            self._style_keys = frozenset(key for key in self._ip_keys if _STYLE_KEY.fullmatch(key))
            if not self._style_keys or not callable(pipeline.set_ip_adapter_scale):
                raise ValueError("SDXL_IP_STYLE_ROUTING_TARGET_MISSING")
            for key in self._processors:
                if not _PROCESSOR_KEY.fullmatch(key) or (
                    key.endswith(".attn2.processor") != (key in self._ip_keys)
                ):
                    raise ValueError("SDXL_IP_STYLE_ROUTING_PROCESSOR_INVALID")
            self._lock = Lock()
            self._usable = True
            self._validate_scales("OFF")
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc

    def _validate_scales(self, arm: Literal["OFF", "ON"]) -> SdxlIpStyleScaleTrace:
        try:
            current = self._pipeline.unet.attn_processors
            if set(current) != set(self._processors) or any(
                current[key] is not proc for key, proc in self._processors.items()
            ):
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            rows = []
            for key in self._ip_order:
                scale = self._processors[key].scale
                expected = (
                    self._routing.on_scale if arm == "ON" and key in self._style_keys else 0.0
                )
                if (
                    not isinstance(scale, list)
                    or len(scale) != 1
                    or type(scale[0]) is not float
                    or scale[0] != expected
                ):
                    raise ProviderError("SDXL_PROBE_MODEL_INVALID")
                rows.append((key, expected))
            return SdxlIpStyleScaleTrace(arm, tuple(rows))
        except (AttributeError, TypeError, KeyError) as exc:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc

    def _set_scales(self, scale: float | dict[str, dict[str, list[float]]]) -> None:
        try:
            self._pipeline.set_ip_adapter_scale(scale)
        except Exception as exc:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc

    @contextmanager
    def arm(self, arm: Literal["OFF", "ON"]) -> Iterator[SdxlIpStyleScaleTrace]:
        if not isinstance(arm, str) or arm not in {"OFF", "ON"}:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        if not self._lock.acquire(blocking=False):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        try:
            if not self._usable:
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            self._validate_scales("OFF")
            try:
                self._set_scales(
                    {"up": {"block_0": [0.0, self._routing.on_scale, 0.0]}} if arm == "ON" else 0.0
                )
                trace = self._validate_scales(arm)
                yield trace
                self._validate_scales(arm)
            finally:
                self._set_scales(0.0)
                self._validate_scales("OFF")
        except BaseException:
            self._usable = False
            raise
        finally:
            self._lock.release()
