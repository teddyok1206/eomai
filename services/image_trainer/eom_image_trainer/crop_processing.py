"""Deterministic, bounded crop materialization shared by LoRA training paths."""

from __future__ import annotations

import io
import warnings
from collections import defaultdict

from eom_image_contracts import ImageEvaluationBoundingBox
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

MAX_SOURCE_IMAGE_PIXELS = 50_000_000
OUTPUT_WIDTH = 768
OUTPUT_HEIGHT = 512
NEAR_DUPLICATE_HAMMING_DISTANCE = 2


class CropProcessingError(RuntimeError):
    """Stable local error for invalid or unsafe crop materialization."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def decode_png(payload: bytes) -> Image.Image:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                    raise CropProcessingError("IMAGE_TRAINING_SOURCE_PAGE_FORMAT_INVALID")
                source.load()
                return source.convert("RGB")
    except CropProcessingError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CropProcessingError("IMAGE_TRAINING_SOURCE_PAGE_TOO_LARGE") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise CropProcessingError("IMAGE_TRAINING_SOURCE_PAGE_DECODE_FAILED") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _pixel_box(
    box: ImageEvaluationBoundingBox,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left = box.left * width // 10_000
    top = box.top * height // 10_000
    right = (box.right * width + 9_999) // 10_000
    bottom = (box.bottom * height + 9_999) // 10_000
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise CropProcessingError("IMAGE_TRAINING_BOUNDING_BOX_INVALID")
    return left, top, right, bottom


def materialize_training_crop(
    source: Image.Image,
    *,
    crop_box: ImageEvaluationBoundingBox,
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...] = (),
) -> Image.Image:
    """Apply exact white redactions, grayscale, resize, and deterministic letterboxing."""

    left, top, right, bottom = _pixel_box(
        crop_box,
        width=source.width,
        height=source.height,
    )
    crop = source.crop((left, top, right, bottom)).convert("RGB")
    drawing = ImageDraw.Draw(crop)
    for redaction in redaction_boxes:
        redaction_left, redaction_top, redaction_right, redaction_bottom = _pixel_box(
            redaction,
            width=source.width,
            height=source.height,
        )
        if not (
            left <= redaction_left < redaction_right <= right
            and top <= redaction_top < redaction_bottom <= bottom
        ):
            raise CropProcessingError("IMAGE_TRAINING_REDACTION_BOX_INVALID")
        drawing.rectangle(
            (
                redaction_left - left,
                redaction_top - top,
                redaction_right - left - 1,
                redaction_bottom - top - 1,
            ),
            fill=(255, 255, 255),
        )
    grayscale = crop.convert("L")
    grayscale.thumbnail((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (OUTPUT_WIDTH, OUTPUT_HEIGHT), 255)
    offset = (
        (OUTPUT_WIDTH - grayscale.width) // 2,
        (OUTPUT_HEIGHT - grayscale.height) // 2,
    )
    canvas.paste(grayscale, offset)
    return canvas.convert("RGB")


def png_bytes(image: Image.Image) -> bytes:
    target = io.BytesIO()
    image.save(target, format="PNG", optimize=False, compress_level=9)
    payload = target.getvalue()
    if not 0 < len(payload) <= 8 * 1024 * 1024:
        raise CropProcessingError("IMAGE_TRAINING_CROP_SIZE_INVALID")
    return payload


def average_hash(image: Image.Image) -> tuple[str, int]:
    grayscale = image.convert("L")
    ink_box = ImageOps.invert(grayscale).getbbox()
    if ink_box is None:
        raise CropProcessingError("IMAGE_TRAINING_CROP_EMPTY")
    pixels = tuple(grayscale.crop(ink_box).resize((8, 8), Image.Resampling.LANCZOS).tobytes())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return f"{value:016x}", value


class PerceptualIndex:
    """Four-band candidate index for bounded Hamming-distance lookup."""

    def __init__(self) -> None:
        self._values: list[int] = []
        self._buckets: dict[tuple[int, int], set[int]] = defaultdict(set)

    def contains_near_duplicate(self, value: int) -> bool:
        candidates: set[int] = set()
        for band in range(4):
            candidates.update(self._buckets[(band, (value >> (band * 16)) & 0xFFFF)])
        return any(
            (value ^ self._values[index]).bit_count() <= NEAR_DUPLICATE_HAMMING_DISTANCE
            for index in candidates
        )

    def add(self, value: int) -> None:
        index = len(self._values)
        self._values.append(value)
        for band in range(4):
            self._buckets[(band, (value >> (band * 16)) & 0xFFFF)].add(index)
