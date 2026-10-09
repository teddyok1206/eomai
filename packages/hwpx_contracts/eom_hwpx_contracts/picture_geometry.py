"""Full-image bounds in the original HWP shape coordinate system, not PNG pixels.

This product refers to Hancom's public HWP document specification: IMAGECLIP is the
rectangle after clipping, not four crop margins. A zero-sized rectangle hides the image.
See table 122 in https://cdn.hancom.com/link/docs/한글문서파일형식3.0_HWPML_revision1.2.pdf.
"""

from __future__ import annotations


def uncropped_image_bounds(width: int, height: int) -> tuple[int, int, int, int]:
    """One O(1) rule shared by XML writers and independent output acceptance."""

    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("original image dimensions must be positive integers")
    return (0, 0, width, height)
