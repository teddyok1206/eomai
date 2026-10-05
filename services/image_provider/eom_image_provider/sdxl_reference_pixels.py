"""Shared initialized-reference pixel evidence, independent of source authority."""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy
from eom_image_contracts.sdxl_canny_reference import SdxlCannyReferenceTrace
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartProbeCase
from PIL import Image

from eom_image_provider.sdxl_canny_pixels import (
    canny_png_edge_count,
    sdxl_canny_native_source_canvas,
)
from eom_image_provider.sdxl_canny_reference_backend import SdxlCannyReferencePixels
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

REFERENCE_PIXEL_DIRECTORIES = ("conditionings", "initializers")


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedSdxlReferencePixels:
    initializations: Mapping[str, SdxlCannyReferencePixels]
    traces: tuple[SdxlCannyReferenceTrace, ...]


def prepare_sdxl_reference_pixels(
    root: int,
    cases: tuple[SdxlLineartProbeCase, ...],
    originals: Mapping[str, bytes],
    *,
    policy: SdxlCannyPolicy,
    conditioner: Callable[..., bytes],
) -> PreparedSdxlReferencePixels:
    from types import MappingProxyType

    for directory in REFERENCE_PIXEL_DIRECTORIES:
        create_staged_directory(root, directory)
    initializations, traces = {}, []
    for case in cases:
        canvas = sdxl_canny_native_source_canvas(
            originals[case.case_id],
            width_px=case.reference_width_px,
            height_px=case.reference_height_px,
        )
        control = conditioner(canvas, policy=policy)
        rgb_image = canvas.convert("RGB")
        rgb = rgb_image.tobytes()
        encoded = io.BytesIO()
        rgb_image.save(encoded, format="PNG", compress_level=9)
        write_staged_member(root, "initializers/" + case.case_id + ".png", encoded.getvalue())
        write_staged_member(root, "conditionings/" + case.case_id + ".png", control)
        initializations[case.reference_image.sha256] = SdxlCannyReferencePixels(rgb, control)
        traces.append(
            SdxlCannyReferenceTrace(
                case_id=case.case_id,
                source_sha256=case.reference_image.sha256,
                conditioning_sha256=_sha(control),
                initialization_rgb_sha256=_sha(rgb),
            )
        )
    return PreparedSdxlReferencePixels(MappingProxyType(initializations), tuple(traces))


def validate_sdxl_reference_pixel_members(
    root: int,
    workspace: Path,
    traces: tuple[SdxlCannyReferenceTrace, ...],
    *,
    owner: int,
) -> None:
    expected = {trace.case_id + ".png" for trace in traces}
    for directory in REFERENCE_PIXEL_DIRECTORIES:
        with verified_directory(workspace / directory, expected_owner_uid=owner) as fd:
            if set(os.listdir(fd)) != expected:
                raise ValueError("reference derived pixel closure mismatch")
    for trace in traces:
        control = read_staged_member(
            root,
            "conditionings/" + trace.case_id + ".png",
            maximum_bytes=8 * 1024**2,
            expected_sha256=trace.conditioning_sha256,
            expected_owner_uid=owner,
        )
        canny_png_edge_count(control)
        initializer = read_staged_member(
            root,
            "initializers/" + trace.case_id + ".png",
            maximum_bytes=8 * 1024**2,
            expected_owner_uid=owner,
        )
        with Image.open(io.BytesIO(initializer)) as image:
            if (
                image.format != "PNG"
                or image.mode != "RGB"
                or image.size != (832, 512)
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("reference initializer media mismatch")
            image.load()
            if _sha(image.tobytes()) != trace.initialization_rgb_sha256:
                raise ValueError("reference initializer hash mismatch")
