from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from eom_catalog_service.knowledge_stimulus import KnowledgeStimulusService


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _png(width: int = 800, height: int = 500) -> bytes:
    header = struct.pack(">II5B", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b"test"))
        + _chunk(b"IEND", b"")
    )


def test_fixed_knowledge_stimulus_requires_reviewed_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "stimulus.png"
    image.write_bytes(_png())
    assert KnowledgeStimulusService._validate_png(image) == (800, 500)

    image.write_bytes(_png(width=799))
    with pytest.raises(ValueError, match="dimensions"):
        KnowledgeStimulusService._validate_png(image)


def test_fixed_knowledge_stimulus_rejects_symlink_and_non_png(tmp_path: Path) -> None:
    image = tmp_path / "stimulus.png"
    image.write_bytes(_png())
    link = tmp_path / "link.png"
    link.symlink_to(image)
    with pytest.raises(ValueError, match="regular file"):
        KnowledgeStimulusService._validate_png(link)

    image.write_bytes(b"not-a-png" * 4)
    with pytest.raises(ValueError, match="header"):
        KnowledgeStimulusService._validate_png(image)
