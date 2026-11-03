"""Orchestrator-owned isolated Office extraction; no worker NAS or DB access."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImage
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog, OfficePictureView

from eom_orchestrator.external_item_learning_page_render import (
    PdfToolRunner,
    _run_isolated,
    _trusted_executable,
)


@dataclass(frozen=True, slots=True)
class ExtractedOfficePictureUses:
    catalog: OfficePictureUseCatalog
    workspace: Path
    members: tuple[str, ...]


def extract_office_picture_use_input(
    source_bytes: bytes,
    *,
    expected_sha256: str,
    tool_root: Path,
    workspace: Path,
    python: Path | None = None,
    run: PdfToolRunner = _run_isolated,
) -> ExtractedOfficePictureUses:
    """Read authorization belongs to the caller; parsing never runs as its UID.

    The tool root is an operator-installed code release, never document/model
    input. The returned local members are still validated before NAS admission.
    """
    if (
        not 0 < len(source_bytes) <= 256 * 1024 * 1024
        or sha256_bytes(source_bytes) != expected_sha256
        or not workspace.is_absolute()
        or os.path.lexists(workspace)
        or not tool_root.is_absolute()
        or tool_root.is_symlink()
        or tool_root.resolve() != tool_root
        or re.fullmatch(r"/opt/eom/office-image-tools/[0-9a-f]{40}/site-packages", str(tool_root))
        is None
    ):
        raise ValueError("OFFICE_PICTURE_EXTRACTION_INPUT_INVALID")
    metadata = tool_root.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError("OFFICE_PICTURE_TOOL_ROOT_UNTRUSTED")
    # The interpreter belongs to the pinned CPU tool release. A developer-owned
    # HWPX Conda environment is not an executable production trust boundary.
    executable = _trusted_executable(python or tool_root.parent / "runtime/bin/python")
    bootstrap = (
        "import sys;sys.path.insert(0," + json.dumps(str(tool_root)) + ");"
        "from eom_image_provider.office_picture_uses import main;raise SystemExit(main())"
    )
    payload = run(
        executable,
        ("-I", "-B", "-c", bootstrap, "--source-sha256", expected_sha256),
        source_bytes,
        timeout_seconds=115.0,
        maximum_stdout=512 * 1024 * 1024,
    )
    return unpack_office_picture_use_input(
        payload, expected_sha256=expected_sha256, workspace=workspace
    )


def unpack_office_picture_use_input(
    payload: bytes, *, expected_sha256: str, workspace: Path
) -> ExtractedOfficePictureUses:
    """Validate sandbox output identity/closure before writing fixed local members."""
    if (
        not 0 < len(payload) <= 512 * 1024 * 1024
        or not workspace.is_absolute()
        or os.path.lexists(workspace)
    ):
        raise ValueError("OFFICE_PICTURE_EXTRACTION_OUTPUT_INVALID")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        names = [entry.filename for entry in infos]
        if (
            names != sorted(set(names))
            or len(names) > 2561
            or "picture-use-catalog.json" not in names
            or any(
                entry.flag_bits & 1
                or entry.compress_type != zipfile.ZIP_STORED
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.is_dir()
                or not 0 < entry.file_size <= 64 * 1024 * 1024
                for entry in infos
            )
            or sum(entry.file_size for entry in infos) > 512 * 1024 * 1024
            or archive.getinfo("picture-use-catalog.json").file_size > 8 * 1024 * 1024
        ):
            raise ValueError("OFFICE_PICTURE_EXTRACTION_OUTPUT_INVALID")
        manifest_bytes = archive.read("picture-use-catalog.json")
        catalog = OfficePictureUseCatalog.model_validate_json(manifest_bytes)
        if catalog.embedded_images.source_sha256 != expected_sha256:
            raise ValueError("OFFICE_PICTURE_EXTRACTION_SOURCE_MISMATCH")
        expected: dict[str, OfficeEmbeddedImage | OfficePictureView] = {
            image.member_path: image for image in catalog.embedded_images.images
        }
        for view in catalog.rendered_uses:
            prior = expected.get(view.member_path)
            if prior is not None and (
                prior.sha256,
                prior.width_px,
                prior.height_px,
                prior.content_length,
            ) != (view.sha256, view.width_px, view.height_px, view.content_length):
                raise ValueError("OFFICE_PICTURE_EXTRACTION_MEMBER_CONFLICT")
            expected[view.member_path] = view
        if set(names) != {"picture-use-catalog.json", *expected}:
            raise ValueError("OFFICE_PICTURE_EXTRACTION_OUTPUT_CLOSURE_INVALID")
        # Check every bounded member before any local publication candidate is
        # created. Do not use extractall on untrusted archive paths.
        for name, image in expected.items():
            raw = archive.read(name)
            if len(raw) != image.content_length or sha256_bytes(raw) != image.sha256:
                raise ValueError("OFFICE_PICTURE_EXTRACTION_MEMBER_HASH_MISMATCH")
            if (
                len(raw) < 33
                or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                or struct.unpack(">II", raw[16:24]) != (image.width_px, image.height_px)
                or struct.unpack(">I", raw[29:33])[0] != zlib.crc32(raw[12:29]) & 0xFFFFFFFF
            ):
                raise ValueError("OFFICE_PICTURE_EXTRACTION_PNG_INVALID")
        workspace.mkdir(mode=0o700)
        for member in names:
            path = workspace / member
            path.parent.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(archive.read(member))
    return ExtractedOfficePictureUses(catalog, workspace, tuple(names))
