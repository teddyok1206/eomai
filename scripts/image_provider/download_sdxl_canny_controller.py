#!/usr/bin/env python3
"""One pinned controller download; no snapshot, token, pickle, code or runtime network."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_controlnet import (
    SDXL_CANNY_CONTROLLER_FILES,
    LocalImageSdxlCannyControllerManifest,
    SdxlCannyControllerLicense,
)
from eom_image_contracts.validation import validate_contract
from eom_image_provider.sdxl_canny_controller_io import validate_sdxl_canny_controller_metadata

UPSTREAM = (
    "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/resolve/"
    "eb115a19a10d14909256db740ed109532ab1483c/"
)
URLS = {
    "README.md": UPSTREAM + "README.md",
    "config.json": UPSTREAM + "config.json",
    "diffusion_pytorch_model.fp16.safetensors": (
        UPSTREAM + "diffusion_pytorch_model.fp16.safetensors"
    ),
    "LICENSE.standard.md": (
        "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/"
        "462165984030d82259a11f4367a4eed129e94a7b/LICENSE.md"
    ),
    "hub-license-identifiers.md": (
        "https://raw.githubusercontent.com/huggingface/hub-docs/"
        "fd6cf1f56e1514af08c5a7262d9f79b3becb810d/docs/hub/repositories-licenses.md"
    ),
}


def _destination(path: Path) -> None:
    if (
        not path.is_absolute()
        or path.parent.parent != Path("/tmp")
        or not path.parent.name.startswith("eom-sdxl-canny-download.")
        or path.name != "controller"
        or os.path.lexists(path)
    ):
        raise ValueError("SDXL_CANNY_DOWNLOAD_DESTINATION_INVALID")
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or path.parent.is_symlink()
    ):
        raise ValueError("SDXL_CANNY_DOWNLOAD_DESTINATION_INVALID")


def _download(name: str, target: Path | None) -> bytes | None:
    expected = SDXL_CANNY_CONTROLLER_FILES[name]
    descriptor = None
    body = bytearray() if target is None else None
    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(URLS[name], timeout=60) as response:
            host = urlparse(response.url)
            if host.scheme != "https" or not (
                host.hostname
                in {
                    "huggingface.co",
                    "raw.githubusercontent.com",
                    "cdn-lfs.huggingface.co",
                }
                or (host.hostname is not None and host.hostname.endswith(".hf.co"))
            ):
                raise ValueError("SDXL_CANNY_DOWNLOAD_REDIRECT_INVALID")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("SDXL_CANNY_DOWNLOAD_ENCODING_INVALID")
            if target is not None:
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
            while chunk := response.read(min(4 * 1024**2, expected.size_bytes - received + 1)):
                received += len(chunk)
                if received > expected.size_bytes:
                    raise ValueError("SDXL_CANNY_DOWNLOAD_BUDGET_EXCEEDED")
                digest.update(chunk)
                if descriptor is not None:
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("short controller write")
                        view = view[written:]
                elif body is not None:
                    body.extend(chunk)
            if received != expected.size_bytes or "sha256:" + digest.hexdigest() != expected.sha256:
                raise ValueError("SDXL_CANNY_DOWNLOAD_HASH_MISMATCH")
            if descriptor is not None:
                os.fsync(descriptor)
            return bytes(body) if body is not None else None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def acquire_sdxl_canny_controller(destination: Path, *, preflight_only: bool = False) -> None:
    _destination(destination)
    # Establish exact card/config/license proof before any large model download or directory write.
    metadata = {
        name: _download(name, None)
        for name in sorted(URLS)
        if name != "diffusion_pytorch_model.fp16.safetensors"
    }
    if any(raw is None for raw in metadata.values()):
        raise ValueError("SDXL_CANNY_DOWNLOAD_METADATA_INVALID")
    validate_sdxl_canny_controller_metadata(
        config=metadata["config.json"] or b"",
        card=metadata["README.md"] or b"",
        mapping=metadata["hub-license-identifiers.md"] or b"",
        license_text=metadata["LICENSE.standard.md"] or b"",
    )
    print("SDXL_CANNY_LICENSE_CONFIG_PREFLIGHT=PASS weights_acquired=0", flush=True)
    if preflight_only:
        return
    os.umask(0o077)
    destination.mkdir(mode=0o700)
    for name, raw in sorted(metadata.items()):
        descriptor = os.open(
            destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw or b"")
            output.flush()
            os.fsync(output.fileno())
    _download(
        "diffusion_pytorch_model.fp16.safetensors",
        destination / "diffusion_pytorch_model.fp16.safetensors",
    )
    value = {
        "schema_version": "local-image-sdxl-canny-controller-manifest/1.0",
        "provider_family": "diffusers-sdxl-controlnet-canny",
        "runtime_contract_version": "eom-local-image-sdxl-canny-runner/1.0",
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "upstream_repo": "diffusers/controlnet-canny-sdxl-1.0",
        "upstream_revision": "eb115a19a10d14909256db740ed109532ab1483c",
        "source_url": "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0",
        "supported_base_repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "license": SdxlCannyControllerLicense().model_dump(mode="json"),
        "files": [
            SDXL_CANNY_CONTROLLER_FILES[name].model_dump(mode="json")
            for name in sorted(SDXL_CANNY_CONTROLLER_FILES)
        ],
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "created_by": "codex.image-style-goal",
    }
    value["model_id"] = (
        "imgmodel_"
        + content_sha256(
            {
                "provider_family": value["provider_family"],
                "upstream_repo": value["upstream_repo"],
            }
        )[7:39]
    )
    value["model_revision_id"] = (
        "imgmodelrev_"
        + content_sha256(
            {
                "upstream_revision": value["upstream_revision"],
                "license": value["license"],
                "files": value["files"],
            }
        )[7:39]
    )
    value["manifest_sha256"] = content_sha256(value)
    validate_contract("sdxl-canny-controller-manifest", value)
    manifest = LocalImageSdxlCannyControllerManifest.model_validate(value)
    descriptor = os.open(
        destination / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(content_json_bytes(manifest.model_dump(mode="json")))
        output.flush()
        os.fsync(output.fileno())
    print("SDXL_CANNY_CONTROLLER_ACQUIRED=" + manifest.model_revision_id, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        acquire_sdxl_canny_controller(args.destination, preflight_only=args.preflight_only)
    except (ValueError, OSError):
        print("SDXL_CANNY_CONTROLLER_ACQUISITION_FAILED", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
