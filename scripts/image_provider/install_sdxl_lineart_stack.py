#!/usr/bin/env python3
"""Publish one exact evaluation-only model revision to the existing protected image model store."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import stat
import tempfile
from pathlib import Path

from eom_image_contracts import (
    LocalImageSdxlLineartStack,
    SdxlLineartStackPointer,
    content_json_bytes,
    validate_contract,
)
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.staged_file_io import (
    copy_verified_member,
    read_staged_member,
    verified_directory,
    write_staged_member,
)


def _directory(path: Path, group: int) -> None:
    path.mkdir(mode=0o750, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or path.is_symlink():
        raise SystemExit("SDXL_INSTALL_DIRECTORY_INVALID")
    os.chown(path, 0, group)
    path.chmod(0o750)


def install_sdxl_stack(
    source: Path,
    model_store_root: Path,
    expected_manifest_sha256: str,
) -> LocalImageSdxlLineartStack:
    if os.geteuid() != 0:
        raise SystemExit("SDXL_INSTALL_REQUIRES_OPERATOR")
    source_uid = pwd.getpwnam("eom").pw_uid
    group = grp.getgrnam("eom-image").gr_gid
    with verified_directory(source, expected_owner_uid=source_uid) as source_root:
        raw = read_staged_member(
            source_root, "manifest.json", maximum_bytes=256 * 1024, expected_owner_uid=source_uid
        )
        value = json.loads(raw)
        validate_contract("sdxl-lineart-stack", value)
        manifest = LocalImageSdxlLineartStack.model_validate(value)
        if raw not in (content_json_bytes(value), content_json_bytes(value) + b"\n"):
            raise SystemExit("SDXL_INSTALL_MANIFEST_INVALID")
        if manifest.manifest_sha256 != expected_manifest_sha256:
            raise SystemExit("SDXL_INSTALL_MANIFEST_MISMATCH")
        pointer = SdxlLineartStackPointer(
            **manifest.model_dump(
                include={
                    "model_id",
                    "model_revision_id",
                    "manifest_sha256",
                    "provider_family",
                    "runtime_contract_version",
                }
            )
        )
        with verified_directory(model_store_root, expected_owner_uid=0):
            model = model_store_root / manifest.model_id
            _directory(model, group)
            final = model / manifest.model_revision_id
            if os.path.lexists(final):
                resolved = resolve_sdxl_stack(model_store_root, pointer)
                return resolved.manifest
            staging = Path(tempfile.mkdtemp(prefix=".installing-sdxl-", dir=model))
            _directory(staging, group)
            _directory(staging / "components", group)
            for component in manifest.components:
                relative = "components/" + component.role.lower()
                target = staging / relative
                _directory(target, group)
                for file in component.files:
                    parent = target
                    for part in Path(file.relative_path).parts[:-1]:
                        parent = parent / part
                        _directory(parent, group)
                with (
                    verified_directory(source / relative, expected_owner_uid=source_uid) as origin,
                    verified_directory(target, expected_owner_uid=0) as destination,
                ):
                    for file in component.files:
                        copy_verified_member(
                            origin,
                            destination,
                            file.relative_path,
                            size_bytes=file.size_bytes,
                            sha256=file.sha256,
                            source_owner_uid=source_uid,
                            destination_group_gid=group,
                        )
            with verified_directory(staging, expected_owner_uid=0) as descriptor:
                write_staged_member(descriptor, "manifest.json", raw)
            os.chown(staging / "manifest.json", 0, group)
            (staging / "manifest.json").chmod(0o640)
            os.rename(staging, final)
            with verified_directory(model, expected_owner_uid=0) as descriptor:
                os.fsync(descriptor)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-store-root", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    manifest = install_sdxl_stack(args.source, args.model_store_root, args.manifest_sha256)
    print(
        json.dumps(
            {
                "SDXL_STACK_INSTALL": "READY",
                "model_id": manifest.model_id,
                "model_revision_id": manifest.model_revision_id,
                "manifest_sha256": manifest.manifest_sha256,
                "state": manifest.state,
                "production_activation": "UNCHANGED",
            }
        )
    )


if __name__ == "__main__":
    main()
