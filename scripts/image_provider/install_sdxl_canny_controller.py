#!/usr/bin/env python3
"""Operator-only atomic publication of one evaluation-only controller revision."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import stat
import tempfile
from pathlib import Path

from eom_image_contracts.sdxl_canny_controlnet import (
    LocalImageSdxlCannyControllerManifest,
    sdxl_canny_controller_pointer,
)
from eom_image_provider.sdxl_canny_controller_io import resolve_sdxl_canny_controller
from eom_image_provider.staged_file_io import (
    copy_verified_member,
    read_staged_member,
    verified_directory,
    write_staged_member,
)


def _directory(path: Path, group: int) -> None:
    path.mkdir(mode=0o750, exist_ok=True)
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or path.is_symlink()
    ):
        raise ValueError("SDXL_CANNY_INSTALL_DIRECTORY_INVALID")
    os.chown(path, 0, group)
    path.chmod(0o750)


def install_sdxl_canny_controller(
    source: Path,
    model_store_root: Path,
    expected_manifest_sha256: str,
) -> LocalImageSdxlCannyControllerManifest:
    if os.geteuid() != 0:
        raise ValueError("SDXL_CANNY_INSTALL_REQUIRES_OPERATOR")
    source_uid = pwd.getpwnam("eom").pw_uid
    group = grp.getgrnam("eom-image").gr_gid
    # Resolve the whole acquired file set before creating a protected model directory.
    with verified_directory(source, expected_owner_uid=source_uid) as root:
        raw = read_staged_member(
            root, "manifest.json", maximum_bytes=64 * 1024, expected_owner_uid=source_uid
        )
    manifest = LocalImageSdxlCannyControllerManifest.model_validate_json(raw)
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise ValueError("SDXL_CANNY_INSTALL_MANIFEST_MISMATCH")
    pointer = sdxl_canny_controller_pointer(manifest)
    # Acquisition has a private flat folder, so validate using the same typed/fd invariants.
    with verified_directory(source, expected_owner_uid=source_uid) as origin:
        from eom_image_provider.sdxl_canny_controller_io import (
            validate_sdxl_canny_controller_metadata,
        )
        from eom_image_provider.staged_file_io import verify_staged_member

        if set(os.listdir(origin)) != {
            "manifest.json",
            *(file.relative_path for file in manifest.files),
        }:
            raise ValueError("SDXL_CANNY_INSTALL_FILE_CLOSURE_INVALID")
        for file in manifest.files:
            verify_staged_member(
                origin,
                file.relative_path,
                size_bytes=file.size_bytes,
                sha256=file.sha256,
                expected_owner_uid=source_uid,
            )
        metadata = {
            name: read_staged_member(
                origin, name, maximum_bytes=64 * 1024, expected_owner_uid=source_uid
            )
            for name in (
                "config.json",
                "README.md",
                "hub-license-identifiers.md",
                "LICENSE.standard.md",
            )
        }
        validate_sdxl_canny_controller_metadata(
            config=metadata["config.json"],
            card=metadata["README.md"],
            mapping=metadata["hub-license-identifiers.md"],
            license_text=metadata["LICENSE.standard.md"],
        )
        with verified_directory(model_store_root, expected_owner_uid=0):
            model = model_store_root / manifest.model_id
            _directory(model, group)
            final = model / manifest.model_revision_id
            if os.path.lexists(final):
                return resolve_sdxl_canny_controller(model_store_root, pointer).manifest
            staging = Path(tempfile.mkdtemp(prefix=".installing-canny-", dir=model))
            _directory(staging, group)
            with verified_directory(staging, expected_owner_uid=0) as destination:
                for file in manifest.files:
                    copy_verified_member(
                        origin,
                        destination,
                        file.relative_path,
                        size_bytes=file.size_bytes,
                        sha256=file.sha256,
                        source_owner_uid=source_uid,
                        destination_group_gid=group,
                    )
                write_staged_member(destination, "manifest.json", raw)
                os.chown(staging / "manifest.json", 0, group)
                (staging / "manifest.json").chmod(0o640)
            os.rename(staging, final)
            with verified_directory(model, expected_owner_uid=0) as descriptor:
                os.fsync(descriptor)
        # Protect publication success with a full, installed-identity resolution.
        return resolve_sdxl_canny_controller(model_store_root, pointer).manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-store-root", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    manifest = install_sdxl_canny_controller(
        args.source, args.model_store_root, args.manifest_sha256
    )
    print(
        json.dumps(
            {
                "SDXL_CANNY_CONTROLLER_INSTALL": "READY",
                "model_id": manifest.model_id,
                "model_revision_id": manifest.model_revision_id,
                "manifest_sha256": manifest.manifest_sha256,
                "production_activation": "UNCHANGED",
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
