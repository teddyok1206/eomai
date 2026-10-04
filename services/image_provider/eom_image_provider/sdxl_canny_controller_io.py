"""Verified immutable controller files and explicit Hub-linked license evidence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_canny_controlnet import (
    LocalImageSdxlCannyControllerManifest,
    SdxlCannyControllerPointer,
)
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    verify_staged_member,
)


@dataclass(frozen=True, slots=True)
class ResolvedSdxlCannyController:
    manifest: LocalImageSdxlCannyControllerManifest
    root: Path


def validate_sdxl_canny_controller_metadata(
    *,
    config: bytes,
    card: bytes,
    mapping: bytes,
    license_text: bytes,
) -> None:
    """No tensor load; configuration/card/mapping/text are independently pinned files."""
    value = json.loads(config)
    expected = {
        "_class_name": "ControlNetModel",
        "addition_embed_type": "text_time",
        "conditioning_channels": 3,
        "in_channels": 4,
        "cross_attention_dim": 2048,
        "projection_class_embeddings_input_dim": 2816,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("controller SDXL architecture mismatch")
    # The Hub author specifies a standard identifier, not a controller-local LICENSE file.
    if not card.startswith(b"---\n") or b"\nlicense: openrail++\n" not in card.split(b"---", 2)[1]:
        raise ValueError("controller license declaration missing")
    rows = [row for row in mapping.splitlines() if b"`openrail++`" in row]
    if len(rows) != 1 or (
        b"Open Rail++-M License" not in rows[0]
        or b"https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md"
        not in rows[0]
    ):
        raise ValueError("official identifier/text license mapping missing")
    if b"CreativeML Open RAIL++-M License" not in license_text:
        raise ValueError("linked standard license text missing")


def resolve_sdxl_canny_controller(
    model_store_root: Path,
    pointer: SdxlCannyControllerPointer,
    *,
    expected_owner_uid: int = 0,
) -> ResolvedSdxlCannyController:
    revision = model_store_root / pointer.model_id / pointer.model_revision_id
    try:
        with (
            verified_directory(model_store_root, expected_owner_uid=expected_owner_uid),
            verified_directory(revision.parent, expected_owner_uid=expected_owner_uid),
            verified_directory(revision, expected_owner_uid=expected_owner_uid) as root,
        ):
            raw = read_staged_member(
                root,
                "manifest.json",
                maximum_bytes=64 * 1024,
                expected_owner_uid=expected_owner_uid,
            )
            validate_contract("sdxl-canny-controller-manifest", json.loads(raw))
            manifest = LocalImageSdxlCannyControllerManifest.model_validate_json(raw)
            if raw != content_json_bytes(manifest.model_dump(mode="json")):
                raise ValueError("noncanonical controller manifest")
            if any(
                getattr(manifest, name) != getattr(pointer, name)
                for name in (
                    "model_id",
                    "model_revision_id",
                    "manifest_sha256",
                    "provider_family",
                    "runtime_contract_version",
                )
            ):
                raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
            expected = {"manifest.json", *(file.relative_path for file in manifest.files)}
            if set(os.listdir(root)) != expected:
                raise ValueError("controller exact file closure mismatch")
            for file in manifest.files:
                verify_staged_member(
                    root,
                    file.relative_path,
                    size_bytes=file.size_bytes,
                    sha256=file.sha256,
                    expected_owner_uid=expected_owner_uid,
                )
            metadata = {}
            for name in (
                "config.json",
                "README.md",
                "hub-license-identifiers.md",
                "LICENSE.standard.md",
            ):
                metadata[name] = read_staged_member(
                    root, name, maximum_bytes=64 * 1024, expected_owner_uid=expected_owner_uid
                )
            validate_sdxl_canny_controller_metadata(
                config=metadata["config.json"],
                card=metadata["README.md"],
                mapping=metadata["hub-license-identifiers.md"],
                license_text=metadata["LICENSE.standard.md"],
            )
            return ResolvedSdxlCannyController(manifest, revision)
    except (ProviderError, OSError, ValueError, TypeError, KeyError, SchemaError) as exc:
        if isinstance(exc, ProviderError) and exc.code == "SDXL_PROBE_HASH_MISMATCH":
            raise
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
