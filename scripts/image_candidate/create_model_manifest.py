#!/usr/bin/env python3
"""Create the immutable candidate-model manifest from one verified local tree."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import (
    LocalImageModelCandidateManifest,
    content_json_bytes,
    content_sha256,
    validate_contract,
)

REVISION = "a3b4f4849157f664bdbc776fd7453c2783562f4d"
REPO_ID = "black-forest-labs/FLUX.2-klein-base-4B"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size <= 0:
            raise SystemExit("FLUX2_MANIFEST_INPUT_INVALID")
        while chunk := os.read(descriptor, 4 * 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise SystemExit("FLUX2_MANIFEST_INPUT_CHANGED")
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _files(root: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            raise SystemExit("FLUX2_MANIFEST_INPUT_INVALID")
        if stat.S_ISREG(metadata.st_mode):
            values.append(
                {
                    "relative_path": path.relative_to(root).as_posix(),
                    "size_bytes": metadata.st_size,
                    "sha256": _file_sha256(path),
                }
            )
    values.sort(key=lambda value: str(value["relative_path"]))
    if not values:
        raise SystemExit("FLUX2_MANIFEST_INPUT_EMPTY")
    return values


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--created-by", required=True)
    args = parser.parse_args()
    root = args.model_root
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise SystemExit("FLUX2_MANIFEST_ROOT_INVALID")
    files = _files(root)
    upstream = {
        "repo_id": REPO_ID,
        "revision": REVISION,
        "source_url": "https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B",
        "license_id": "Apache-2.0",
    }
    value: dict[str, object] = {
        "schema_version": "local-image-model-candidate-manifest/1.0",
        "model_id": "imgmodel_" + content_sha256(REPO_ID)[7:39],
        "model_revision_id": "imgmodelrev_"
        + content_sha256({"upstream": upstream, "files": files})[7:39],
        "provider_family": "diffusers-flux2-klein-base-4b",
        "runtime_contract_version": "eom-local-image-candidate-runner/1.0",
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "upstream": upstream,
        "files": files,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "created_by": args.created_by,
    }
    value["manifest_sha256"] = content_sha256(value)
    validate_contract("model-candidate-manifest", value)
    manifest = LocalImageModelCandidateManifest.model_validate(value)
    _write_exclusive(args.output, content_json_bytes(manifest.model_dump(mode="json")))
    print(f"FLUX2_MODEL_ID={manifest.model_id}")
    print(f"FLUX2_MODEL_REVISION_ID={manifest.model_revision_id}")
    print(f"FLUX2_MODEL_MANIFEST_SHA256={manifest.manifest_sha256}")


if __name__ == "__main__":
    main()
