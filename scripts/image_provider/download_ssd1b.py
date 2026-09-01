#!/usr/bin/env python3
"""Download the one reviewed SSD-1B revision into a protected disposable directory."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from eom_image_provider.model_manifest import SSD1B_REQUIRED_FILES, SSD1B_UPSTREAM_REVISION
from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination: Path = args.destination
    if destination.exists() or destination.is_symlink():
        raise SystemExit("LOCAL_IMAGE_DOWNLOAD_TARGET_EXISTS")
    parent = destination.parent
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SystemExit("LOCAL_IMAGE_DOWNLOAD_PARENT_INVALID")
    snapshot_download(
        repo_id="segmind/SSD-1B",
        revision=SSD1B_UPSTREAM_REVISION,
        local_dir=destination,
        allow_patterns=list(SSD1B_REQUIRED_FILES),
        max_workers=4,
        token=False,
    )
    destination.chmod(0o700)
    total_bytes = 0
    for relative in SSD1B_REQUIRED_FILES:
        path = destination / relative
        file_metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(file_metadata.st_mode)
            or file_metadata.st_size <= 0
        ):
            raise SystemExit("LOCAL_IMAGE_DOWNLOAD_FILE_INVALID")
        total_bytes += file_metadata.st_size
    print(f"UPSTREAM_REVISION={SSD1B_UPSTREAM_REVISION}")
    print(f"REVIEWED_FILE_COUNT={len(SSD1B_REQUIRED_FILES)}")
    print(f"REVIEWED_TOTAL_BYTES={total_bytes}")


if __name__ == "__main__":
    main()
