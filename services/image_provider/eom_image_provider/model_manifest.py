"""Build one immutable SSD-1B file manifest from a reviewed local snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import LocalImageModelManifest, content_sha256, validate_contract

from eom_image_provider.provider import ProviderError

SSD1B_UPSTREAM_REVISION = "60987f37e94cd59c36b1cba832b9f97b57395a10"
SSD1B_REQUIRED_FILES = (
    "README.md",
    "model_index.json",
    "scheduler/scheduler_config.json",
    "text_encoder/config.json",
    "text_encoder/model.fp16.safetensors",
    "text_encoder_2/config.json",
    "text_encoder_2/model.fp16.safetensors",
    "tokenizer/added_tokens.json",
    "tokenizer/merges.txt",
    "tokenizer/special_tokens_map.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json",
    "tokenizer_2/added_tokens.json",
    "tokenizer_2/merges.txt",
    "tokenizer_2/special_tokens_map.json",
    "tokenizer_2/tokenizer_config.json",
    "tokenizer_2/vocab.json",
    "unet/config.json",
    "unet/diffusion_pytorch_model.fp16.safetensors",
    "vae/config.json",
    "vae/diffusion_pytorch_model.fp16.safetensors",
)


def create_model_manifest(
    revision_directory: Path,
    *,
    model_id: str,
    model_revision_id: str,
    approved_by: str,
) -> LocalImageModelManifest:
    _require_directory(revision_directory, mode=0o750)
    files_root = revision_directory / "files"
    _require_directory(files_root, mode=0o750)
    observed_paths: list[str] = []
    for root, directories, files in os.walk(files_root, followlinks=False):
        root_path = Path(root)
        for name in directories:
            _require_directory(root_path / name, mode=0o750)
        for name in files:
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
            observed_paths.append(path.relative_to(files_root).as_posix())
    observed = tuple(sorted(observed_paths))
    if observed != SSD1B_REQUIRED_FILES:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    file_values: list[dict[str, object]] = []
    for relative in observed:
        path = files_root / relative
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= 8 * 1024 * 1024 * 1024
            or stat.S_IMODE(metadata.st_mode) != 0o640
        ):
            raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
        file_values.append(
            {
                "relative_path": relative,
                "size_bytes": metadata.st_size,
                "sha256": _sha256_file(path),
            }
        )
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    body = {
        "schema_version": "local-image-model-manifest/1.0",
        "model_id": model_id,
        "model_revision_id": model_revision_id,
        "provider_family": "diffusers-ssd-1b",
        "runtime_contract_version": "eom-local-image-provider/1.0",
        "state": "APPROVED",
        "upstream": {
            "repo_id": "segmind/SSD-1B",
            "revision": SSD1B_UPSTREAM_REVISION,
            "source_url": "https://huggingface.co/segmind/SSD-1B",
            "license_id": "Apache-2.0",
        },
        "files": file_values,
        "created_at": now,
        "approved_at": now,
        "approved_by": approved_by,
    }
    manifest = LocalImageModelManifest.model_validate(
        {**body, "manifest_sha256": content_sha256(body)}
    )
    value = manifest.model_dump(mode="json")
    validate_contract("model-manifest", value)
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_exclusive(revision_directory / "manifest.json", payload)
    return manifest


def _require_directory(path: Path, *, mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o640)
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
