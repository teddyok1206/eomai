"""One exact filesystem/media closure for terminal paired-comparison outputs."""

from __future__ import annotations

import io
import os
from pathlib import Path

from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from PIL import Image

from eom_image_provider.staged_file_io import read_staged_member, verified_directory


def validate_sdxl_pair_output_members(
    root: int,
    workspace: Path,
    outputs: tuple[SdxlLearnedComparisonOutput, ...],
    *,
    expected_owner_uid: int | None = None,
) -> None:
    owner = os.geteuid() if expected_owner_uid is None else expected_owner_uid
    expected = {path for row in outputs for path in (row.raw_member_path, row.member_path)}
    allowed = {
        "outputs",
        *("outputs/" + arm for arm in ("base", "lora")),
        *("outputs/" + arm + "/" + kind for arm in ("base", "lora") for kind in ("raw", "final")),
    }
    observed: set[str] = set()
    directories: set[str] = set()
    for parent, dirs, files in os.walk(workspace / "outputs", followlinks=False):
        relative = Path(parent).relative_to(workspace).as_posix()
        directories.add(relative)
        if relative not in allowed:
            raise ValueError("pair result has an unexpected output directory")
        with verified_directory(Path(parent), expected_owner_uid=owner):
            if any((Path(parent) / name).is_symlink() for name in dirs):
                raise ValueError("pair result has a linked output directory")
        observed.update((Path(parent) / name).relative_to(workspace).as_posix() for name in files)
    if observed != expected or directories != allowed:
        raise ValueError("pair result output closure mismatch")
    for row in outputs:
        for name, sha, size, dimensions, mode in (
            (row.member_path, row.sha256, row.size_bytes, (800, 500), "L"),
            (row.raw_member_path, row.raw_sha256, row.raw_size_bytes, (832, 512), "RGB"),
        ):
            pixels = read_staged_member(
                root, name, maximum_bytes=size, expected_sha256=sha, expected_owner_uid=owner
            )
            if len(pixels) != size:
                raise ValueError("pair replay output size mismatch")
            with Image.open(io.BytesIO(pixels)) as source:
                if (
                    source.format != "PNG"
                    or source.mode != mode
                    or source.size != dimensions
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ValueError("pair replay output format mismatch")
                source.load()
