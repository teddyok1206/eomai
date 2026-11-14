"""Closed native picture color modes; source pixels are never overwritten."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from PIL import Image, ImageMath, ImageOps


class OfficePictureColorMode(StrEnum):
    NORMAL = "REAL_PIC"
    GRAY_SCALE = "GRAY_SCALE"
    BLACK_WHITE = "BLACK_WHITE"


HWP_PICTURE_COLOR_MODES: Mapping[int, OfficePictureColorMode] = MappingProxyType(
    {
        0: OfficePictureColorMode.NORMAL,
        1: OfficePictureColorMode.GRAY_SCALE,
        2: OfficePictureColorMode.BLACK_WHITE,
    }
)
HWPX_PICTURE_COLOR_MODES: Mapping[str, OfficePictureColorMode] = MappingProxyType(
    {mode.value: mode for mode in OfficePictureColorMode}
)


def apply_office_picture_color_mode(
    image: Image.Image, mode: OfficePictureColorMode
) -> Image.Image:
    if mode is OfficePictureColorMode.NORMAL:
        return image
    rgba = image.convert("RGBA")
    if mode is OfficePictureColorMode.GRAY_SCALE:
        # Preserve the existing grayscale operation and its exact pixel values.
        result = ImageOps.grayscale(rgba.convert("RGB")).convert("RGBA")
    elif mode is OfficePictureColorMode.BLACK_WHITE:
        # LibreOffice 24.2 raster MONO: integer luminance (76R+151G+29B)>>8,
        # threshold 128, no rounding/dither. Compare before the shift exactly.
        red, green, blue, _alpha = rgba.split()
        monochrome = ImageMath.lambda_eval(
            lambda channels: (
                (channels["r"] * 76 + channels["g"] * 151 + channels["b"] * 29 >= 32768) * 255
            ),
            r=red.convert("I"),
            g=green.convert("I"),
            b=blue.convert("I"),
        )
        result = monochrome.convert("L").convert("RGBA")
    else:
        raise ValueError("OFFICE_PICTURE_EFFECT_MODE_INVALID")
    result.putalpha(rgba.getchannel("A"))
    return result
