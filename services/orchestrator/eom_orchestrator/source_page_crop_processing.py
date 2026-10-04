"""Fixed CPU subprocess adapter; selected original pages never reach model code."""

from __future__ import annotations

import io
import json
import re
import struct
import subprocess
import zipfile
import zlib
from dataclasses import dataclass

from eom_image_contracts import ScienceSourcePageCropRegion

_TRAINER_PYTHON = "/srv/eom/conda/envs/eom-image-trainer/bin/python"
_MAX_PNG_BYTES = 8 * 1024**2
_SCRIPT = """
import io,json,sys,zipfile
from PIL import Image,__version__
from eom_image_trainer.crop_processing import decode_png,average_hash,png_bytes
recipes=json.loads(sys.argv[1])
if __version__ != sys.argv[2]:
    raise ValueError('SCIENCE_SOURCE_CROP_PILLOW_MISMATCH')
payload=sys.stdin.buffer.read(64*1024**2+1)
if not 64 <= len(payload) <= 64*1024**2:
    raise ValueError('SCIENCE_SOURCE_CROP_PAGE_SIZE_INVALID')
with Image.open(io.BytesIO(payload)) as original:
    if original.mode != 'RGB':
        raise ValueError('SCIENCE_SOURCE_CROP_PAGE_MODE_INVALID')
page=decode_png(payload)
result=io.BytesIO()
metadata=[]
with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_STORED) as archive:
    for recipe in recipes:
        if list(page.size) != recipe['page_size']:
            raise ValueError('SCIENCE_SOURCE_CROP_PAGE_DIMENSIONS_INVALID')
        left,top,right,bottom=recipe['pixel_box']
        if not (0 <= left < right <= page.width and 0 <= top < bottom <= page.height):
            raise ValueError('SCIENCE_SOURCE_CROP_BOX_INVALID')
        crop=page.crop((left,top,right,bottom))
        png=png_bytes(crop)
        perceptual_hash,_=average_hash(crop)
        archive.writestr(recipe['selection_id']+'.png',png)
        metadata.append({'selection_id':recipe['selection_id'],'perceptual_hash':perceptual_hash})
    archive.writestr('metadata.json',json.dumps(metadata,sort_keys=True,separators=(',',':')))
sys.stdout.buffer.write(result.getvalue())
"""


@dataclass(frozen=True, slots=True)
class ScienceSourcePageCropPixels:
    selection_id: str
    payload: bytes
    width_px: int
    height_px: int
    perceptual_hash: str

    def __post_init__(self) -> None:
        raw = self.payload
        if (
            re.fullmatch(r"imgsourcecrop_[0-9a-f]{32}", self.selection_id) is None
            or re.fullmatch(r"[0-9a-f]{16}", self.perceptual_hash) is None
            or not 32 <= self.width_px <= 10_000
            or not 32 <= self.height_px <= 10_000
            or not 64 <= len(raw) <= _MAX_PNG_BYTES
            or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
            or struct.unpack(">II", raw[16:24]) != (self.width_px, self.height_px)
            or raw[24:29] != b"\x08\x02\x00\x00\x00"
            or struct.unpack(">I", raw[29:33])[0] != zlib.crc32(raw[12:29])
            or raw[-12:] != b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
        ):
            raise ValueError("SCIENCE_SOURCE_CROP_PIXELS_INVALID")


def process_source_page_crops(
    payload: bytes,
    selections: tuple[ScienceSourcePageCropRegion, ...],
    *,
    pillow_version: str,
) -> tuple[ScienceSourcePageCropPixels, ...]:
    """Only typed recipes and page bytes cross the fixed, no-credentials CPU adapter."""
    if not 1 <= len(selections) <= 3 or not 64 <= len(payload) <= 64 * 1024**2:
        raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_INPUT_INVALID")
    if len({selection.source_page for selection in selections}) != 1:
        raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_PAGE_MISMATCH")
    recipes = [
        {
            "selection_id": selection.selection_id,
            "pixel_box": selection.pixel_box,
            "page_size": (selection.page_width_px, selection.page_height_px),
        }
        for selection in selections
    ]
    try:
        completed = subprocess.run(
            [
                "/usr/sbin/runuser",
                "--user",
                "eom-image",
                "--",
                _TRAINER_PYTHON,
                "-I",
                "-c",
                _SCRIPT,
                json.dumps(recipes),
                pillow_version,
            ],
            input=payload,
            capture_output=True,
            check=False,
            timeout=30,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "CUDA_VISIBLE_DEVICES": "",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_UNAVAILABLE") from exc
    if completed.returncode != 0 or not 64 <= len(completed.stdout) <= (
        len(selections) * _MAX_PNG_BYTES + 8192
    ):
        raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_FAILED")
    try:
        with zipfile.ZipFile(io.BytesIO(completed.stdout)) as archive:
            expected = {selection.selection_id + ".png" for selection in selections}
            expected.add("metadata.json")
            entries = archive.infolist()
            if len(entries) != len(expected) or {entry.filename for entry in entries} != expected:
                raise ValueError("unexpected CPU crop member closure")
            if any(
                entry.compress_type != zipfile.ZIP_STORED
                or entry.flag_bits & 1
                or not 0
                < entry.file_size
                <= (4096 if entry.filename == "metadata.json" else _MAX_PNG_BYTES)
                for entry in entries
            ):
                raise ValueError("invalid CPU crop member size/media")
            metadata = json.loads(archive.read("metadata.json"))
            if (
                not isinstance(metadata, list)
                or any(
                    not isinstance(row, dict) or set(row) != {"selection_id", "perceptual_hash"}
                    for row in metadata
                )
                or [row["selection_id"] for row in metadata]
                != [selection.selection_id for selection in selections]
            ):
                raise ValueError("invalid CPU crop metadata coverage")
            outputs = []
            for selection, row in zip(selections, metadata, strict=True):
                raw = archive.read(selection.selection_id + ".png")
                left, top, right, bottom = selection.pixel_box
                width, height = right - left, bottom - top
                outputs.append(
                    ScienceSourcePageCropPixels(
                        selection.selection_id, raw, width, height, row["perceptual_hash"]
                    )
                )
            return tuple(outputs)
    except (OSError, zipfile.BadZipFile, ValueError, TypeError, KeyError, struct.error) as exc:
        raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_OUTPUT_INVALID") from exc
