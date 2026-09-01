#!/usr/bin/env python3
"""Atomically install reviewed SSD-1B files and create their immutable manifest."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import tempfile
from pathlib import Path

from eom_image_provider.model_manifest import SSD1B_REQUIRED_FILES, create_model_manifest


def _directory(path: Path, *, owner: int, mode: int) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != owner
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise SystemExit("LOCAL_IMAGE_INSTALL_DIRECTORY_INVALID")


def _copy(source: Path, target: Path) -> None:
    metadata = source.lstat()
    if source.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        raise SystemExit("LOCAL_IMAGE_INSTALL_SOURCE_INVALID")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    target.parent.chmod(0o750)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o640)
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb", closefd=False) as output:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-store-root", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision-id", required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args()
    owner = os.geteuid()
    _directory(args.source, owner=owner, mode=0o700)
    _directory(args.model_store_root, owner=owner, mode=0o750)
    model_directory = args.model_store_root / args.model_id
    if not model_directory.exists():
        model_directory.mkdir(mode=0o750)
    _directory(model_directory, owner=owner, mode=0o750)
    final_revision = model_directory / args.model_revision_id
    if final_revision.exists() or final_revision.is_symlink():
        raise SystemExit("LOCAL_IMAGE_MODEL_REVISION_EXISTS")
    staging = Path(tempfile.mkdtemp(prefix=".installing-", dir=model_directory))
    staging.chmod(0o750)
    try:
        files_root = staging / "files"
        files_root.mkdir(mode=0o750)
        for relative in SSD1B_REQUIRED_FILES:
            _copy(args.source / relative, files_root / relative)
        manifest = create_model_manifest(
            staging,
            model_id=args.model_id,
            model_revision_id=args.model_revision_id,
            approved_by=args.approved_by,
        )
        os.rename(staging, final_revision)
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    print(f"MODEL_ID={manifest.model_id}")
    print(f"MODEL_REVISION_ID={manifest.model_revision_id}")
    print(f"MANIFEST_SHA256={manifest.manifest_sha256}")
    print(f"UPSTREAM_REVISION={manifest.upstream.revision}")


if __name__ == "__main__":
    main()
