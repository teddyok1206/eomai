#!/usr/bin/env python3
"""Acquire pinned SDXL components for local evaluation, never inference-time network I/O."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_image_contracts import (
    LocalImageSdxlLineartStack,
    SdxlLineartComponentManifest,
    content_json_bytes,
    content_sha256,
    validate_contract,
)

# Pinned acquisition candidates recorded in the approved improvement plan; never resolve main.
COMPONENTS = (
    (
        "BASE",
        "base",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "462165984030d82259a11f4367a4eed129e94a7b",
        "CreativeML-Open-RAIL++-M",
        (
            "model_index.json",
            "README.md",
            "LICENSE.md",
            "scheduler/scheduler_config.json",
            "text_encoder/config.json",
            "text_encoder/model.fp16.safetensors",
            "text_encoder_2/config.json",
            "text_encoder_2/model.fp16.safetensors",
            "unet/config.json",
            "unet/diffusion_pytorch_model.fp16.safetensors",
            "tokenizer/merges.txt",
            "tokenizer/vocab.json",
            "tokenizer/tokenizer_config.json",
            "tokenizer/special_tokens_map.json",
            "tokenizer_2/merges.txt",
            "tokenizer_2/vocab.json",
            "tokenizer_2/tokenizer_config.json",
            "tokenizer_2/special_tokens_map.json",
        ),
    ),
    (
        "LINEART_ADAPTER",
        "lineart_adapter",
        "TencentARC/t2i-adapter-lineart-sdxl-1.0",
        "5f1f33b049b96fa599f0aa3d77b31dbef5095e97",
        "Apache-2.0",
        ("config.json", "diffusion_pytorch_model.fp16.safetensors", "README.md"),
    ),
    (
        "VAE",
        "vae",
        "madebyollin/sdxl-vae-fp16-fix",
        "207b116dae70ace3637169f1ddd2434b91b3a8cd",
        "MIT",
        ("config.json", "diffusion_pytorch_model.safetensors", "README.md"),
    ),
)
MAX_DOWNLOAD_BYTES = 10 * 1024**3


def _hub_client() -> tuple[Any, Any]:
    from huggingface_hub import HfApi, hf_hub_download  # type: ignore[import-not-found]

    return HfApi(token=False), hf_hub_download


def _destination(path: Path) -> None:
    if (
        not path.is_absolute()
        or path.parent.parent != Path("/tmp")
        or not path.parent.name.startswith("eom-sdxl-lineart-download.")
        or path.name != "stack"
        or path.exists()
        or path.is_symlink()
    ):
        raise SystemExit("SDXL_DOWNLOAD_DESTINATION_INVALID")
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise SystemExit("SDXL_DOWNLOAD_DESTINATION_INVALID")


def _hash(path: Path) -> tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 8 * 1024**3
        ):
            raise SystemExit("SDXL_DOWNLOAD_FILE_INVALID")
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(descriptor, 4 * 1024**2):
            digest.update(chunk)
            count += len(chunk)
        after = os.fstat(descriptor)
        if count != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise SystemExit("SDXL_DOWNLOAD_FILE_CHANGED")
        return count, "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


def _write(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    _destination(args.destination)
    metadata: dict[tuple[str, str], Any] = {}
    total = 0
    api, download = _hub_client()
    for _, _, repo, revision, _, selected in COMPONENTS:
        info = api.model_info(repo, revision=revision, files_metadata=True, token=False)
        if info.sha != revision:
            raise SystemExit("SDXL_DOWNLOAD_REVISION_MISMATCH")
        members = {member.rfilename: member for member in info.siblings or ()}
        for name in selected:
            if name not in members:
                raise SystemExit("SDXL_DOWNLOAD_REQUIRED_MEMBER_MISSING")
            member = members[name]
            if member.size is None or not 0 < member.size <= 8 * 1024**3:
                raise SystemExit("SDXL_DOWNLOAD_SIZE_INVALID")
            metadata[(repo, name)] = member
            total += member.size
    if total > MAX_DOWNLOAD_BYTES:
        raise SystemExit("SDXL_DOWNLOAD_BUDGET_EXCEEDED")
    print(f"SDXL_DOWNLOAD_PREFLIGHT=READY bytes={total} files={len(metadata)}", flush=True)
    if args.preflight_only:
        return
    os.umask(0o077)
    args.destination.mkdir(mode=0o700)
    component_values = []
    for role, folder, repo, revision, license_id, selected in COMPONENTS:
        root = args.destination / "components" / folder
        root.mkdir(parents=True, mode=0o700)
        files = []
        for name in sorted(selected):
            path = Path(download(repo, name, revision=revision, local_dir=root, token=False))
            if path != root / name or any(
                (root / part).is_symlink() for part in path.relative_to(root).parents
            ):
                raise SystemExit("SDXL_DOWNLOAD_FILE_INVALID")
            size, sha = _hash(path)
            remote = metadata[(repo, name)]
            if size != remote.size or (
                remote.lfs is not None and sha != "sha256:" + remote.lfs.sha256
            ):
                raise SystemExit("SDXL_DOWNLOAD_HASH_MISMATCH")
            files.append({"relative_path": name, "size_bytes": size, "sha256": sha})
            print(f"SDXL_DOWNLOADED role={role} file={name} bytes={size}", flush=True)
        upstream = {
            "repo_id": repo,
            "revision": revision,
            "source_url": "https://huggingface.co/" + repo,
            "license_id": license_id,
        }
        value = {
            "role": role,
            "upstream": upstream,
            "files": files,
            "component_id": "imgstackcomponent_"
            + content_sha256({"role": role, "repo_id": repo})[7:39],
            "component_revision_id": "imgstackcomponentrev_"
            + content_sha256({"upstream": upstream, "files": files})[7:39],
        }
        value["manifest_sha256"] = content_sha256(value)
        component_values.append(
            SdxlLineartComponentManifest.model_validate(value).model_dump(mode="json")
        )
    family = "diffusers-sdxl-t2i-lineart"
    value = {
        "schema_version": "local-image-sdxl-lineart-stack/1.0",
        "provider_family": family,
        "runtime_contract_version": "eom-local-image-sdxl-lineart-runner/1.0",
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "created_by": "codex.image-style-goal",
        "components": component_values,
        "model_id": "imgmodel_"
        + content_sha256({"provider_family": family, "base_repo_id": COMPONENTS[0][2]})[7:39],
        "model_revision_id": "imgmodelrev_"
        + content_sha256({"components": component_values})[7:39],
    }
    value["manifest_sha256"] = content_sha256(value)
    validate_contract("sdxl-lineart-stack", value)
    manifest = LocalImageSdxlLineartStack.model_validate(value)
    _write(args.destination / "manifest.json", content_json_bytes(manifest.model_dump(mode="json")))
    print(
        f"SDXL_DOWNLOAD_COMPLETE model={manifest.model_id} revision={manifest.model_revision_id}",
        flush=True,
    )


if __name__ == "__main__":
    main()
