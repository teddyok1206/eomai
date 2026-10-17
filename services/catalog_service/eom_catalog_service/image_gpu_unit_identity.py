"""Closed image GPU unit identities; selecting a name grants no runtime authority."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Literal

ImageGpuUnitRole = Literal["PROVIDER", "TRAINER", "PROVIDER_IN_TRAINER"]

_TEMPLATES: MappingProxyType[str, ImageGpuUnitRole] = MappingProxyType(
    {
        "eom-image-provider@.service": "PROVIDER",
        "eom-image-reference-provider@.service": "PROVIDER",
        "eom-image-reference-style-provider@.service": "PROVIDER",
        "eom-image-reference-base-provider@.service": "PROVIDER",
        "eom-image-sdxl-lineart-probe@.service": "PROVIDER",
        "eom-image-informative-lineart-extraction@.service": "PROVIDER_IN_TRAINER",
        "eom-image-sdxl-learned-comparison@.service": "PROVIDER_IN_TRAINER",
        "eom-image-sdxl-lora-evaluation@.service": "PROVIDER_IN_TRAINER",
        "eom-image-trainer@.service": "TRAINER",
        "eom-image-lora-micro-probe@.service": "TRAINER",
        "eom-image-lora-micro-evaluation@.service": "TRAINER",
        "eom-image-science-lora-micro-probe@.service": "TRAINER",
        "eom-image-science-lora-micro-evaluation@.service": "TRAINER",
        "eom-image-science-campaign-lora-micro-probe@.service": "TRAINER",
        "eom-image-science-campaign-lora-micro-evaluation@.service": "TRAINER",
        "eom-image-sdxl-lora-micro-probe@.service": "TRAINER",
        "eom-image-sdxl-native-lora@.service": "TRAINER",
        "eom-image-science-subject-benchmark@.service": "TRAINER",
        "eom-image-science-subject-multiseed@.service": "TRAINER",
    }
)


def image_gpu_unit_template(unit: str) -> str:
    if type(unit) is not str or len(unit) > 255:
        raise ValueError("IMAGE_GPU_UNIT_IDENTITY_INVALID")
    matched = re.fullmatch(r"([^@]+)@([A-Za-z0-9_][A-Za-z0-9_-]{0,159})\.service", unit, re.ASCII)
    if matched is None:
        raise ValueError("IMAGE_GPU_UNIT_IDENTITY_INVALID")
    template = matched[1] + "@.service"
    if template not in _TEMPLATES:
        raise ValueError("IMAGE_GPU_UNIT_IDENTITY_INVALID")
    return template


def image_gpu_unit_role(unit: str) -> ImageGpuUnitRole:
    return _TEMPLATES[image_gpu_unit_template(unit)]
