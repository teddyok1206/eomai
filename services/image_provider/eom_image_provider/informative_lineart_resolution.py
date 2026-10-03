"""Read one exact protected extractor revision once at the tensor-validation boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from eom_image_contracts import (
    InformativeLineartPointer,
    LocalImageInformativeLineartManifest,
    content_json_bytes,
    validate_contract,
    validate_informative_lineart_pointer,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from eom_image_provider.informative_lineart_model import (
    informative_lineart_config_bytes,
    informative_lineart_license_bytes,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import read_staged_member, verified_directory


@dataclass(frozen=True)
class ResolvedInformativeLineartMaterial:
    manifest: LocalImageInformativeLineartManifest
    weight_bytes: bytes = field(repr=False)


def resolve_informative_lineart_material(
    model_store_root: Path,
    pointer: InformativeLineartPointer,
    *,
    expected_owner_uid: int = 0,
) -> ResolvedInformativeLineartMaterial:
    """FD-relative no-link checks; this does not load Torch, infer images or resolve latest."""
    try:
        pointer = InformativeLineartPointer.model_validate_json(pointer.model_dump_json())
        logical = model_store_root / pointer.extractor_id
        revision = logical / pointer.extractor_revision_id
        with (
            verified_directory(model_store_root, expected_owner_uid=expected_owner_uid),
            verified_directory(logical, expected_owner_uid=expected_owner_uid),
            verified_directory(revision, expected_owner_uid=expected_owner_uid) as root,
        ):
            raw = read_staged_member(
                root,
                "manifest.json",
                maximum_bytes=64 * 1024,
                expected_owner_uid=expected_owner_uid,
            )
            value = json.loads(raw)
            validate_contract("informative-lineart-manifest", value)
            manifest = LocalImageInformativeLineartManifest.model_validate(value)
            if raw not in (content_json_bytes(value), content_json_bytes(value) + b"\n"):
                raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
            try:
                validate_informative_lineart_pointer(pointer, manifest)
            except ValueError as exc:
                raise ProviderError("LINEART_EXTRACTOR_HASH_MISMATCH") from exc
            if set(os.listdir(root)) != {
                "manifest.json",
                *(file.relative_path for file in manifest.files),
            }:
                raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
            # Materialize each bounded file exactly once. Preserve the already-hashed weight bytes
            # for safe tensor parsing instead of reopening the model path and hashing it again.
            members = {}
            for file in manifest.files:
                payload = read_staged_member(
                    root,
                    file.relative_path,
                    maximum_bytes=file.size_bytes,
                    expected_sha256=file.sha256,
                    expected_owner_uid=expected_owner_uid,
                )
                if len(payload) != file.size_bytes:
                    raise ProviderError("LINEART_EXTRACTOR_HASH_MISMATCH")
                members[file.relative_path] = payload
            if (
                members["config.json"] != informative_lineart_config_bytes()
                or members["upstream.json"]
                != content_json_bytes(manifest.upstream.model_dump(mode="json"))
                or members["LICENSE"] != informative_lineart_license_bytes()
            ):
                raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
            return ResolvedInformativeLineartMaterial(manifest, members["model.safetensors"])
    except ProviderError as exc:
        if exc.code.startswith("LINEART_EXTRACTOR_"):
            raise
        code = (
            "LINEART_EXTRACTOR_HASH_MISMATCH"
            if exc.code == "SDXL_PROBE_HASH_MISMATCH"
            else "LINEART_EXTRACTOR_MODEL_INVALID"
        )
        raise ProviderError(code) from exc
    except (ValueError, TypeError, OSError, JsonSchemaValidationError) as exc:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID") from exc
