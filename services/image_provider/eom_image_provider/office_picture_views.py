"""Native integer viewport, quarter-turn and explicit grayscale source views."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from eom_image_contracts.office_embedded_images import OfficeEmbeddedImageSet
from eom_image_contracts.office_picture_uses import OfficePictureUse, OfficePictureView
from PIL import Image, ImageOps

from eom_image_provider.office_embedded_images import OfficeEmbeddedImageError


def render_office_picture_views(
    embedded: OfficeEmbeddedImageSet,
    uses: Sequence[OfficePictureUse],
    *,
    workspace: Path,
    grayscale_uses: frozenset[str] = frozenset(),
) -> tuple[OfficePictureView, ...]:
    """No PDF pixels, guessed boxes, resizing, white-margin trimming or label erasure.

    Work is O(distinct selected source pixels + distinct output pixels + uses).
    Whole unchanged uses reference the existing canonical local member directly.
    """
    images = {image.source_member: image for image in embedded.images}
    if not grayscale_uses.issubset({use.use_id for use in uses}):
        raise OfficeEmbeddedImageError("OFFICE_PICTURE_EFFECT_USE_MISSING")
    grouped: dict[str, list[OfficePictureUse]] = {}
    for use in uses:
        if not use.unresolved_reasons:
            if use.source_member not in images or use.geometry is None:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_VIEW_INPUT_INVALID")
            assert use.source_member is not None
            grouped.setdefault(use.source_member, []).append(use)
    output = workspace / "uses"
    output.mkdir(mode=0o700)
    rendered: dict[str, OfficePictureView] = {}
    written: set[str] = set()
    total_pixels = 0
    total_bytes = 0
    for member, selected in grouped.items():
        image = images[member]
        descriptor = os.open(
            workspace / image.member_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != image.content_length:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_IMAGE_CHANGED")
            payload = stream.read(image.content_length + 1)
        if "sha256:" + hashlib.sha256(payload).hexdigest() != image.sha256:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_IMAGE_CHANGED")
        with Image.open(io.BytesIO(payload), formats=("PNG",)) as original:
            original.load()
            if original.size != (image.width_px, image.height_px):
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_IMAGE_CHANGED")
            cache: dict[tuple[object, ...], OfficePictureView] = {}
            for use in selected:
                geometry = use.geometry
                assert geometry is not None
                box = geometry.pixel_box(width=image.width_px, height=image.height_px)
                recipe = (
                    *box,
                    geometry.clockwise_quarter_turns,
                    geometry.flip_horizontal,
                    geometry.flip_vertical,
                    use.use_id in grayscale_uses,
                )
                previous = cache.get(recipe)
                if previous is not None:
                    rendered[use.use_id] = previous.model_copy(update={"use_id": use.use_id})
                    continue
                if recipe == (0, 0, image.width_px, image.height_px, 0, False, False, False):
                    view = OfficePictureView(
                        use_id=use.use_id,
                        member_path=image.member_path,
                        sha256=image.sha256,
                        width_px=image.width_px,
                        height_px=image.height_px,
                        content_length=image.content_length,
                    )
                else:
                    cropped = original.crop(box)
                    if geometry.flip_horizontal:
                        cropped = cropped.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if geometry.flip_vertical:
                        cropped = cropped.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    for _ in range(geometry.clockwise_quarter_turns):
                        cropped = cropped.transpose(Image.Transpose.ROTATE_270)
                    if use.use_id in grayscale_uses:
                        # Deterministic luma, no threshold/dither, original alpha
                        # and every spatial pixel preserved. The source remains
                        # intact in images/, and this distinct view is hash-named.
                        rgba = cropped.convert("RGBA")
                        cropped = ImageOps.grayscale(rgba.convert("RGB")).convert("RGBA")
                        cropped.putalpha(rgba.getchannel("A"))
                    total_pixels += cropped.width * cropped.height
                    if total_pixels > 100_000_000:
                        raise OfficeEmbeddedImageError("OFFICE_PICTURE_VIEW_PIXEL_LIMIT")
                    buffer = io.BytesIO()
                    cropped.save(buffer, format="PNG", compress_level=9)
                    result = buffer.getvalue()
                    total_bytes += len(result)
                    if len(result) > 64 * 1024 * 1024 or total_bytes > 512 * 1024 * 1024:
                        raise OfficeEmbeddedImageError("OFFICE_PICTURE_VIEW_OUTPUT_LIMIT")
                    sha = "sha256:" + hashlib.sha256(result).hexdigest()
                    target = "uses/" + sha[7:] + ".png"
                    if target not in written:
                        with (workspace / target).open("xb") as stream:
                            stream.write(result)
                        written.add(target)
                    view = OfficePictureView(
                        use_id=use.use_id,
                        member_path=target,
                        sha256=sha,
                        width_px=cropped.width,
                        height_px=cropped.height,
                        content_length=len(result),
                    )
                cache[recipe] = view
                rendered[use.use_id] = view
    return tuple(rendered[use.use_id] for use in uses if use.use_id in rendered)
