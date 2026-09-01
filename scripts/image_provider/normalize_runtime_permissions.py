#!/usr/bin/env python3
"""Normalize only the one binding-pinned image model revision for the fixed provider."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import stat
from pathlib import Path

from eom_image_contracts import (
    LocalImageModelManifest,
    LocalImageProviderBinding,
    validate_contract,
)


def _json(path: Path, contract: str) -> dict[str, object]:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size < 262144:
        raise SystemExit("LOCAL_IMAGE_RUNTIME_POINTER_INVALID")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SystemExit("LOCAL_IMAGE_RUNTIME_POINTER_INVALID")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise SystemExit("LOCAL_IMAGE_RUNTIME_POINTER_INVALID")
    validate_contract(contract, value)
    return value


def _require_directory(path: Path) -> None:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_INVALID")


def _require_regular(path: Path) -> None:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_INVALID")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--model-store-root", type=Path, required=True)
    parser.add_argument("--provider-group", default="eom-image")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("LOCAL_IMAGE_RUNTIME_ROOT_REQUIRED")
    root: Path = args.model_store_root
    if root != Path("/srv/eom/models/image") or not root.is_absolute():
        raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_ROOT_INVALID")
    binding = LocalImageProviderBinding.model_validate(_json(args.binding, "provider-binding"))
    revision = root / binding.model.model_id / binding.model.model_revision_id
    manifest_path = revision / "manifest.json"
    manifest = LocalImageModelManifest.model_validate(_json(manifest_path, "model-manifest"))
    if (
        manifest.model_id != binding.model.model_id
        or manifest.model_revision_id != binding.model.model_revision_id
        or manifest.manifest_sha256 != binding.model.manifest_sha256
    ):
        raise SystemExit("LOCAL_IMAGE_RUNTIME_POINTER_INVALID")
    files_root = revision / "files"
    for path in (root.parent, root, revision.parent, revision, files_root):
        _require_directory(path)
    expected = {item.relative_path: item for item in manifest.files}
    observed: set[str] = set()
    directories = {root.parent, root, revision.parent, revision, files_root}
    for current, names, files in os.walk(files_root, followlinks=False):
        current_path = Path(current)
        directories.add(current_path)
        for name in names:
            directory = current_path / name
            _require_directory(directory)
            directories.add(directory)
        for name in files:
            path = current_path / name
            _require_regular(path)
            relative = path.relative_to(files_root).as_posix()
            entry = expected.get(relative)
            if entry is None:
                raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_INVALID")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if path.stat().st_size != entry.size_bytes or (
                "sha256:" + digest.hexdigest() != entry.sha256
            ):
                raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_INVALID")
            observed.add(relative)
    if observed != set(expected):
        raise SystemExit("LOCAL_IMAGE_RUNTIME_MODEL_INVALID")
    group_id = grp.getgrnam(args.provider_group).gr_gid
    for directory in sorted(directories, key=lambda value: (len(value.parts), str(value))):
        os.chown(directory, 0, group_id, follow_symlinks=False)
        os.chmod(directory, 0o750, follow_symlinks=False)
    for relative in sorted(expected):
        path = files_root / relative
        os.chown(path, 0, group_id, follow_symlinks=False)
        os.chmod(path, 0o640, follow_symlinks=False)
    os.chown(manifest_path, 0, group_id, follow_symlinks=False)
    os.chmod(manifest_path, 0o640, follow_symlinks=False)
    print(f"MODEL_ID={manifest.model_id}")
    print(f"MODEL_REVISION_ID={manifest.model_revision_id}")
    print(f"MANIFEST_SHA256={manifest.manifest_sha256}")
    print(f"FILE_COUNT={len(expected)}")
    print("WORLD_ACCESS=DENIED")


if __name__ == "__main__":
    main()
