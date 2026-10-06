"""Resolve the pinned optional style component without loading a tensor or copying weights."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from eom_image_contracts import (
    LocalImageSdxlIpStyleModelManifest,
    SdxlIpStyleModelPointer,
    content_json_bytes,
    validate_contract,
    validate_sdxl_ip_style_model_pointer,
)
from eom_image_contracts.models import ModelFile
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    open_verified_directory,
    read_staged_member,
    verify_staged_member,
)


@dataclass(frozen=True, slots=True)
class ResolvedSdxlIpStyleModel:
    manifest: LocalImageSdxlIpStyleModelManifest
    root: Path


@dataclass(frozen=True, slots=True)
class VerifiedSdxlIpStyleLoadInputs:
    """Read-only handles live only inside the verified model-open context, never on the wire."""

    manifest: LocalImageSdxlIpStyleModelManifest
    encoder_config: bytes
    encoder_weights_fd: int
    adapter_weights_fd: int


def validate_sdxl_ip_style_metadata(
    *,
    config: bytes,
    card: bytes,
    code_license: bytes,
    encoder_notice: bytes,
) -> None:
    value = json.loads(config)
    expected = {
        "architectures": ["CLIPVisionModelWithProjection"],
        "model_type": "clip_vision_model",
        "hidden_size": 1280,
        "intermediate_size": 5120,
        "num_attention_heads": 16,
        "num_hidden_layers": 32,
        "projection_dim": 1024,
        "image_size": 224,
        "patch_size": 14,
        "num_channels": 3,
        "torch_dtype": "float16",
    }
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
        raise ValueError("SDXL_IP_STYLE_ENCODER_CONFIG_INVALID")
    if "auto_map" in value or "trust_remote_code" in value:
        raise ValueError("SDXL_IP_STYLE_REMOTE_CONFIG_FORBIDDEN")
    for text, declaration in ((card, b"license: apache-2.0"), (encoder_notice, b"license: mit")):
        sections = text.split(b"---", 2)
        if not text.startswith(b"---\n") or len(sections) != 3:
            raise ValueError("SDXL_IP_STYLE_LICENSE_HEADER_INVALID")
        if sections[1].splitlines().count(declaration) != 1:
            raise ValueError("SDXL_IP_STYLE_LICENSE_DECLARATION_INVALID")
    if b"Apache License" not in code_license or b"Version 2.0" not in code_license:
        raise ValueError("SDXL_IP_STYLE_CODE_LICENSE_INVALID")


def _fingerprint(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
    )


def _file_snapshot(root: int, leaf: str, owner_uid: int, maximum_bytes: int) -> tuple[int, ...]:
    metadata = os.stat(leaf, dir_fd=root, follow_symlinks=False)
    # Reject special files before opening: e.g. a FIFO must not stall the bounded read.
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != owner_uid
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not 0 < metadata.st_size <= maximum_bytes
    ):
        raise ValueError("SDXL_IP_STYLE_FILE_UNSAFE")
    return _fingerprint(metadata)


@contextmanager
def _model_tree(
    root: int,
    files: tuple[ModelFile, ...],
    owner_uid: int,
) -> Iterator[Mapping[str, int]]:
    entries: dict[str, set[str]] = {"": {"manifest.json"}}
    for file in files:
        parts = file.relative_path.split("/")
        for index, name in enumerate(parts):
            entries.setdefault("/".join(parts[:index]), set()).add(name)
    with ExitStack() as stack:
        descriptors = {"": root}
        for directory in sorted(entries):
            if directory:
                parent, _, leaf = directory.rpartition("/")
                descriptor = os.open(
                    leaf,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptors[parent],
                )
                stack.callback(os.close, descriptor)
                metadata = os.fstat(descriptor)
                if metadata.st_uid != owner_uid or stat.S_IMODE(metadata.st_mode) & 0o022:
                    raise ValueError("SDXL_IP_STYLE_DIRECTORY_UNSAFE")
                descriptors[directory] = descriptor
            if set(os.listdir(descriptors[directory])) != entries[directory]:
                raise ValueError("SDXL_IP_STYLE_DIRECTORY_CLOSURE_MISMATCH")
        try:
            yield descriptors
        finally:
            for directory, descriptor in descriptors.items():
                opened = os.fstat(descriptor)
                if opened.st_uid != owner_uid or stat.S_IMODE(opened.st_mode) & 0o022:
                    raise ValueError("SDXL_IP_STYLE_DIRECTORY_UNSAFE")
                if set(os.listdir(descriptor)) != entries[directory]:
                    raise ValueError("SDXL_IP_STYLE_DIRECTORY_CLOSURE_CHANGED")
                if directory:
                    parent, _, leaf = directory.rpartition("/")
                    current = os.stat(leaf, dir_fd=descriptors[parent], follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ValueError("SDXL_IP_STYLE_DIRECTORY_IDENTITY_CHANGED")
                    if current.st_uid != owner_uid or stat.S_IMODE(current.st_mode) & 0o022:
                        raise ValueError("SDXL_IP_STYLE_DIRECTORY_UNSAFE")


@contextmanager
def _open_verified_members(
    root: int,
    manifest: LocalImageSdxlIpStyleModelManifest,
    owner_uid: int,
) -> Iterator[VerifiedSdxlIpStyleLoadInputs]:
    with (
        _model_tree(root, manifest.files, owner_uid) as descriptors,
        ExitStack() as weight_handles,
    ):
        snapshots = {}
        for file in manifest.files:
            parent, _, leaf = file.relative_path.rpartition("/")
            snapshots[file.relative_path] = _file_snapshot(
                descriptors[parent], leaf, owner_uid, file.size_bytes
            )
        metadata: dict[str, bytes] = {}
        for file in manifest.files:
            if not file.relative_path.endswith(".safetensors"):
                parent, _, leaf = file.relative_path.rpartition("/")
                payload = read_staged_member(
                    descriptors[parent],
                    leaf,
                    maximum_bytes=min(file.size_bytes, 64 * 1024),
                    expected_sha256=file.sha256,
                    expected_owner_uid=owner_uid,
                )
                if len(payload) != file.size_bytes:
                    raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
                metadata[file.relative_path] = payload
        validate_sdxl_ip_style_metadata(
            config=metadata["models/image_encoder/config.json"],
            card=metadata["README.md"],
            code_license=metadata["LICENSE.code.txt"],
            encoder_notice=metadata["NOTICE.encoder.md"],
        )
        for file in manifest.files:
            if file.relative_path.endswith(".safetensors"):
                parent, _, leaf = file.relative_path.rpartition("/")
                verify_staged_member(
                    descriptors[parent],
                    leaf,
                    size_bytes=file.size_bytes,
                    sha256=file.sha256,
                    expected_owner_uid=owner_uid,
                )
        for file in manifest.files:
            parent, _, leaf = file.relative_path.rpartition("/")
            current = os.stat(leaf, dir_fd=descriptors[parent], follow_symlinks=False)
            if snapshots[file.relative_path] != _fingerprint(current):
                raise ValueError("SDXL_IP_STYLE_FILE_IDENTITY_CHANGED")
        weights = {}
        for file in manifest.files:
            if file.relative_path.endswith(".safetensors"):
                parent, _, leaf = file.relative_path.rpartition("/")
                descriptor = os.open(
                    leaf,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=descriptors[parent],
                )
                weight_handles.callback(os.close, descriptor)
                if _fingerprint(os.fstat(descriptor)) != snapshots[file.relative_path]:
                    raise ValueError("SDXL_IP_STYLE_LOAD_FILE_CHANGED")
                weights[file.relative_path] = descriptor
        try:
            yield VerifiedSdxlIpStyleLoadInputs(
                manifest,
                metadata["models/image_encoder/config.json"],
                weights["models/image_encoder/model.safetensors"],
                weights["sdxl_models/ip-adapter_sdxl_vit-h.safetensors"],
            )
        finally:
            for file in manifest.files:
                parent, _, leaf = file.relative_path.rpartition("/")
                current = os.stat(leaf, dir_fd=descriptors[parent], follow_symlinks=False)
                if snapshots[file.relative_path] != _fingerprint(current):
                    raise ValueError("SDXL_IP_STYLE_LOAD_FILE_CHANGED")
                if (
                    file.relative_path in weights
                    and _fingerprint(os.fstat(weights[file.relative_path]))
                    != snapshots[file.relative_path]
                ):
                    raise ValueError("SDXL_IP_STYLE_LOAD_DESCRIPTOR_CHANGED")


@contextmanager
def open_sdxl_ip_style_load_inputs(
    model_store_root: Path,
    pointer: SdxlIpStyleModelPointer,
    *,
    expected_owner_uid: int = 0,
) -> Iterator[VerifiedSdxlIpStyleLoadInputs]:
    consumer_error: BaseException | None = None
    try:
        # Public adapter input is revalidated before it can select a filesystem location.
        pointer = SdxlIpStyleModelPointer.model_validate(pointer.model_dump(mode="json"))
        revision = model_store_root / pointer.model_id / pointer.model_revision_id
        with (
            open_verified_directory(
                model_store_root, expected_owner_uid=expected_owner_uid
            ) as store,
            open_verified_directory(
                revision.parent, expected_owner_uid=expected_owner_uid
            ) as parent,
            open_verified_directory(revision, expected_owner_uid=expected_owner_uid) as root,
        ):
            manifest_before = _file_snapshot(root, "manifest.json", expected_owner_uid, 64 * 1024)
            raw = read_staged_member(
                root,
                "manifest.json",
                maximum_bytes=64 * 1024,
                expected_owner_uid=expected_owner_uid,
            )
            validate_contract("sdxl-ip-style-model-manifest", json.loads(raw))
            manifest = LocalImageSdxlIpStyleModelManifest.model_validate_json(raw)
            if raw != content_json_bytes(manifest.model_dump(mode="json")):
                raise ValueError("SDXL_IP_STYLE_MANIFEST_NONCANONICAL")
            try:
                validate_sdxl_ip_style_model_pointer(pointer, manifest)
            except ValueError as exc:
                raise ProviderError("SDXL_PROBE_HASH_MISMATCH") from exc
            try:
                with _open_verified_members(root, manifest, expected_owner_uid) as inputs:
                    try:
                        yield inputs
                    except BaseException as exc:
                        consumer_error = exc
                        raise
            finally:
                if manifest_before != _fingerprint(
                    os.stat("manifest.json", dir_fd=root, follow_symlinks=False)
                ):
                    raise ValueError("SDXL_IP_STYLE_MANIFEST_IDENTITY_CHANGED")
                # Sibling revisions may be installed; check only this pinned location.
                for descriptor, location in (
                    (store, os.stat(model_store_root, follow_symlinks=False)),
                    (parent, os.stat(pointer.model_id, dir_fd=store, follow_symlinks=False)),
                    (
                        root,
                        os.stat(pointer.model_revision_id, dir_fd=parent, follow_symlinks=False),
                    ),
                ):
                    opened = os.fstat(descriptor)
                    if (location.st_dev, location.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ValueError("SDXL_IP_STYLE_REVISION_LOCATION_CHANGED")
                    if opened.st_uid != expected_owner_uid or stat.S_IMODE(opened.st_mode) & 0o022:
                        raise ValueError("SDXL_IP_STYLE_DIRECTORY_UNSAFE")
    except (ProviderError, OSError, ValueError, TypeError, KeyError, SchemaError) as exc:
        if exc is consumer_error:
            raise
        if isinstance(exc, ProviderError) and exc.code == "SDXL_PROBE_HASH_MISMATCH":
            raise
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc


def resolve_sdxl_ip_style_model(
    model_store_root: Path,
    pointer: SdxlIpStyleModelPointer,
    *,
    expected_owner_uid: int = 0,
) -> ResolvedSdxlIpStyleModel:
    """A resolution snapshot is not a later model-open capability."""
    with open_sdxl_ip_style_load_inputs(
        model_store_root,
        pointer,
        expected_owner_uid=expected_owner_uid,
    ) as inputs:
        return ResolvedSdxlIpStyleModel(
            inputs.manifest,
            model_store_root / inputs.manifest.model_id / inputs.manifest.model_revision_id,
        )
